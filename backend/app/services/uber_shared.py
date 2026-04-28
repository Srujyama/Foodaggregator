"""
Shared parsing helpers for the Uber Eats family of feeds (Uber Eats, Postmates).

Both surfaces hit the same backend (getFeedV1 / getStoreV1) and return the same
JSON shape, so the parsing logic lives here and the per-platform scrapers just
call into it. The Uber response surface evolves frequently, so all extractors
fail soft - they prefer correct-but-empty over crash.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from app.models.food import MenuItem, Platform, PlatformResult

logger = logging.getLogger(__name__)


def parse_fee_string(text) -> float:
    """Extract a dollar amount from a string like '$6.49 Delivery Fee', '$0', 'Free'.
    Returns 0.0 if the string explicitly says 'Free' or no number is found."""
    if text is None:
        return 0.0
    s = str(text)
    if "free" in s.lower() and not re.search(r"\$\s*[1-9]", s):
        return 0.0
    m = re.search(r"\$?\s*([0-9]+(?:\.[0-9]+)?)", s)
    if not m:
        return 0.0
    try:
        return round(float(m.group(1)), 2)
    except ValueError:
        return 0.0


def cents_to_dollars(value) -> float:
    """Convert a price value to dollars. Uber's catalog returns prices in cents
    (small integers like 599 = $5.99). Tolerates floats and dollar-style values."""
    if value is None:
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v == 0:
        return 0.0
    if abs(v) >= 100:
        return round(v / 100, 2)
    if abs(v) >= 10 and v == int(v):
        return round(v / 100, 2)
    return round(v, 2)


def _name_from_title(title) -> str:
    if isinstance(title, dict):
        return title.get("text") or ""
    return str(title or "")


def _scan_meta_for_badges(store: dict) -> dict:
    """Walk meta/meta2/meta4 and pull out FARE + ETD badges.

    Returns: {fare_seen, delivery_fee, service_fee, eta_text, eta_min, eta_max}
    """
    out = {
        "fare_seen": False,
        "delivery_fee": 0.0,
        "service_fee": 0.0,
        "eta_text": "",
        "eta_min": 0,
        "eta_max": 0,
    }
    for meta_key in ("meta", "meta2", "meta4"):
        for meta_item in (store.get(meta_key) or []):
            if not isinstance(meta_item, dict):
                continue
            badge = meta_item.get("badgeType", "")
            if badge == "FARE":
                out["fare_seen"] = True
                fare_data = (meta_item.get("badgeData") or {}).get("fare") or {}
                df_text = fare_data.get("deliveryFee") or meta_item.get("text") or ""
                if df_text:
                    out["delivery_fee"] = parse_fee_string(df_text)
                sf_text = fare_data.get("serviceFee") or ""
                if sf_text:
                    out["service_fee"] = parse_fee_string(sf_text)
            elif badge == "ETD":
                out["eta_text"] = (
                    meta_item.get("accessibilityText")
                    or meta_item.get("text")
                    or ""
                )
                m_range = re.search(
                    r"(\d+)\s*(?:to|–|-|—)\s*(\d+)\s*min",
                    out["eta_text"],
                    re.IGNORECASE,
                )
                if m_range:
                    out["eta_min"] = int(m_range.group(1))
                    out["eta_max"] = int(m_range.group(2))
                else:
                    m_min = re.search(r"(\d+)\s*min", out["eta_text"], re.IGNORECASE)
                    if m_min:
                        out["eta_min"] = int(m_min.group(1))
                        out["eta_max"] = out["eta_min"]
    return out


def _signpost_text(store: dict) -> Optional[str]:
    signposts = store.get("signposts") or []
    if signposts and isinstance(signposts[0], dict):
        return signposts[0].get("text")
    return None


def _signpost_describes_fee(text: str) -> Optional[float]:
    """Detect a free/$N delivery promotion in a signpost.

    Examples:
      "Free delivery"           -> 0.0
      "$0 Delivery Fee"         -> 0.0
      "$2.99 Delivery Fee"      -> 2.99
    Returns None if the signpost isn't about delivery fee.
    """
    if not text:
        return None
    lower = text.lower()
    if "delivery" not in lower and "deliver" not in lower:
        return None
    if "free" in lower and not re.search(r"\$\s*[1-9]", text):
        return 0.0
    m = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)", text)
    if m:
        try:
            return round(float(m.group(1)), 2)
        except ValueError:
            return None
    return None


def parse_feed_store(
    store: dict,
    platform: Platform,
    base_url: str,
    accept_pickup: bool = False,
) -> Optional[PlatformResult]:
    """Parse one store object from getFeedV1 into a PlatformResult.

    Returns None if the store isn't usable (missing id/title or marked dead).
    Set accept_pickup=True when the caller asked for diningMode=PICKUP.
    """
    try:
        uuid = (
            store.get("storeUuid")
            or store.get("uuid")
            or store.get("id")
            or ""
        )
        name = _name_from_title(store.get("title", ""))
        if not uuid or not name:
            return None

        action_url = store.get("actionUrl") or ""
        if (not accept_pickup) and "diningMode=PICKUP" in action_url:
            return None

        tracking = store.get("tracking") or {}
        store_payload = tracking.get("storePayload") or {}
        availability = store_payload.get("storeAvailablityState")
        is_orderable = store_payload.get("isOrderable")

        badges = _scan_meta_for_badges(store)

        # Pull ETA from tracking if meta didn't have it.
        if badges["eta_min"] == 0:
            etd_info = store_payload.get("etdInfo") or {}
            etd_range = etd_info.get("dropoffETARange") or {}
            try:
                badges["eta_min"] = int(etd_range.get("min") or 0)
                badges["eta_max"] = int(etd_range.get("max") or badges["eta_min"])
            except (ValueError, TypeError):
                pass

        eta_min = badges["eta_min"]
        eta_max = badges["eta_max"] or eta_min

        eta_text_lower = badges["eta_text"].lower()
        if "currently unavailable" in eta_text_lower:
            return None

        # Rating
        rating: Optional[float] = None
        rating_count: Optional[int] = None
        rating_data = store.get("rating") or {}
        if isinstance(rating_data, dict):
            rating_str = rating_data.get("text") or rating_data.get("ratingValue") or ""
            try:
                rating = float(rating_str) if rating_str else None
            except (ValueError, TypeError):
                rating = None
        rating_info = store_payload.get("ratingInfo") or {}
        rc_raw = rating_info.get("ratingCount")
        if rc_raw:
            m = re.search(r"(\d[\d,]*)", str(rc_raw))
            if m:
                try:
                    rating_count = int(m.group(1).replace(",", ""))
                except ValueError:
                    pass
        if rating is None:
            score = rating_info.get("storeRatingScore")
            if score is not None:
                try:
                    rating = round(float(score), 2)
                except (ValueError, TypeError):
                    pass

        # Drop dead listings (no fare, no eta, no rating).
        if not badges["fare_seen"] and eta_min == 0 and rating is None:
            return None
        if eta_min == 0:
            eta_min = 30
            eta_max = eta_max or 30

        # Promo + fee inference from signposts.
        promo = _signpost_text(store)
        delivery_fee = badges["delivery_fee"]
        service_fee = badges["service_fee"]
        if not badges["fare_seen"] and promo:
            inferred = _signpost_describes_fee(promo)
            if inferred is not None:
                delivery_fee = inferred

        # Status
        accepting_orders = is_orderable if is_orderable is not None else None
        status_text: Optional[str] = None
        if availability == "NO_COURIERS_NEARBY":
            status_text = "No couriers nearby"
            accepting_orders = False
        elif availability == "NOT_ACCEPTING_ORDERS":
            status_text = "Not accepting orders"
            accepting_orders = False
        if promo and not status_text and "free" in promo.lower():
            pass  # leave promo as-is

        # URL
        if action_url.startswith("/"):
            url = f"{base_url}{action_url}"
        else:
            url = f"{base_url}/store/{uuid}"

        pickup_eta = max(5, int(eta_min * 0.5)) if eta_min else 15

        return PlatformResult(
            platform=platform,
            restaurant_name=name,
            restaurant_id=uuid,
            restaurant_url=url,
            delivery_fee=delivery_fee,
            service_fee=service_fee,
            estimated_delivery_minutes=eta_min,
            estimated_delivery_minutes_max=eta_max if eta_max != eta_min else None,
            pickup_available=True,
            pickup_fee=0.0,
            pickup_service_fee=0.0,
            estimated_pickup_minutes=pickup_eta,
            rating=rating,
            rating_count=rating_count,
            promo_text=promo,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            is_open=is_orderable,
            accepting_orders=accepting_orders,
            status_text=status_text,
        )
    except Exception as e:
        logger.debug(f"[{platform.value}] feed parse error: {e}")
        return None


def parse_feed(
    data: dict,
    platform: Platform,
    base_url: str,
    accept_pickup: bool = False,
) -> list[PlatformResult]:
    results = []
    try:
        top = data.get("data", data)
        if not isinstance(top, dict):
            return []
        feed_items = top.get("feedItems") or []
    except Exception:
        return []

    for item in feed_items:
        try:
            item_type = item.get("type", "")
            if item_type not in ("REGULAR_STORE", "STORE", "store", "REGULAR", "CAROUSEL_V2"):
                continue
            store = item.get("store") or {}
            if not store:
                continue
            parsed = parse_feed_store(store, platform, base_url, accept_pickup=accept_pickup)
            if parsed is not None:
                results.append(parsed)
        except Exception as e:
            logger.debug(f"[{platform.value}] feed item error: {e}")
            continue
    return results


# ---------- Store-detail parsing (getStoreV1) ----------


def _hhmm_from_minutes(mins: int) -> str:
    """Convert minutes-from-midnight (Uber's `endTime`) to a human-readable time.
    Values >= 1440 wrap into the next day (Uber uses 1500 == 1:00 AM next day)."""
    mins = mins % 1440
    h, m = divmod(mins, 60)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"


def _parse_today_hours(store: dict) -> Optional[str]:
    """Pick today's hours from store.hours[].sectionHours and format as
    'Open until 11:00 PM' (or 'Closes at midnight'). Best-effort; returns None
    if data is missing or shape changes."""
    hours = store.get("hours") or []
    if not hours:
        return None
    today = datetime.now().strftime("%A")
    section = None
    for entry in hours:
        if not isinstance(entry, dict):
            continue
        day_range = entry.get("dayRange") or ""
        if today.lower() in day_range.lower():
            section = entry
            break
    if section is None:
        section = hours[0]
    sh = section.get("sectionHours") or []
    if not sh or not isinstance(sh[0], dict):
        return None
    end_time = sh[0].get("endTime")
    if end_time is None:
        return None
    return f"Open until {_hhmm_from_minutes(int(end_time))}"


def _detail_eta(store: dict) -> tuple[int, Optional[int]]:
    """Pull (min, max) ETA from store.etaRange."""
    eta_range = store.get("etaRange") or {}
    txt = eta_range.get("text") or eta_range.get("accessibilityText") or ""
    m_range = re.search(r"(\d+)\s*[–-]\s*(\d+)", txt)
    if m_range:
        return int(m_range.group(1)), int(m_range.group(2))
    m_one = re.search(r"(\d+)", txt)
    if m_one:
        v = int(m_one.group(1))
        return v, None
    try:
        v = int(eta_range.get("min") or 30)
        mx = int(eta_range.get("max") or 0) or None
        return v, mx
    except (TypeError, ValueError):
        return 30, None


def _detail_fees(store: dict) -> tuple[float, float, Optional[float]]:
    """Extract (delivery_fee, service_fee, minimum_order) from getStoreV1.

    UberEats deprecated fareInfo.deliveryFee on the public response - the
    structured fee now mostly lives in fareBadge.text or modalityInfo. We try
    all of them.
    """
    delivery = 0.0
    service = 0.0
    minimum = None

    fare_info = store.get("fareInfo") or {}
    sf_cents = fare_info.get("serviceFeeCents")
    if sf_cents is not None:
        service = cents_to_dollars(sf_cents)

    df_raw = fare_info.get("deliveryFee")
    if isinstance(df_raw, str):
        delivery = parse_fee_string(df_raw)
    elif df_raw is not None:
        delivery = cents_to_dollars(df_raw)

    fare_badge = store.get("fareBadge")
    if isinstance(fare_badge, dict):
        text = fare_badge.get("text") or fare_badge.get("accessibilityText") or ""
        if text and delivery == 0.0:
            v = parse_fee_string(text)
            # only take the badge if it's actually about delivery, not "Free item"
            if "deliv" in text.lower() or "$" in text:
                delivery = v

    modality = store.get("modalityInfo") or {}
    if isinstance(modality, dict):
        for k in ("deliveryFee", "deliveryFeeText"):
            val = modality.get(k)
            if val and delivery == 0.0:
                if isinstance(val, str):
                    delivery = parse_fee_string(val)
                else:
                    delivery = cents_to_dollars(val)
        for k in ("serviceFee", "serviceFeeText"):
            val = modality.get(k)
            if val and service == 0.0:
                if isinstance(val, str):
                    service = parse_fee_string(val)
                else:
                    service = cents_to_dollars(val)

    # Minimum order
    for k in ("smallOrderThreshold", "minOrderTotalCents", "minimumOrder"):
        val = (fare_info.get(k) if isinstance(fare_info, dict) else None) or store.get(k)
        if val is not None:
            try:
                if isinstance(val, str):
                    minimum = parse_fee_string(val)
                else:
                    minimum = cents_to_dollars(val)
                break
            except Exception:
                pass

    return delivery, service, minimum


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def parse_store_detail(
    data: dict,
    restaurant_id: str,
    platform: Platform,
    base_url: str,
) -> Optional[PlatformResult]:
    """Parse getStoreV1 response into a fully-populated PlatformResult."""
    store = data.get("data") if isinstance(data, dict) else {}
    if not isinstance(store, dict) or not store:
        return None

    title_val = store.get("title", "")
    name = _name_from_title(title_val) or store.get("sanitizedTitle") or f"Store {restaurant_id}"

    delivery_fee, service_fee, minimum_order = _detail_fees(store)

    eta_min, eta_max = _detail_eta(store)

    # Menu
    menu_items: list[MenuItem] = []
    seen = set()
    for _sid, sections_list in (store.get("catalogSectionsMap") or {}).items():
        if not isinstance(sections_list, list):
            sections_list = [sections_list]
        for section in sections_list:
            if not isinstance(section, dict):
                continue
            items = (
                section.get("payload", {})
                .get("standardItemsPayload", {})
                .get("catalogItems", [])
            )
            for item in items:
                try:
                    iname = item.get("title", "")
                    if not iname:
                        continue
                    key = iname.lower()
                    if key in seen:
                        continue
                    price = cents_to_dollars(item.get("price") or 0)
                    if price <= 0:
                        continue
                    seen.add(key)
                    menu_items.append(MenuItem(
                        name=iname,
                        description=item.get("itemDescription"),
                        price=price,
                        image_url=item.get("imageUrl"),
                    ))
                except Exception:
                    continue
                if len(menu_items) >= 100:
                    break
            if len(menu_items) >= 100:
                break

    location = store.get("location") or {}
    address = None
    if isinstance(location, dict):
        addr = location.get("address") or location.get("streetAddress")
        if addr:
            city = location.get("city") or ""
            region = location.get("region") or ""
            postal = location.get("postalCode") or ""
            extra = ", ".join(x for x in (city, region) if x)
            address = addr
            if extra and city.lower() not in addr.lower():
                address = f"{addr}, {extra}"
            if postal and postal not in address:
                address = f"{address} {postal}"

    distance_text = None
    distance_badge = store.get("distanceBadge")
    if isinstance(distance_badge, dict):
        distance_text = distance_badge.get("text")

    categories = []
    cats_raw = store.get("categories") or []
    if isinstance(cats_raw, list):
        categories = [c for c in cats_raw if isinstance(c, str) and c not in ("$", "$$", "$$$")]

    price_bucket = store.get("priceBucket") if isinstance(store.get("priceBucket"), str) else None

    is_open = store.get("isOpen")
    is_orderable = store.get("isOrderable")
    is_within_range = store.get("isWithinDeliveryRange")
    closed_message = store.get("closedMessage") or {}
    closed_text = None
    if isinstance(closed_message, dict):
        closed_text = closed_message.get("text") or closed_message.get("accessibilityText")
    elif isinstance(closed_message, str):
        closed_text = closed_message

    status_text = None
    if is_orderable is False:
        status_text = closed_text or "Not accepting orders"
    elif is_within_range is False:
        status_text = "Outside delivery range"

    hours_today_text = _parse_today_hours(store)
    closing_soon = None
    if hours_today_text:
        # If "Open until X PM" and now is within ~30 min of X, mark closing_soon.
        m = re.search(r"Open until (\d{1,2})(?::(\d{2}))?\s*(AM|PM)", hours_today_text)
        if m:
            try:
                h = int(m.group(1)) % 12
                if m.group(3) == "PM":
                    h += 12
                mm = int(m.group(2) or 0)
                close_total = h * 60 + mm
                now = datetime.now()
                now_total = now.hour * 60 + now.minute
                if 0 <= close_total - now_total <= 30:
                    closing_soon = True
            except Exception:
                closing_soon = None

    phone = store.get("phoneNumber") if isinstance(store.get("phoneNumber"), str) else None

    allergen_html = None
    disclaimer = store.get("disclaimerBadge")
    if isinstance(disclaimer, dict):
        allergen_html = disclaimer.get("text")

    # Promo
    promo = None
    suggested = store.get("suggestedPromotion") or store.get("promotion") or {}
    if isinstance(suggested, dict):
        promo = (
            suggested.get("title")
            or (suggested.get("titleBadge") or {}).get("text") if isinstance(suggested.get("titleBadge"), dict) else None
        )
        if not promo:
            text_obj = suggested.get("text") or suggested.get("titleText")
            if isinstance(text_obj, dict):
                promo = text_obj.get("text")
            elif isinstance(text_obj, str):
                promo = text_obj

    supports = store.get("supportedDiningModes") or []
    pickup_available = True
    if isinstance(supports, list) and supports:
        # supportedDiningModes can be list of strings or dicts
        names = []
        for s in supports:
            if isinstance(s, str):
                names.append(s.upper())
            elif isinstance(s, dict):
                m = s.get("mode") or s.get("name") or ""
                if m:
                    names.append(str(m).upper())
        if names:
            pickup_available = "PICKUP" in names

    slug = store.get("slug") or restaurant_id

    return PlatformResult(
        platform=platform,
        restaurant_name=name,
        restaurant_id=restaurant_id,
        restaurant_url=f"{base_url}/store/{slug}",
        menu_items=menu_items,
        delivery_fee=delivery_fee,
        service_fee=service_fee,
        estimated_delivery_minutes=eta_min,
        estimated_delivery_minutes_max=eta_max,
        pickup_available=pickup_available,
        pickup_fee=0.0,
        pickup_service_fee=0.0,
        estimated_pickup_minutes=max(5, int(eta_min * 0.5)) if eta_min else 15,
        minimum_order=minimum_order,
        promo_text=promo,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        is_open=bool(is_open) if is_open is not None else None,
        accepting_orders=bool(is_orderable) if is_orderable is not None else None,
        is_within_delivery_range=bool(is_within_range) if is_within_range is not None else None,
        distance_text=distance_text,
        categories=categories[:8],
        price_bucket=price_bucket,
        address=address,
        phone=phone,
        hours_today_text=hours_today_text,
        closing_soon=closing_soon,
        allergen_disclaimer_html=allergen_html,
        status_text=status_text,
    )
