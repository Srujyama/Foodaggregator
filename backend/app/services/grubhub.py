"""
Grubhub scraper - April 2026.

Two strategies:
1. API-based: Uses api-gtm.grubhub.com with a bearer token (env var).
2. curl_cffi session: Creates a browser-like session to obtain an anonymous
   token via curl_cffi (bypasses PerimeterX TLS fingerprinting).

Set GRUBHUB_BEARER_TOKEN for best results; the scraper attempts anonymous
auth via curl_cffi automatically.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx
from curl_cffi import requests as cffi_requests

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

logger = logging.getLogger(__name__)

GH_SEARCH_API = "https://api-gtm.grubhub.com/restaurants/search/search_listing"
GH_SEARCH_LEGACY = "https://api-gtm.grubhub.com/restaurants/search"
GH_RESTAURANT_API = "https://api-gtm.grubhub.com/restaurants/{restaurant_id}"
GH_AUTH_URL = "https://api-gtm.grubhub.com/auth"

_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.grubhub.com/",
    "Origin": "https://www.grubhub.com",
}

_token_cache: tuple[str, float] = ("", 0.0)


_client_id_cache: tuple[str, float] = ("", 0.0)


async def _discover_client_id() -> str:
    """Try to discover the current Grubhub client_id from their JS bundles."""
    global _client_id_cache
    cid, expires_at = _client_id_cache
    if cid and time.time() < expires_at:
        return cid

    import asyncio

    def _fetch_client_id():
        try:
            session = cffi_requests.Session(impersonate="chrome")
            resp = session.get("https://www.grubhub.com/", timeout=10)
            html = resp.text

            # Look for JS bundles loaded by the targeting manifest
            js_urls = re.findall(
                r'(https://assets\.grubhub\.com/assets/[^\s"\']+\.js)', html
            )

            # Also try fetching the main app chunk via manifest
            manifest_match = re.search(
                r'manifest["\s:]+["\'](https://[^\s"\']+\.json)["\']', html
            )
            if manifest_match:
                try:
                    mresp = session.get(manifest_match.group(1), timeout=8)
                    mdata = mresp.json() if mresp.status_code == 200 else {}
                    for v in mdata.values():
                        if isinstance(v, str) and v.endswith(".js"):
                            js_urls.append(f"https://assets.grubhub.com/assets/{v}")
                except Exception:
                    pass

            for url in js_urls[:10]:
                try:
                    jresp = session.get(url, timeout=8)
                    if jresp.status_code == 200:
                        matches = re.findall(
                            r'client_id["\s:]+["\']([A-Za-z0-9_]+)["\']', jresp.text
                        )
                        for m in matches:
                            if len(m) > 8 and m != "undefined":
                                return m
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"[Grubhub] client_id discovery failed: {e}")
        return ""

    cid = await asyncio.to_thread(_fetch_client_id)
    if cid:
        _client_id_cache = (cid, time.time() + 7200)
    return cid


async def _get_token() -> str:
    """Get a Grubhub API token from env or anonymous auth."""
    global _token_cache
    token, expires_at = _token_cache
    if token and time.time() < expires_at:
        return token

    # Check env var first
    env_token = os.environ.get("GRUBHUB_BEARER_TOKEN", "").strip()
    if env_token:
        _token_cache = (env_token, time.time() + 3600)
        return env_token

    # Try to discover the current client_id and auth with curl_cffi
    client_id = await _discover_client_id()
    client_ids_to_try = []
    if client_id:
        client_ids_to_try.append(client_id)
    client_ids_to_try.append("beta_UmWlpsR6GHQhCpmUCk")

    import asyncio
    import uuid

    def _try_auth():
        for cid in client_ids_to_try:
            try:
                resp = cffi_requests.post(
                    GH_AUTH_URL,
                    json={
                        "brand": "GRUBHUB",
                        "client_id": cid,
                        "device_id": str(uuid.uuid4()),
                        "refresh_token": "",
                    },
                    headers={
                        **_API_HEADERS,
                        "Content-Type": "application/json",
                    },
                    impersonate="chrome",
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    tk = data.get("session_handle", {}).get("access_token", "")
                    if tk:
                        logger.info(f"[Grubhub] Got anonymous token via curl_cffi (client_id={cid[:10]}...)")
                        return tk
                else:
                    logger.debug(f"[Grubhub] Auth with client_id={cid[:10]}... returned {resp.status_code}")
            except Exception as e:
                logger.debug(f"[Grubhub] curl_cffi auth failed for {cid[:10]}...: {e}")
        return ""

    token = await asyncio.to_thread(_try_auth)

    if not token:
        # Fallback: try httpx (original approach)
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    GH_AUTH_URL,
                    json={
                        "brand": "GRUBHUB",
                        "client_id": "beta_UmWlpsR6GHQhCpmUCk",
                        "device_id": 1,
                        "refresh_token": "",
                    },
                    headers=_API_HEADERS,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    token = data.get("session_handle", {}).get("access_token", "")
        except Exception as e:
            logger.debug(f"[Grubhub] httpx anonymous auth failed: {e}")

    if token:
        _token_cache = (token, time.time() + 1800)
    return token


def _cents_to_dollars(value) -> float:
    if value is None:
        return 0.0
    try:
        v = float(value)
        if v == 0:
            return 0.0
        if abs(v) >= 100:
            return round(v / 100, 2)
        if abs(v) > 10 and v == int(v):
            return round(v / 100, 2)
        return round(v, 2)
    except (ValueError, TypeError):
        return 0.0


def _parse_restaurant(restaurant: dict) -> dict:
    """Parse a restaurant dict from the Grubhub API."""
    name = restaurant.get("name", "")
    rest_id = str(restaurant.get("restaurant_id", ""))

    fee_obj = restaurant.get("delivery_fee", {})
    if isinstance(fee_obj, dict):
        delivery_fee = _cents_to_dollars(fee_obj.get("amount", 0))
    else:
        delivery_fee = _cents_to_dollars(fee_obj)

    eta = int(restaurant.get("delivery_time_estimate", 0) or 35)
    if eta == 0:
        eta = 35

    ratings = restaurant.get("ratings", {})
    rating = None
    rating_count = None
    if isinstance(ratings, dict):
        try:
            rating = float(ratings.get("actual_rating_value", 0))
            if rating == 0:
                rating = None
        except (ValueError, TypeError):
            pass
        try:
            rating_count = int(ratings.get("rating_count", 0))
            if rating_count == 0:
                rating_count = None
        except (ValueError, TypeError):
            pass

    slug = restaurant.get("restaurant_slug", rest_id)
    url = f"https://www.grubhub.com/restaurant/{slug}" if slug else f"https://www.grubhub.com/restaurant/{rest_id}"

    min_obj = restaurant.get("minimum_order_amount", {})
    minimum_order = None
    if isinstance(min_obj, dict):
        minimum_order = _cents_to_dollars(min_obj.get("amount", 0)) or None
    elif min_obj:
        minimum_order = _cents_to_dollars(min_obj) or None

    promo = None
    deals = restaurant.get("deals", [])
    if isinstance(deals, list) and deals:
        first = deals[0] if isinstance(deals[0], dict) else {}
        promo = first.get("description") or first.get("badge_text")

    return {
        "name": name,
        "restaurant_id": rest_id,
        "delivery_fee": delivery_fee,
        "service_fee": 0.0,
        "eta": eta,
        "rating": rating,
        "rating_count": rating_count,
        "promo": promo,
        "slug": slug,
        "url": url,
        "minimum_order": minimum_order,
    }


def _parse_menu_item(item: dict) -> Optional[MenuItem]:
    name = item.get("name", "")
    if not name or len(name) < 2:
        return None

    price_obj = item.get("price", {})
    if isinstance(price_obj, dict):
        price = _cents_to_dollars(price_obj.get("amount", 0))
    else:
        price = _cents_to_dollars(price_obj)

    if price <= 0:
        return None

    description = item.get("description") or None
    if description and len(description) < 3:
        description = None

    image_url = None
    media = item.get("media_image", {})
    if isinstance(media, dict):
        image_url = media.get("base_url") or media.get("url")

    return MenuItem(
        name=name,
        description=description,
        price=round(price, 2),
        image_url=image_url,
    )


GH_WEB_SEARCH = "https://www.grubhub.com/search"


def _scrape_search_page(query: str, lat: float, lng: float) -> list[dict]:
    """Scrape restaurant data from Grubhub's search page using curl_cffi."""
    try:
        url = f"{GH_WEB_SEARCH}?orderMethod=delivery&locationMode=DELIVERY&query={quote(query)}&latitude={lat}&longitude={lng}"
        resp = cffi_requests.get(
            url,
            impersonate="chrome",
            timeout=12,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        if resp.status_code != 200:
            logger.warning(f"[Grubhub] Web scrape returned {resp.status_code}")
            return []

        html = resp.text

        # Strategy 1: Look for __NEXT_DATA__ JSON blob (Next.js SSR)
        next_data_match = re.search(
            r'<script\s+id="__NEXT_DATA__"[^>]*>\s*({.+?})\s*</script>',
            html,
            re.DOTALL,
        )
        if next_data_match:
            try:
                data = json.loads(next_data_match.group(1))
                return _extract_from_next_data(data)
            except json.JSONDecodeError:
                logger.debug("[Grubhub] __NEXT_DATA__ JSON parse failed")

        # Strategy 2: Look for JSON-LD structured data
        jsonld_matches = re.findall(
            r'<script\s+type="application/ld\+json"[^>]*>\s*({.+?})\s*</script>',
            html,
            re.DOTALL,
        )
        restaurants = []
        for match in jsonld_matches:
            try:
                ld = json.loads(match)
                if ld.get("@type") == "Restaurant" or ld.get("@type") == "FoodEstablishment":
                    restaurants.append(_parse_jsonld_restaurant(ld))
            except json.JSONDecodeError:
                continue
        if restaurants:
            return restaurants

        # Strategy 3: Extract from embedded state / window.__APOLLO_STATE__ or similar
        state_match = re.search(
            r'window\.__\w+(?:STATE|DATA|STORE)__\s*=\s*({.+?});?\s*</script>',
            html,
            re.DOTALL,
        )
        if state_match:
            try:
                state_data = json.loads(state_match.group(1))
                return _extract_from_state(state_data)
            except json.JSONDecodeError:
                pass

        # Strategy 4: Extract restaurant data from any large JSON blob in script tags
        json_blobs = re.findall(
            r'<script[^>]*>\s*({["\w].{500,}?})\s*</script>',
            html,
            re.DOTALL,
        )
        for blob in json_blobs[:5]:
            try:
                data = json.loads(blob)
                extracted = _extract_restaurants_from_json(data)
                if extracted:
                    return extracted
            except json.JSONDecodeError:
                continue

        logger.info(f"[Grubhub] Web scrape: no restaurant data found in HTML ({len(html)} bytes)")
        return []

    except Exception as e:
        logger.warning(f"[Grubhub] Web scrape failed: {e}")
        return []


def _extract_from_next_data(data: dict) -> list[dict]:
    """Extract restaurants from Next.js __NEXT_DATA__ payload."""
    results = []

    def _walk(obj, depth=0):
        if depth > 10 or len(results) >= 20:
            return
        if isinstance(obj, dict):
            # Look for restaurant-like objects
            if "restaurant_id" in obj and "name" in obj:
                results.append(obj)
            elif "restaurantId" in obj and "name" in obj:
                results.append({
                    "restaurant_id": obj.get("restaurantId"),
                    "name": obj.get("name"),
                    "delivery_fee": obj.get("deliveryFee", {}).get("amount", 0)
                    if isinstance(obj.get("deliveryFee"), dict) else obj.get("deliveryFee", 0),
                    "delivery_time_estimate": obj.get("deliveryTimeEstimate", 35),
                    "ratings": {"actual_rating_value": obj.get("rating", 0), "rating_count": obj.get("ratingCount", 0)},
                    "restaurant_slug": obj.get("slug", ""),
                })
            for v in obj.values():
                _walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, depth + 1)

    _walk(data)
    return results


def _parse_jsonld_restaurant(ld: dict) -> dict:
    """Parse a JSON-LD Restaurant object."""
    name = ld.get("name", "")
    url = ld.get("url", "")
    slug = url.rsplit("/", 1)[-1] if url else ""
    rating_obj = ld.get("aggregateRating", {})
    return {
        "name": name,
        "restaurant_id": slug or name.lower().replace(" ", "-"),
        "delivery_fee": 0,
        "delivery_time_estimate": 35,
        "ratings": {
            "actual_rating_value": float(rating_obj.get("ratingValue", 0) or 0),
            "rating_count": int(rating_obj.get("reviewCount", 0) or 0),
        },
        "restaurant_slug": slug,
    }


def _extract_from_state(state: dict) -> list[dict]:
    """Extract restaurants from Apollo/Redux state."""
    results = []
    for key, value in state.items():
        if isinstance(value, dict) and ("name" in value) and (
            "restaurant_id" in value or "restaurantId" in value or "restaurant" in key.lower()
        ):
            results.append(value)
    return results[:20]


def _extract_restaurants_from_json(data, depth=0) -> list[dict]:
    """Recursively search a JSON object for restaurant arrays."""
    if depth > 8:
        return []
    if isinstance(data, list) and len(data) >= 2:
        # Check if this looks like a restaurant array
        if all(isinstance(item, dict) and "name" in item for item in data[:3]):
            has_restaurant_keys = any(
                "restaurant_id" in item or "restaurantId" in item or "delivery_fee" in item
                for item in data[:3]
            )
            if has_restaurant_keys:
                return data[:20]
    if isinstance(data, dict):
        for v in data.values():
            result = _extract_restaurants_from_json(v, depth + 1)
            if result:
                return result
    return []


class GrubhubScraper(BaseScraper):
    PLATFORM_NAME = "grubhub"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)
        token = await _get_token()

        # Try API-based search first if we have a token
        if token:
            api_results = await self._api_search(query, lat, lng, token)
            if api_results:
                return api_results

        # Fall back to web scraping
        logger.info("[Grubhub] Trying web scraping fallback")
        return await self._web_search(query, lat, lng)

    async def _api_search(self, query: str, lat: float, lng: float, token: str) -> list[PlatformResult]:
        """Search via Grubhub API with bearer token."""
        headers = {**_API_HEADERS, "Authorization": f"Bearer {token}"}
        params = {
            "orderMethod": "delivery",
            "locationMode": "DELIVERY",
            "facetSet": "umaNew",
            "pageSize": 20,
            "hideHateos": "true",
            "queryText": query,
            "latitude": lat,
            "longitude": lng,
        }

        for search_url in [GH_SEARCH_API, GH_SEARCH_LEGACY]:
            try:
                async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                    resp = await client.get(search_url, params=params, headers=headers)

                    if resp.status_code in (401, 403):
                        logger.warning(f"[Grubhub] API {resp.status_code} - token may be expired")
                        global _token_cache
                        _token_cache = ("", 0.0)
                        break

                    resp.raise_for_status()
                    data = resp.json()

                results_data = (
                    data.get("search_result", {}).get("results", [])
                    or data.get("results", [])
                )

                if not results_data:
                    continue

                parsed = self._build_results(results_data)
                if parsed:
                    logger.info(f"[Grubhub] API: {len(parsed)} results for '{query}'")
                    return parsed

            except httpx.HTTPStatusError as e:
                logger.warning(f"[Grubhub] API {e.response.status_code}")
            except Exception as e:
                logger.warning(f"[Grubhub] API search error: {e}")

        return []

    async def _web_search(self, query: str, lat: float, lng: float) -> list[PlatformResult]:
        """Search via web scraping when API token is unavailable."""
        import asyncio
        raw = await asyncio.to_thread(_scrape_search_page, query, lat, lng)
        if not raw:
            return []

        parsed = self._build_results_from_raw(raw)
        if parsed:
            logger.info(f"[Grubhub] Web scrape: {len(parsed)} results for '{query}'")
        return parsed

    def _build_results(self, results_data: list) -> list[PlatformResult]:
        """Build PlatformResult list from API response data."""
        parsed = []
        now = datetime.now(timezone.utc).isoformat()
        for item in results_data:
            restaurant = item.get("restaurant") or item
            if not isinstance(restaurant, dict):
                continue
            rd = _parse_restaurant(restaurant)
            if rd["name"] and rd["restaurant_id"]:
                eta = rd["eta"]
                pickup_eta = max(5, int(eta * 0.5)) if eta else 15
                parsed.append(PlatformResult(
                    platform=Platform.GRUBHUB,
                    restaurant_name=rd["name"],
                    restaurant_id=rd["restaurant_id"],
                    restaurant_url=rd["url"],
                    delivery_fee=rd["delivery_fee"],
                    service_fee=rd["service_fee"],
                    estimated_delivery_minutes=eta,
                    pickup_available=True,
                    pickup_fee=0.0,
                    pickup_service_fee=0.0,
                    estimated_pickup_minutes=pickup_eta,
                    minimum_order=rd["minimum_order"],
                    rating=rd["rating"],
                    rating_count=rd["rating_count"],
                    promo_text=rd["promo"],
                    fetched_at=now,
                ))
        return parsed

    def _build_results_from_raw(self, raw_restaurants: list[dict]) -> list[PlatformResult]:
        """Build PlatformResult list from web-scraped raw dicts."""
        parsed = []
        now = datetime.now(timezone.utc).isoformat()
        for restaurant in raw_restaurants:
            if not isinstance(restaurant, dict):
                continue
            rd = _parse_restaurant(restaurant)
            if rd["name"]:
                # Generate an ID if missing
                if not rd["restaurant_id"]:
                    rd["restaurant_id"] = rd["name"].lower().replace(" ", "-")[:50]
                eta = rd["eta"]
                pickup_eta = max(5, int(eta * 0.5)) if eta else 15
                parsed.append(PlatformResult(
                    platform=Platform.GRUBHUB,
                    restaurant_name=rd["name"],
                    restaurant_id=rd["restaurant_id"],
                    restaurant_url=rd["url"],
                    delivery_fee=rd["delivery_fee"],
                    service_fee=rd["service_fee"],
                    estimated_delivery_minutes=eta,
                    pickup_available=True,
                    pickup_fee=0.0,
                    pickup_service_fee=0.0,
                    estimated_pickup_minutes=pickup_eta,
                    minimum_order=rd["minimum_order"],
                    rating=rd["rating"],
                    rating_count=rd["rating_count"],
                    promo_text=rd["promo"],
                    fetched_at=now,
                ))
        return parsed

    async def get_restaurant(self, restaurant_id: str, location: str) -> Optional[PlatformResult]:
        token = await _get_token()
        if not token:
            return None

        headers = {**_API_HEADERS, "Authorization": f"Bearer {token}"}

        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                resp = await client.get(
                    GH_RESTAURANT_API.format(restaurant_id=restaurant_id),
                    params={"orderMethod": "delivery", "version": "4"},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            restaurant = data.get("restaurant") or data
            now = datetime.now(timezone.utc).isoformat()

            menu_items = []
            for category in (restaurant.get("menu_category_list") or []):
                for item in (category.get("menu_item_list") or [])[:30]:
                    mi = _parse_menu_item(item)
                    if mi:
                        menu_items.append(mi)
                    if len(menu_items) >= 50:
                        break
                if len(menu_items) >= 50:
                    break

            rd = _parse_restaurant(restaurant)
            eta = rd["eta"]
            pickup_eta = max(5, int(eta * 0.5)) if eta else 15

            return PlatformResult(
                platform=Platform.GRUBHUB,
                restaurant_name=rd["name"] or f"Restaurant {restaurant_id}",
                restaurant_id=restaurant_id,
                restaurant_url=rd["url"],
                menu_items=menu_items,
                delivery_fee=rd["delivery_fee"],
                service_fee=rd["service_fee"],
                estimated_delivery_minutes=eta,
                pickup_available=True,
                pickup_fee=0.0,
                pickup_service_fee=0.0,
                estimated_pickup_minutes=pickup_eta,
                minimum_order=rd["minimum_order"],
                rating=rd["rating"],
                rating_count=rd["rating_count"],
                promo_text=rd["promo"],
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[Grubhub] get_restaurant failed: {e}")
            return None
