"""
gopuff scraper - April 2026.

gopuff delivers food, drinks, and essentials from their own micro-fulfillment
centers and partner restaurants. They have a web API at gopuff.com that
serves restaurant/food data.

Uses a combination of their web search page and internal API endpoints.
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

GP_BASE = "https://gopuff.com"
GP_SEARCH = "https://gopuff.com/api/search"
GP_CATALOG = "https://gopuff.com/api/catalog"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

_session_cache: tuple[dict, float] = ({}, 0.0)


async def _get_session(lat: float, lng: float) -> tuple[dict, dict]:
    """Get gopuff session cookies and location context.

    Returns (cookies_dict, location_context).
    """
    global _session_cache
    cookies, expires_at = _session_cache
    if cookies and time.time() < expires_at:
        return cookies, {}

    import asyncio

    def _fetch():
        try:
            session = cffi_requests.Session(impersonate="chrome")
            resp = session.get(GP_BASE, timeout=10)
            cook = {k: v for k, v in resp.cookies.items()}

            # Try to set location via API
            try:
                loc_resp = session.post(
                    f"{GP_BASE}/api/location",
                    json={"latitude": lat, "longitude": lng},
                    timeout=8,
                )
                if loc_resp.status_code == 200:
                    cook.update({k: v for k, v in loc_resp.cookies.items()})
            except Exception:
                pass

            return cook
        except Exception as e:
            logger.debug(f"[gopuff] Session fetch failed: {e}")
            return {}

    cookies = await asyncio.to_thread(_fetch)
    if cookies:
        _session_cache = (cookies, time.time() + 300)
    return cookies, {}


class GopuffScraper(BaseScraper):
    PLATFORM_NAME = "gopuff"

    async def search(self, query: str, location: str, mode: str = "delivery") -> list[PlatformResult]:
        lat, lng = await geocode(location)
        session_cookies, _ = await _get_session(lat, lng)
        cookie_str = "; ".join(f"{k}={v}" for k, v in session_cookies.items())

        # Strategy 1: Try API search
        results = await self._api_search(query, lat, lng, cookie_str)
        if results:
            return results

        # Strategy 2: Scrape search page
        results = await self._web_search(query, lat, lng)
        if results:
            return results

        # Strategy 3: Headless browser
        return await self._browser_search(query, lat, lng)

    async def _api_search(self, query: str, lat: float, lng: float, cookie_str: str) -> list[PlatformResult]:
        """Search via gopuff's internal API."""
        headers = {
            **_BROWSER_HEADERS,
            "Cookie": cookie_str,
            "Referer": "https://gopuff.com/",
            "Origin": "https://gopuff.com",
        }

        # gopuff API endpoint patterns
        search_urls = [
            f"{GP_BASE}/api/search?q={quote(query)}&lat={lat}&lng={lng}",
            f"{GP_BASE}/api/v2/search?query={quote(query)}&latitude={lat}&longitude={lng}",
        ]

        for url in search_urls:
            try:
                async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                results = self._parse_api_results(data)
                if results:
                    logger.info(f"[gopuff] API: {len(results)} results for '{query}'")
                    return results
            except Exception as e:
                logger.debug(f"[gopuff] API search error: {e}")
                continue

        return []

    async def _web_search(self, query: str, lat: float, lng: float) -> list[PlatformResult]:
        """Scrape gopuff's web search page."""
        import asyncio

        def _scrape():
            try:
                url = f"https://gopuff.com/search?q={quote(query)}"
                session = cffi_requests.Session(impersonate="chrome")

                # Set location first
                try:
                    session.post(
                        f"{GP_BASE}/api/location",
                        json={"latitude": lat, "longitude": lng},
                        timeout=8,
                    )
                except Exception:
                    pass

                resp = session.get(url, timeout=12)
                if resp.status_code != 200:
                    return []

                html = resp.text

                # Look for __NEXT_DATA__ or embedded state
                next_data = re.search(
                    r'<script\s+id="__NEXT_DATA__"[^>]*>\s*({.+?})\s*</script>',
                    html, re.DOTALL,
                )
                if next_data:
                    try:
                        data = json.loads(next_data.group(1))
                        return _extract_products(data)
                    except json.JSONDecodeError:
                        pass

                # Try embedded JSON state
                state = re.search(
                    r'window\.__\w+(?:STATE|DATA|STORE)__\s*=\s*({.+?});?\s*</script>',
                    html, re.DOTALL,
                )
                if state:
                    try:
                        data = json.loads(state.group(1))
                        return _extract_products(data)
                    except json.JSONDecodeError:
                        pass

                return []
            except Exception as e:
                logger.debug(f"[gopuff] Web scrape failed: {e}")
                return []

        raw = await asyncio.to_thread(_scrape)
        if not raw:
            return []

        return self._build_from_products(raw)

    async def _browser_search(self, query: str, lat: float, lng: float) -> list[PlatformResult]:
        """Fallback: headless browser."""
        try:
            from app.services.browser import browser_fetch
            url = f"https://gopuff.com/search?q={quote(query)}"
            html = await browser_fetch(url, wait_time=5000)
            if html:
                next_data = re.search(
                    r'<script\s+id="__NEXT_DATA__"[^>]*>\s*({.+?})\s*</script>',
                    html, re.DOTALL,
                )
                if next_data:
                    data = json.loads(next_data.group(1))
                    products = _extract_products(data)
                    if products:
                        return self._build_from_products(products)
        except Exception as e:
            logger.debug(f"[gopuff] Browser fallback failed: {e}")
        return []

    def _parse_api_results(self, data: dict) -> list[PlatformResult]:
        """Parse gopuff API response."""
        results = []
        now = datetime.now(timezone.utc).isoformat()

        # gopuff API returns products/items, sometimes grouped by store
        items = (
            data.get("products") or data.get("items") or
            data.get("results") or data.get("data", {}).get("products") or []
        )

        # Group items by store/restaurant
        stores: dict[str, dict] = {}
        for item in items:
            if not isinstance(item, dict):
                continue

            # gopuff items belong to a store/location
            store_name = (
                item.get("store_name") or item.get("brand") or
                item.get("merchant_name") or item.get("restaurant_name") or
                "gopuff"
            )
            store_id = str(
                item.get("store_id") or item.get("merchant_id") or
                item.get("location_id") or store_name.lower().replace(" ", "-")
            )

            if store_id not in stores:
                stores[store_id] = {
                    "name": store_name,
                    "id": store_id,
                    "items": [],
                    "delivery_fee": 0.0,
                    "eta": 30,
                }

            # Extract item price
            price = 0.0
            for price_key in ["price", "sale_price", "unit_price"]:
                pval = item.get(price_key)
                if pval:
                    try:
                        p = float(pval)
                        if p >= 100:
                            p = p / 100
                        price = round(p, 2)
                        break
                    except (ValueError, TypeError):
                        pass

            if price > 0:
                stores[store_id]["items"].append(MenuItem(
                    name=item.get("name") or item.get("title") or "",
                    description=item.get("description"),
                    price=price,
                    image_url=item.get("image_url") or item.get("thumbnail"),
                ))

            # Capture delivery info if present
            if item.get("delivery_fee") is not None:
                try:
                    fee = float(item["delivery_fee"])
                    stores[store_id]["delivery_fee"] = round(fee / 100, 2) if fee >= 100 else round(fee, 2)
                except (ValueError, TypeError):
                    pass

            if item.get("delivery_eta") or item.get("eta_minutes"):
                try:
                    stores[store_id]["eta"] = int(item.get("delivery_eta") or item.get("eta_minutes"))
                except (ValueError, TypeError):
                    pass

        for store_id, store in stores.items():
            if not store["items"]:
                continue

            eta = store["eta"]
            results.append(PlatformResult(
                platform=Platform.GOPUFF,
                restaurant_name=store["name"],
                restaurant_id=store["id"],
                restaurant_url=f"https://gopuff.com/store/{store['id']}",
                menu_items=store["items"][:50],
                delivery_fee=store["delivery_fee"],
                service_fee=0.0,
                estimated_delivery_minutes=eta,
                pickup_available=False,
                pickup_fee=0.0,
                pickup_service_fee=0.0,
                estimated_pickup_minutes=None,
                fetched_at=now,
            ))

        return results

    def _build_from_products(self, products: list[dict]) -> list[PlatformResult]:
        """Build results from extracted product data."""
        now = datetime.now(timezone.utc).isoformat()
        stores: dict[str, dict] = {}

        for product in products:
            if not isinstance(product, dict):
                continue

            store_name = product.get("store_name") or product.get("brand") or "gopuff"
            store_id = str(product.get("store_id") or store_name.lower().replace(" ", "-"))

            if store_id not in stores:
                stores[store_id] = {"name": store_name, "id": store_id, "items": []}

            price = 0.0
            for key in ["price", "sale_price", "unit_price"]:
                if product.get(key):
                    try:
                        p = float(product[key])
                        price = round(p / 100, 2) if p >= 100 else round(p, 2)
                        break
                    except (ValueError, TypeError):
                        pass

            if price > 0:
                stores[store_id]["items"].append(MenuItem(
                    name=product.get("name") or product.get("title") or "",
                    description=product.get("description"),
                    price=price,
                    image_url=product.get("image_url") or product.get("thumbnail"),
                ))

        results = []
        for store_id, store in stores.items():
            if not store["items"]:
                continue
            results.append(PlatformResult(
                platform=Platform.GOPUFF,
                restaurant_name=store["name"],
                restaurant_id=store["id"],
                restaurant_url=f"https://gopuff.com/store/{store_id}",
                menu_items=store["items"][:50],
                delivery_fee=3.95,  # gopuff standard delivery fee
                service_fee=0.0,
                estimated_delivery_minutes=30,
                pickup_available=False,
                fetched_at=now,
            ))

        return results

    async def get_restaurant(self, restaurant_id: str, location: str, mode: str = "delivery") -> Optional[PlatformResult]:
        """Get store details from gopuff."""
        lat, lng = await geocode(location)
        session_cookies, _ = await _get_session(lat, lng)
        cookie_str = "; ".join(f"{k}={v}" for k, v in session_cookies.items())

        headers = {
            **_BROWSER_HEADERS,
            "Cookie": cookie_str,
            "Referer": "https://gopuff.com/",
        }

        # Try API endpoint for store details
        store_urls = [
            f"{GP_BASE}/api/store/{restaurant_id}",
            f"{GP_BASE}/api/v2/store/{restaurant_id}",
            f"{GP_BASE}/api/catalog/{restaurant_id}",
        ]

        for url in store_urls:
            try:
                async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                store = data.get("store") or data.get("data") or data
                now = datetime.now(timezone.utc).isoformat()

                menu_items = []
                for item in (store.get("products") or store.get("items") or [])[:50]:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or item.get("title") or ""
                    if not name:
                        continue

                    price = 0.0
                    for key in ["price", "sale_price"]:
                        if item.get(key):
                            try:
                                p = float(item[key])
                                price = round(p / 100, 2) if p >= 100 else round(p, 2)
                                break
                            except (ValueError, TypeError):
                                pass

                    if price > 0:
                        menu_items.append(MenuItem(
                            name=name,
                            description=item.get("description"),
                            price=price,
                            image_url=item.get("image_url"),
                        ))

                return PlatformResult(
                    platform=Platform.GOPUFF,
                    restaurant_name=store.get("name") or f"gopuff Store {restaurant_id}",
                    restaurant_id=restaurant_id,
                    restaurant_url=f"https://gopuff.com/store/{restaurant_id}",
                    menu_items=menu_items,
                    delivery_fee=3.95,
                    service_fee=0.0,
                    estimated_delivery_minutes=30,
                    pickup_available=False,
                    fetched_at=now,
                )
            except Exception as e:
                logger.debug(f"[gopuff] Store detail failed: {e}")
                continue

        return None


def _extract_products(data: dict, depth: int = 0) -> list[dict]:
    """Recursively extract product items from nested JSON."""
    if depth > 8:
        return []
    results = []

    if isinstance(data, dict):
        # Check if this looks like a product
        if ("name" in data or "title" in data) and ("price" in data or "sale_price" in data):
            results.append(data)
        for v in data.values():
            results.extend(_extract_products(v, depth + 1))
            if len(results) >= 50:
                break
    elif isinstance(data, list):
        for item in data:
            results.extend(_extract_products(item, depth + 1))
            if len(results) >= 50:
                break

    return results[:50]
