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

        # Minimal payload - extra fields cause 400 Bad Request as of 2026
        payload = {
            "userQuery": query,
            "pageInfo": {"offset": 0, "pageSize": 20},
            "targetLocation": {
                "latitude": lat,
                "longitude": lng,
            },
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

                # Fees and ETA are in the meta[] array indexed by badgeType
                delivery_fee = 0.0
                service_fee = 0.0
                eta_min = 30
                promo = None

                for meta_item in (store.get("meta") or []):
                    badge_type = meta_item.get("badgeType", "")
                    if badge_type == "FARE":
                        fare_data = (meta_item.get("badgeData") or {}).get("fare") or {}
                        delivery_fee = _parse_fee_string(
                            fare_data.get("deliveryFee", "")
                            or meta_item.get("text", "")
                        )
                        service_fee = _parse_fee_string(fare_data.get("serviceFee", ""))
                    elif badge_type == "ETD":
                        # "14 min" or accessibilityText "Delivered in 14 to 14 min"
                        eta_text = meta_item.get("accessibilityText") or meta_item.get("text") or ""
                        eta_min = _parse_eta_minutes(eta_text)

                # Rating: {text: "4.2", ...}
                rating_data = store.get("rating") or {}
                if isinstance(rating_data, dict):
                    rating_str = rating_data.get("text") or rating_data.get("ratingValue") or ""
                else:
                    rating_str = str(rating_data)
                try:
                    rating = float(rating_str) if rating_str else None
                except (ValueError, TypeError):
                    rating = None

                # Promo from signposts
                signposts = store.get("signposts") or []
                if signposts and isinstance(signposts[0], dict):
                    promo = signposts[0].get("text")

                # URL from actionUrl: "/store/dominos-45-catherine-st/pe79..."
                action_url = store.get("actionUrl") or ""
                if action_url.startswith("/"):
                    url = f"https://www.ubereats.com{action_url}"
                else:
                    url = f"https://www.ubereats.com/store/{uuid}"

                results.append(PlatformResult(
                    platform=Platform.UBER_EATS,
                    restaurant_name=name,
                    restaurant_id=uuid,
                    restaurant_url=url,
                    delivery_fee=delivery_fee,
                    service_fee=service_fee,
                    estimated_delivery_minutes=eta_min,
                    rating=rating,
                    rating_count=None,
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
            for _sid, section in (store.get("catalogSectionsMap") or {}).items():
                items = (
                    section.get("payload", {})
                    .get("standardItemsPayload", {})
                    .get("catalogItems", [])
                )
                for item in items[:50]:
                    try:
                        menu_items.append(MenuItem(
                            name=item.get("title", ""),
                            description=item.get("itemDescription"),
                            price=_cents_to_dollars(item.get("price") or 0),
                            image_url=item.get("imageUrl"),
                        ))
                    except Exception:
                        continue

            fare = store.get("fareInfo") or {}
            slug = store.get("slug") or restaurant_id
            return PlatformResult(
                platform=Platform.UBER_EATS,
                restaurant_name=store.get("title", ""),
                restaurant_id=restaurant_id,
                restaurant_url=f"https://www.ubereats.com/store/{slug}",
                menu_items=menu_items,
                delivery_fee=_cents_to_dollars(fare.get("deliveryFee") or 0),
                service_fee=_cents_to_dollars(fare.get("serviceFee") or 0),
                estimated_delivery_minutes=int((store.get("etaRange") or {}).get("min") or 30),
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[UberEats] get_restaurant failed: {e}")
            return None


def _cents_to_dollars(value) -> float:
    if value is None:
        return 0.0
    try:
        v = float(value)
        return round(v, 2) if abs(v) < 50 else round(v / 100, 2)
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
