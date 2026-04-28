"""
EatStreet scraper - April 2026.

EatStreet is an independent food delivery platform with coverage in 250+ US cities.
They have a public-facing API and web interface at eatstreet.com.

Uses their web search API and page scraping as fallback.
"""

import json
import logging
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

ES_BASE = "https://eatstreet.com"
ES_API = "https://eatstreet.com/publicapi/v1"
ES_SEARCH_API = f"{ES_API}/restaurant/search"
ES_RESTAURANT_API = f"{ES_API}/restaurant"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://eatstreet.com/",
    "Origin": "https://eatstreet.com",
}

# EatStreet has a public API key that's embedded in their frontend
_api_key_cache: tuple[str, float] = ("", 0.0)


async def _get_api_key() -> str:
    """Discover EatStreet's public API key from their frontend JS."""
    global _api_key_cache
    key, expires_at = _api_key_cache
    if key and time.time() < expires_at:
        return key

    import asyncio

    def _discover():
        try:
            session = cffi_requests.Session(impersonate="chrome")
            resp = session.get(ES_BASE, timeout=10)
            html = resp.text

            # Look for API key in inline scripts
            key_patterns = [
                r'api[_-]?key["\s:]+["\']([\w-]+)["\']',
                r'apiKey["\s:]+["\']([\w-]+)["\']',
                r'X-Access-Token["\s:]+["\']([\w-]+)["\']',
                r'accessToken["\s:]+["\']([\w-]+)["\']',
            ]
            for pattern in key_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for m in matches:
                    if len(m) > 8 and m != "undefined":
                        return m

            # Check JS bundles
            js_urls = re.findall(r'(?:src|href)="([^"]*\.js(?:\?[^"]*)?)"', html)
            for js_url in js_urls[:8]:
                if js_url.startswith("/"):
                    js_url = f"{ES_BASE}{js_url}"
                elif not js_url.startswith("http"):
                    continue
                try:
                    jresp = session.get(js_url, timeout=8)
                    if jresp.status_code == 200:
                        for pattern in key_patterns:
                            matches = re.findall(pattern, jresp.text, re.IGNORECASE)
                            for m in matches:
                                if len(m) > 8 and m != "undefined":
                                    return m
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"[EatStreet] API key discovery failed: {e}")
        return ""

    key = await asyncio.to_thread(_discover)
    if key:
        _api_key_cache = (key, time.time() + 7200)
    return key


def _parse_fee(value) -> float:
    if value is None:
        return 0.0
    try:
        v = float(value)
        if v >= 100:
            return round(v / 100, 2)
        return round(v, 2)
    except (ValueError, TypeError):
        return 0.0


class EatStreetScraper(BaseScraper):
    PLATFORM_NAME = "eatstreet"

    async def search(self, query: str, location: str, mode: str = "delivery") -> list[PlatformResult]:
        lat, lng = await geocode(location)

        # Try API and direct search in parallel (fast strategies)
        import asyncio
        api_key = await _get_api_key()

        fast_tasks = []
        if api_key:
            fast_tasks.append(self._api_search(query, lat, lng, api_key))
        fast_tasks.append(self._direct_search(query, lat, lng))

        for coro in asyncio.as_completed([asyncio.wait_for(t, timeout=8.0) for t in fast_tasks]):
            try:
                results = await coro
                if results:
                    return results
            except (asyncio.TimeoutError, Exception):
                continue

        # Fallback: web scraping (slower)
        results = await self._web_search(query, lat, lng)
        if results:
            return results

        return []

    async def _api_search(self, query: str, lat: float, lng: float, api_key: str) -> list[PlatformResult]:
        """Search via EatStreet's public API."""
        headers = {
            **_BROWSER_HEADERS,
            "X-Access-Token": api_key,
        }

        params = {
            "latitude": lat,
            "longitude": lng,
            "search": query,
            "method": "delivery",
        }

        try:
            async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(ES_SEARCH_API, params=params)
                if resp.status_code != 200:
                    return []
                data = resp.json()

            restaurants = data.get("restaurants") or data if isinstance(data, list) else []
            if isinstance(data, dict) and not restaurants:
                restaurants = data.get("data", {}).get("restaurants", [])

            return self._build_results(restaurants)

        except Exception as e:
            logger.debug(f"[EatStreet] API search error: {e}")
            return []

    async def _direct_search(self, query: str, lat: float, lng: float) -> list[PlatformResult]:
        """Search using EatStreet's internal web API endpoints."""
        headers = {**_BROWSER_HEADERS}

        # Try various internal API patterns
        search_urls = [
            f"{ES_BASE}/api/v2/restaurants?latitude={lat}&longitude={lng}&search={quote(query)}",
            f"{ES_BASE}/api/restaurants/search?lat={lat}&lng={lng}&q={quote(query)}",
        ]

        for url in search_urls:
            try:
                async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                restaurants = []
                if isinstance(data, list):
                    restaurants = data
                elif isinstance(data, dict):
                    restaurants = data.get("restaurants") or data.get("data") or data.get("results") or []

                if restaurants:
                    results = self._build_results(restaurants)
                    if results:
                        logger.info(f"[EatStreet] Direct API: {len(results)} results")
                        return results
            except Exception:
                continue

        return []

    async def _web_search(self, query: str, lat: float, lng: float) -> list[PlatformResult]:
        """Scrape EatStreet's search page."""
        import asyncio

        def _scrape():
            try:
                url = f"{ES_BASE}/search?q={quote(query)}&lat={lat}&lng={lng}&method=delivery"
                resp = cffi_requests.get(
                    url,
                    impersonate="chrome",
                    timeout=12,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,*/*",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                if resp.status_code != 200:
                    return []

                html = resp.text

                # __NEXT_DATA__
                next_data = re.search(
                    r'<script\s+id="__NEXT_DATA__"[^>]*>\s*({.+?})\s*</script>',
                    html, re.DOTALL,
                )
                if next_data:
                    try:
                        data = json.loads(next_data.group(1))
                        return _extract_restaurants(data)
                    except json.JSONDecodeError:
                        pass

                # Embedded state
                state = re.search(
                    r'window\.__\w+(?:STATE|DATA|STORE|INITIAL)__\s*=\s*({.+?});?\s*</script>',
                    html, re.DOTALL,
                )
                if state:
                    try:
                        data = json.loads(state.group(1))
                        return _extract_restaurants(data)
                    except json.JSONDecodeError:
                        pass

                # JSON-LD
                jsonld = re.findall(
                    r'<script\s+type="application/ld\+json"[^>]*>\s*({.+?})\s*</script>',
                    html, re.DOTALL,
                )
                results = []
                for match in jsonld:
                    try:
                        ld = json.loads(match)
                        if ld.get("@type") in ("Restaurant", "FoodEstablishment"):
                            results.append({
                                "name": ld.get("name", ""),
                                "apiKey": ld.get("url", "").rsplit("/", 1)[-1],
                                "deliveryPrice": 0,
                                "deliveryMin": 35,
                            })
                    except json.JSONDecodeError:
                        continue
                return results

            except Exception as e:
                logger.debug(f"[EatStreet] Web scrape failed: {e}")
                return []

        raw = await asyncio.to_thread(_scrape)
        if not raw:
            return []
        return self._build_results(raw)

    async def _browser_search(self, query: str, lat: float, lng: float) -> list[PlatformResult]:
        """Fallback: headless browser."""
        try:
            from app.services.browser import browser_fetch
            url = f"https://eatstreet.com/search?q={quote(query)}&lat={lat}&lng={lng}"
            html = await browser_fetch(url, wait_time=5000)
            if html:
                next_data = re.search(
                    r'<script\s+id="__NEXT_DATA__"[^>]*>\s*({.+?})\s*</script>',
                    html, re.DOTALL,
                )
                if next_data:
                    data = json.loads(next_data.group(1))
                    raw = _extract_restaurants(data)
                    if raw:
                        return self._build_results(raw)
        except Exception as e:
            logger.debug(f"[EatStreet] Browser fallback failed: {e}")
        return []

    def _build_results(self, restaurants: list) -> list[PlatformResult]:
        results = []
        now = datetime.now(timezone.utc).isoformat()

        for rest in restaurants:
            if not isinstance(rest, dict):
                continue

            name = rest.get("name") or rest.get("restaurantName") or ""
            if not name:
                continue

            rest_id = str(
                rest.get("apiKey") or rest.get("restaurantId") or
                rest.get("id") or rest.get("slug") or
                name.lower().replace(" ", "-")[:50]
            )

            delivery_fee = _parse_fee(
                rest.get("deliveryPrice") or rest.get("delivery_fee") or
                rest.get("deliveryFee") or 0
            )

            eta = 35
            for eta_key in ["deliveryMin", "delivery_min", "deliveryEta", "estimatedDeliveryTime"]:
                if rest.get(eta_key):
                    try:
                        eta = int(rest[eta_key])
                        break
                    except (ValueError, TypeError):
                        pass

            rating = None
            for rating_key in ["starRating", "rating", "averageRating"]:
                if rest.get(rating_key):
                    try:
                        rating = round(float(rest[rating_key]), 1)
                        break
                    except (ValueError, TypeError):
                        pass

            rating_count = None
            for count_key in ["ratingCount", "reviewCount", "numRatings"]:
                if rest.get(count_key):
                    try:
                        rating_count = int(rest[count_key])
                        break
                    except (ValueError, TypeError):
                        pass

            min_order = None
            for min_key in ["minimumOrder", "minimum_order", "minOrderAmount"]:
                if rest.get(min_key):
                    min_order = _parse_fee(rest[min_key]) or None
                    break

            slug = rest.get("slug") or rest.get("apiKey") or rest_id
            url = rest.get("url") or f"https://eatstreet.com/restaurant/{slug}"
            if not url.startswith("http"):
                url = f"https://eatstreet.com{url}" if url.startswith("/") else f"https://eatstreet.com/restaurant/{url}"

            promo = rest.get("promoText") or rest.get("deal") or None

            pickup_eta = max(5, int(eta * 0.5)) if eta else 15
            results.append(PlatformResult(
                platform=Platform.EATSTREET,
                restaurant_name=name,
                restaurant_id=rest_id,
                restaurant_url=url,
                delivery_fee=delivery_fee,
                service_fee=0.0,
                estimated_delivery_minutes=eta,
                pickup_available=True,
                pickup_fee=0.0,
                pickup_service_fee=0.0,
                estimated_pickup_minutes=pickup_eta,
                minimum_order=min_order,
                rating=rating,
                rating_count=rating_count,
                promo_text=promo,
                fetched_at=now,
            ))

        logger.info(f"[EatStreet] {len(results)} results")
        return results

    async def get_restaurant(self, restaurant_id: str, location: str, mode: str = "delivery") -> Optional[PlatformResult]:
        """Get full restaurant details with menu."""
        api_key = await _get_api_key()

        # Try public API first
        if api_key:
            result = await self._api_restaurant(restaurant_id, api_key)
            if result:
                return result

        # Fallback: scrape restaurant page
        return await self._web_restaurant(restaurant_id)

    async def _api_restaurant(self, restaurant_id: str, api_key: str) -> Optional[PlatformResult]:
        headers = {**_BROWSER_HEADERS, "X-Access-Token": api_key}

        try:
            async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
                # Get restaurant info
                resp = await client.get(f"{ES_RESTAURANT_API}/{restaurant_id}")
                if resp.status_code != 200:
                    return None
                data = resp.json()

                # Get menu
                menu_resp = await client.get(f"{ES_RESTAURANT_API}/{restaurant_id}/menu")
                menu_data = menu_resp.json() if menu_resp.status_code == 200 else []

            now = datetime.now(timezone.utc).isoformat()

            menu_items = []
            menu_list = menu_data if isinstance(menu_data, list) else menu_data.get("items", [])
            for category in menu_list:
                items = category.get("items", []) if isinstance(category, dict) else []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or ""
                    if not name:
                        continue
                    price = _parse_fee(item.get("basePrice") or item.get("price") or 0)
                    if price <= 0:
                        continue
                    menu_items.append(MenuItem(
                        name=name,
                        description=item.get("description"),
                        price=price,
                        image_url=item.get("imageUrl"),
                    ))
                    if len(menu_items) >= 50:
                        break
                if len(menu_items) >= 50:
                    break

            delivery_fee = _parse_fee(data.get("deliveryPrice") or data.get("deliveryFee") or 0)
            eta = int(data.get("deliveryMin") or data.get("deliveryEta") or 35)
            pickup_eta = max(5, int(eta * 0.5))

            rating = None
            if data.get("starRating"):
                try:
                    rating = round(float(data["starRating"]), 1)
                except (ValueError, TypeError):
                    pass

            slug = data.get("slug") or data.get("apiKey") or restaurant_id

            return PlatformResult(
                platform=Platform.EATSTREET,
                restaurant_name=data.get("name") or f"Restaurant {restaurant_id}",
                restaurant_id=restaurant_id,
                restaurant_url=f"https://eatstreet.com/restaurant/{slug}",
                menu_items=menu_items,
                delivery_fee=delivery_fee,
                service_fee=0.0,
                estimated_delivery_minutes=eta,
                pickup_available=True,
                pickup_fee=0.0,
                pickup_service_fee=0.0,
                estimated_pickup_minutes=pickup_eta,
                rating=rating,
                rating_count=int(data.get("ratingCount") or 0) or None,
                minimum_order=_parse_fee(data.get("minimumOrder") or 0) or None,
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[EatStreet] API restaurant failed: {e}")
            return None

    async def _web_restaurant(self, restaurant_id: str) -> Optional[PlatformResult]:
        """Scrape restaurant page for menu data."""
        import asyncio

        def _scrape():
            try:
                url = f"https://eatstreet.com/restaurant/{restaurant_id}"
                resp = cffi_requests.get(url, impersonate="chrome", timeout=12)
                if resp.status_code != 200:
                    return None
                return resp.text
            except Exception:
                return None

        html = await asyncio.to_thread(_scrape)
        if not html:
            return None

        now = datetime.now(timezone.utc).isoformat()

        # Extract restaurant name from title
        title_m = re.search(r"<title>([^<]+)</title>", html)
        name = title_m.group(1).split("|")[0].split("-")[0].strip() if title_m else restaurant_id

        # Extract menu from __NEXT_DATA__ or embedded state
        menu_items = []
        next_data = re.search(
            r'<script\s+id="__NEXT_DATA__"[^>]*>\s*({.+?})\s*</script>',
            html, re.DOTALL,
        )
        if next_data:
            try:
                data = json.loads(next_data.group(1))
                menu_items = _extract_menu_from_data(data)
            except json.JSONDecodeError:
                pass

        return PlatformResult(
            platform=Platform.EATSTREET,
            restaurant_name=name,
            restaurant_id=restaurant_id,
            restaurant_url=f"https://eatstreet.com/restaurant/{restaurant_id}",
            menu_items=menu_items[:50],
            delivery_fee=0.0,
            service_fee=0.0,
            estimated_delivery_minutes=35,
            pickup_available=True,
            pickup_fee=0.0,
            pickup_service_fee=0.0,
            estimated_pickup_minutes=15,
            fetched_at=now,
        )


def _extract_restaurants(data: dict, depth: int = 0) -> list[dict]:
    """Recursively find restaurant objects in nested JSON."""
    if depth > 10:
        return []
    results = []
    if isinstance(data, dict):
        if "name" in data and any(k in data for k in ["apiKey", "restaurantId", "deliveryPrice", "deliveryFee"]):
            results.append(data)
        for v in data.values():
            results.extend(_extract_restaurants(v, depth + 1))
            if len(results) >= 20:
                break
    elif isinstance(data, list):
        for item in data:
            results.extend(_extract_restaurants(item, depth + 1))
            if len(results) >= 20:
                break
    return results[:20]


def _extract_menu_from_data(data: dict, depth: int = 0) -> list[MenuItem]:
    """Extract menu items from nested JSON data."""
    if depth > 8:
        return []
    items = []

    if isinstance(data, dict):
        if ("name" in data) and ("price" in data or "basePrice" in data):
            name = data.get("name", "")
            price = _parse_fee(data.get("basePrice") or data.get("price") or 0)
            if name and price > 0:
                items.append(MenuItem(
                    name=name,
                    description=data.get("description"),
                    price=price,
                    image_url=data.get("imageUrl"),
                ))
        for v in data.values():
            items.extend(_extract_menu_from_data(v, depth + 1))
            if len(items) >= 50:
                break
    elif isinstance(data, list):
        for item in data:
            items.extend(_extract_menu_from_data(item, depth + 1))
            if len(items) >= 50:
                break

    return items[:50]
