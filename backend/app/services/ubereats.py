"""
Uber Eats scraper - Fixed for March 2026.

Key fix: endpoint must be /_p/api/getFeedV1 (not /api/getFeedV1).
Uber Eats requires browser session cookies (uev2.*) + a uev2.loc cookie
encoding the target lat/lng. x-csrf-token value "x" works once cookies are set.
"""

import json as _json
import logging
import time
import urllib.parse as _up
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ubereats.com"
FEED_URL = "https://www.ubereats.com/_p/api/getFeedV1"
STORE_URL = "https://www.ubereats.com/_p/api/getStoreV1"

# Session cookie cache: (cookies_dict, expires_at)
_session_cache: tuple[dict, float] = ({}, 0.0)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


async def _get_session_cookies() -> dict:
    """Load ubereats.com homepage, capture real session cookies. Cached 3 min."""
    global _session_cache
    cookies, expires_at = _session_cache
    if cookies and time.time() < expires_at:
        return cookies

    try:
        async with httpx.AsyncClient(
            headers={
                **_BROWSER_HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            },
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(BASE_URL)
            all_cookies = dict(resp.cookies)
            logger.debug(f"[UberEats] Session cookies: {list(all_cookies.keys())}")
            _session_cache = (all_cookies, time.time() + 180)
            return all_cookies
    except Exception as e:
        logger.warning(f"[UberEats] Failed to get session cookies: {e}")
        return {}


def _build_loc_cookie(lat: float, lng: float, address: str) -> str:
    """Build uev2.loc cookie value (URL-encoded JSON with lat/lng)."""
    loc_data = {
        "latitude": lat,
        "longitude": lng,
        "addressLine1": address,
        "addressLine2": "",
        "city": "",
        "country": "US",
        "postalCode": "",
        "region": "",
        "type": "geocode",
    }
    return _up.quote(_json.dumps(loc_data, separators=(",", ":")))


def _build_cookie_str(session_cookies: dict, lat: float, lng: float, address: str) -> str:
    cookies = {**session_cookies, "uev2.loc": _build_loc_cookie(lat, lng, address)}
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


class UberEatsScraper(BaseScraper):
    PLATFORM_NAME = "uber_eats"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)
        session_cookies = await _get_session_cookies()
        cookie_str = _build_cookie_str(session_cookies, lat, lng, location)

        headers = {
            **_BROWSER_HEADERS,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "x-csrf-token": "x",
            "Referer": "https://www.ubereats.com/feed?diningMode=DELIVERY",
            "Origin": "https://www.ubereats.com",
            "Cookie": cookie_str,
        }

        # diningMode=DELIVERY is critical — without it UberEats returns a mix of
        # delivery + pickup results (stores that only offer pickup, not delivery).
        payload = {
            "userQuery": query,
            "pageInfo": {"offset": 0, "pageSize": 80},
            "targetLocation": {
                "latitude": lat,
                "longitude": lng,
            },
            "diningMode": "DELIVERY",
        }

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=10.0,
                follow_redirects=True,
            ) as client:
                resp = await client.post(FEED_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()

            results = self._parse_feed(data, query, location)
            logger.info(f"[UberEats] {len(results)} results for '{query}'")
            return results

        except httpx.HTTPStatusError as e:
            logger.warning(
                f"[UberEats] HTTP {e.response.status_code} for '{query}': "
                f"{e.response.text[:200]}"
            )
            # Invalidate session cache on 403 so next request re-fetches cookies
            if e.response.status_code == 403:
                global _session_cache
                _session_cache = ({}, 0.0)
            return []
        except Exception as e:
            logger.warning(f"[UberEats] Search failed: {e}")
            return []

    def _parse_feed(self, data: dict, query: str, location: str) -> list[PlatformResult]:
        """Parse UberEats getFeedV1 response (2026 format).

        Response shape:
          data.feedItems[]: {uuid, type: "REGULAR_STORE", store: {
            storeUuid, title: {text}, meta: [{badgeType, ...}],
            rating: {text}, actionUrl, signposts
          }}
        Fees/ETA are in store.meta[] by badgeType:
          "FARE"  -> badgeData.fare.{deliveryFee, serviceFee} (strings like "$6.49 Delivery Fee")
          "ETD"   -> text like "14 min" or accessibilityText "Delivered in 14 to 14 min"
        """
        results = []
        try:
            top = data.get("data", data)
            if not isinstance(top, dict):
                return []
            feed_items = top.get("feedItems") or []
        except Exception:
            return []

        now = datetime.now(timezone.utc).isoformat()

        for item in feed_items:
            try:
                item_type = item.get("type", "")
                # 2026: REGULAR_STORE is the main type; also accept old names
                if item_type not in ("REGULAR_STORE", "STORE", "store", "REGULAR", "CAROUSEL_V2"):
                    continue

                store = item.get("store") or {}
                if not store:
                    continue

                uuid = store.get("storeUuid") or store.get("uuid") or store.get("id", "")

                # title is now an object: {text: "..."}
                title_val = store.get("title", "")
                if isinstance(title_val, dict):
                    name = title_val.get("text", "")
                else:
                    name = str(title_val)

                if not name or not uuid:
                    continue

                # Skip pickup-only results (actionUrl has diningMode=PICKUP).
                # We asked for DELIVERY; pickup-only stores aren't useful.
                action_url = store.get("actionUrl") or ""
                if "diningMode=PICKUP" in action_url:
                    continue

                # Grab tracking data for fallback fields (rating, ETA). We keep
                # stores that aren't accepting right now so late-night queries
                # still return results; the frontend can surface availability
                # via promo_text if we detect it.
                tracking = store.get("tracking") or {}
                store_payload = tracking.get("storePayload") or {}
                availability = store_payload.get("storeAvailablityState")

                # Still drop stores that are totally dead (no ETD badge, no
                # rating, and marked unavailable / no couriers).
                meta_badges = {
                    mi.get("badgeType")
                    for mk in ("meta", "meta2", "meta4")
                    for mi in (store.get(mk) or [])
                    if isinstance(mi, dict)
                }

                # Scan all meta arrays (meta, meta2, meta4) for fee + ETA badges.
                delivery_fee = 0.0
                service_fee = 0.0
                eta_min = 0
                fare_seen = False
                eta_text_raw = ""

                for meta_key in ("meta", "meta2", "meta4"):
                    for meta_item in (store.get(meta_key) or []):
                        if not isinstance(meta_item, dict):
                            continue
                        badge_type = meta_item.get("badgeType", "")
                        if badge_type == "FARE":
                            fare_seen = True
                            fare_data = (meta_item.get("badgeData") or {}).get("fare") or {}
                            df_text = fare_data.get("deliveryFee") or meta_item.get("text") or ""
                            if df_text:
                                delivery_fee = _parse_fee_string(df_text)
                            sf_text = fare_data.get("serviceFee") or ""
                            if sf_text:
                                service_fee = _parse_fee_string(sf_text)
                        elif badge_type == "ETD":
                            eta_text_raw = (
                                meta_item.get("accessibilityText")
                                or meta_item.get("text")
                                or ""
                            )

                # Drop stores that are currently unavailable (no real ETA).
                # Accept items with a numeric ETA, OR with a clock time (6:19AM).
                lower_eta = eta_text_raw.lower()
                if "currently unavailable" in lower_eta or "unavailable" in lower_eta:
                    continue

                # Parse ETA. "14 min" -> 14, "6:19AM" -> compute minutes from now
                import re as _re
                m_min = _re.search(r'(\d+)\s*min', eta_text_raw, _re.IGNORECASE)
                if m_min:
                    eta_min = int(m_min.group(1))
                elif _re.search(r'\d+\s*:\s*\d+\s*(?:AM|PM)', eta_text_raw, _re.IGNORECASE):
                    # "6:19AM" means next-day delivery window; use a large default.
                    eta_min = 60
                else:
                    # Fall back to scanning for any integer
                    m_any = _re.search(r'(\d+)', eta_text_raw)
                    eta_min = int(m_any.group(1)) if m_any else 0

                # Require at least one of: FARE badge, numeric ETA, or a rating.
                # Otherwise it's almost certainly a dead/inaccessible result.
                rating_data = store.get("rating") or {}
                if isinstance(rating_data, dict):
                    rating_str = rating_data.get("text") or rating_data.get("ratingValue") or ""
                else:
                    rating_str = str(rating_data)
                try:
                    rating = float(rating_str) if rating_str else None
                except (ValueError, TypeError):
                    rating = None

                # Pull rating count from tracking.storePayload.ratingInfo when present
                rating_count: Optional[int] = None
                rating_info = store_payload.get("ratingInfo") or {}
                rc_raw = rating_info.get("ratingCount")
                if rc_raw:
                    # "1,500+" / "220+" / "1500"
                    import re as _re2
                    m = _re2.search(r'(\d[\d,]*)', str(rc_raw))
                    if m:
                        try:
                            rating_count = int(m.group(1).replace(",", ""))
                        except ValueError:
                            pass

                # Prefer high-precision rating score when available
                rating_score = rating_info.get("storeRatingScore")
                if rating is None and rating_score is not None:
                    try:
                        rating = round(float(rating_score), 2)
                    except (ValueError, TypeError):
                        pass

                # Pull ETA from tracking when meta badge absent
                if eta_min == 0:
                    etd_info = store_payload.get("etdInfo") or {}
                    etd_range = etd_info.get("dropoffETARange") or {}
                    try:
                        eta_min = int(etd_range.get("min") or etd_range.get("raw") or 0)
                    except (ValueError, TypeError):
                        eta_min = 0

                if not fare_seen and eta_min == 0 and rating is None:
                    continue

                if eta_min == 0:
                    eta_min = 30

                # Promo from signposts
                promo = None
                signposts = store.get("signposts") or []
                if signposts and isinstance(signposts[0], dict):
                    promo = signposts[0].get("text")

                # Surface unavailability so the UI can warn
                if availability == "NO_COURIERS_NEARBY":
                    promo = promo or "No couriers nearby"
                elif availability == "NOT_ACCEPTING_ORDERS":
                    promo = promo or "Not accepting orders"

                if action_url.startswith("/"):
                    url = f"https://www.ubereats.com{action_url}"
                else:
                    url = f"https://www.ubereats.com/store/{uuid}"

                pickup_eta = max(5, int(eta_min * 0.5)) if eta_min else 15

                results.append(PlatformResult(
                    platform=Platform.UBER_EATS,
                    restaurant_name=name,
                    restaurant_id=uuid,
                    restaurant_url=url,
                    delivery_fee=delivery_fee,
                    service_fee=service_fee,
                    estimated_delivery_minutes=eta_min,
                    pickup_available=True,
                    pickup_fee=0.0,
                    pickup_service_fee=0.0,
                    estimated_pickup_minutes=pickup_eta,
                    rating=rating,
                    rating_count=rating_count,
                    promo_text=promo,
                    fetched_at=now,
                ))
            except Exception as e:
                logger.debug(f"[UberEats] Feed item parse error: {e}")
                continue

        return results

    async def get_restaurant(self, restaurant_id: str, location: str) -> Optional[PlatformResult]:
        lat, lng = await geocode(location)
        session_cookies = await _get_session_cookies()
        cookie_str = _build_cookie_str(session_cookies, lat, lng, location)

        headers = {
            **_BROWSER_HEADERS,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "x-csrf-token": "x",
            "Referer": "https://www.ubereats.com/",
            "Cookie": cookie_str,
        }

        try:
            async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
                resp = await client.post(STORE_URL, json={"storeUuid": restaurant_id, "diningMode": "DELIVERY"})
                resp.raise_for_status()
                data = resp.json()

            store = data.get("data", {})
            now = datetime.now(timezone.utc).isoformat()

            menu_items = []
            seen_names = set()
            for _sid, sections_list in (store.get("catalogSectionsMap") or {}).items():
                # 2026 format: each value is a LIST of section objects
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
                            name = item.get("title", "")
                            if not name or name.lower() in seen_names:
                                continue
                            price = _cents_to_dollars(item.get("price") or 0)
                            if price <= 0:
                                continue
                            seen_names.add(name.lower())
                            menu_items.append(MenuItem(
                                name=name,
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

            fare = store.get("fareInfo") or {}
            slug = store.get("slug") or restaurant_id
            delivery_eta = int((store.get("etaRange") or {}).get("min") or 30)

            # Fee parsing: fareInfo.deliveryFee can be cents (int) or a string ("$2.99 Delivery Fee").
            df_raw = fare.get("deliveryFee")
            sf_raw = fare.get("serviceFee")
            if isinstance(df_raw, str):
                delivery_fee = _parse_fee_string(df_raw)
            else:
                delivery_fee = _cents_to_dollars(df_raw or 0)
            if isinstance(sf_raw, str):
                service_fee = _parse_fee_string(sf_raw)
            else:
                service_fee = _cents_to_dollars(sf_raw or 0)

            # Name: title can be string OR dict {text: "..."} depending on endpoint version.
            title_val = store.get("title", "")
            if isinstance(title_val, dict):
                rest_name = title_val.get("text", "") or f"Store {restaurant_id}"
            else:
                rest_name = str(title_val) or f"Store {restaurant_id}"

            return PlatformResult(
                platform=Platform.UBER_EATS,
                restaurant_name=rest_name,
                restaurant_id=restaurant_id,
                restaurant_url=f"https://www.ubereats.com/store/{slug}",
                menu_items=menu_items,
                delivery_fee=delivery_fee,
                service_fee=service_fee,
                estimated_delivery_minutes=delivery_eta,
                pickup_available=True,
                pickup_fee=0.0,
                pickup_service_fee=0.0,
                estimated_pickup_minutes=max(5, int(delivery_eta * 0.5)),
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[UberEats] get_restaurant failed: {e}")
            return None


def _cents_to_dollars(value) -> float:
    """Convert a value to dollars. UberEats API returns prices in cents (integers).
    Values >= 100 are treated as cents. Values < 100 with decimals are treated as dollars.
    """
    if value is None:
        return 0.0
    try:
        v = float(value)
        if v == 0:
            return 0.0
        # UberEats prices are in cents when they're large integers
        if abs(v) >= 100:
            return round(v / 100, 2)
        # Values between 10-99 with no decimal portion are likely cents
        if abs(v) >= 10 and v == int(v):
            return round(v / 100, 2)
        # Small values or values with decimals are already dollars
        return round(v, 2)
    except (ValueError, TypeError):
        return 0.0


def _parse_fee_string(text: str) -> float:
    """Parse a fee string like '$6.49 Delivery Fee' or '' -> float dollars."""
    if not text:
        return 0.0
    import re
    m = re.search(r'\$?([\d]+(?:\.[\d]+)?)', str(text))
    if m:
        try:
            return round(float(m.group(1)), 2)
        except ValueError:
            pass
    return 0.0


def _parse_eta_minutes(text: str) -> int:
    """Parse ETA text like '14 min' or 'Delivered in 14 to 14 min' -> int minutes."""
    if not text:
        return 30
    import re
    # Find first number in string
    m = re.search(r'(\d+)', str(text))
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return 30
