"""
Caviar scraper - April 2026.

Caviar (trycaviar.com) is DoorDash's premium restaurant brand. It features
curated, upscale restaurants that may not appear on the main DoorDash app,
often with different pricing and exclusive deals.

Uses DoorDash's backend but accessed through the Caviar domain/surface.
"""

import base64
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from curl_cffi import requests as cffi_requests

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.pricing import build_fee_schedule
from app.services.scraper_base import BaseScraper, geocode

# Caviar is DoorDash's premium surface and streams the exact same 2026 RSC
# shapes (MenuPageItemList menu blocks, T-row search records,
# DeliveryFeeLayout header). Reuse DoorDash's brace-matched parsers rather
# than fork a second copy that would drift.
from app.services.doordash import (
    _extract_menu_items_from_text as _dd_extract_menu_items_from_text,
    _extract_store_header_fees as _dd_extract_store_header_fees,
    _stores_from_search_records as _dd_stores_from_search_records,
)

logger = logging.getLogger(__name__)

CAVIAR_SEARCH_URL = "https://www.trycaviar.com/search/store/{query}/"
CAVIAR_STORE_URL = "https://www.trycaviar.com/store/{store_id}/"


def _build_location_cookie(lat: float, lng: float, address: str = "") -> str:
    payload = {
        "lat": lat,
        "lng": lng,
        "shouldShowAddressModal": False,
        "unit": "",
    }
    if address:
        payload["address"] = address
    raw = json.dumps(payload, separators=(",", ":"))
    return base64.b64encode(raw.encode()).decode()


def _cffi_get(url: str, cookies: str = "", timeout: int = 15, retries: int = 2) -> Optional[str]:
    """Fetch a URL using curl_cffi with Chrome impersonation."""
    browsers = ["chrome", "chrome110", "chrome120"]
    attempts = min(retries + 1, len(browsers))

    for attempt in range(attempts):
        browser = browsers[attempt % len(browsers)]
        try:
            headers = {
                "Referer": "https://www.trycaviar.com/",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            if cookies:
                headers["Cookie"] = cookies
            resp = cffi_requests.get(
                url,
                impersonate=browser,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            )
            if resp.status_code != 200:
                logger.warning(f"[Caviar] curl_cffi ({browser}) returned {resp.status_code}")
                continue
            html = resp.text

            if "waitingroom" in html.lower() or (
                "challenge" in html.lower() and len(html) < 50000
            ):
                logger.warning(f"[Caviar] Cloudflare challenge ({browser}), attempt {attempt + 1}")
                if attempt < attempts - 1:
                    import time as _time
                    _time.sleep(1)
                continue

            logger.info(f"[Caviar] curl_cffi ({browser}) got {len(html)} bytes")
            return html
        except Exception as e:
            logger.warning(f"[Caviar] curl_cffi ({browser}) failed: {e}")
            continue

    return None


def _extract_rsc_text(html: str) -> str:
    combined = []
    pattern = re.compile(
        r'self\.__next_f\.push\(\s*\[1\s*,\s*("(?:[^"\\]|\\.)*")\s*\]\s*\)',
        re.DOTALL,
    )
    for m in pattern.finditer(html):
        try:
            chunk = json.loads(m.group(1))
            combined.append(chunk)
        except (json.JSONDecodeError, ValueError):
            pass
    return "".join(combined)


def _extract_stores(html: str) -> list[dict]:
    """Extract store records from Caviar's RSC payload."""
    full_text = _extract_rsc_text(html)
    if not full_text:
        return []

    # 2026 payload: complete store records stream as RSC text rows; parse
    # them brace-matched (same shape as DoorDash). The regex-window path
    # below only remains for older payloads.
    stores = _dd_stores_from_search_records(full_text)
    if stores:
        logger.info(f"[Caviar] {len(stores)} stores via 2026 search records")
        for store in stores:
            # Caviar's legacy store dicts use "eta" for the display time.
            store["eta"] = store.get("store_display_asap_time")
        return stores

    stores = []
    seen_ids: set = set()

    # Caviar uses same DoorDash RSC format
    for m in re.finditer(r'"store_id":"(\d+)"', full_text):
        store_id = m.group(1)
        if store_id in seen_ids:
            continue

        obj_start = full_text.rfind("{", max(0, m.start() - 800), m.start())
        if obj_start == -1:
            obj_start = max(0, m.start() - 500)

        next_store = re.search(r'"store_id":"', full_text[m.end():])
        obj_end = min(m.end() + (next_store.start() if next_store else 2000), m.end() + 2000)
        window = full_text[obj_start:obj_end]

        def _field(field: str) -> Optional[str]:
            fm = re.search(rf'"{re.escape(field)}":"([^"]*)"', window)
            return fm.group(1) if fm else None

        def _num_field(field: str) -> Optional[float]:
            fm = re.search(rf'"{re.escape(field)}":([\d.]+)', window)
            try:
                return float(fm.group(1)) if fm else None
            except (ValueError, TypeError):
                return None

        def _money_field(field: str) -> float:
            fm = re.search(rf'"{re.escape(field)}":\s*\{{\s*"unit_amount":\s*(\d+)', window)
            if fm:
                try:
                    return round(int(fm.group(1)) / 100, 2)
                except (ValueError, TypeError):
                    pass
            fm = re.search(rf'"{re.escape(field)}":\s*\{{[^}}]*"display_string":"(\$?[\d.]+)"', window)
            if fm:
                try:
                    return round(float(fm.group(1).replace("$", "")), 2)
                except (ValueError, TypeError):
                    pass
            fm = re.search(rf'"{re.escape(field)}":(\d+)', window)
            if fm:
                val = int(fm.group(1))
                return round(val / 100, 2) if val > 100 else round(val / 1, 2)
            fm = re.search(rf'"{re.escape(field)}":"\$?([\d.]+)"', window)
            if fm:
                try:
                    return round(float(fm.group(1)), 2)
                except (ValueError, TypeError):
                    pass
            return 0.0

        name = _field("store_name")
        if not name:
            continue

        seen_ids.add(store_id)

        delivery_fee = 0.0
        for fee_field in ["delivery_fee", "deliveryFee"]:
            val = _money_field(fee_field)
            if val > 0:
                delivery_fee = val
                break

        if delivery_fee == 0.0:
            fee_text = re.search(r'\$(\d+\.?\d*)\s*delivery\s*fee', window, re.IGNORECASE)
            if fee_text:
                try:
                    delivery_fee = round(float(fee_text.group(1)), 2)
                except ValueError:
                    pass

        service_fee = 0.0
        for fee_field in ["service_fee", "serviceFee"]:
            val = _money_field(fee_field)
            if val > 0:
                service_fee = val
                break

        promo = None
        free_delivery = re.search(r'(\$0(?:\.00)?\s+delivery\s+fee[^"]*)', window, re.IGNORECASE)
        if free_delivery:
            promo = free_delivery.group(1).strip()
            delivery_fee = 0.0

        stores.append({
            "store_id": store_id,
            "store_name": name,
            "star_rating": _field("star_rating"),
            "num_ratings": int(_num_field("num_ratings")) if _num_field("num_ratings") else None,
            "eta": _field("store_display_asap_time"),
            "delivery_fee": delivery_fee,
            "service_fee": service_fee,
            "promo_text": promo,
        })

    # Fallback: try StoreCard patterns
    if not stores:
        for m in re.findall(
            r'"__typename":"(?:Store|StoreSearchResult)"[^}]*?"id":"(\d+)"[^}]*?"name":"([^"]+)"',
            full_text,
        ):
            store_id, store_name = m
            if store_id not in seen_ids:
                seen_ids.add(store_id)
                stores.append({
                    "store_id": store_id,
                    "store_name": store_name,
                    "star_rating": None,
                    "num_ratings": None,
                    "eta": None,
                    "delivery_fee": 0.0,
                    "service_fee": 0.0,
                    "promo_text": None,
                })

    return stores


def _extract_menu_items(html: str) -> list[MenuItem]:
    """Extract menu items from a Caviar store page.

    Caviar streams the identical 2026 RSC shape as DoorDash, so this returns
    the full menu (all MenuPageItemList sections, item ids, cents prices) via
    the shared parser, which itself falls back to the legacy carousel /
    item_id shapes when the new blocks are absent.
    """
    full_text = _extract_rsc_text(html)
    if not full_text:
        return []
    return _dd_extract_menu_items_from_text(full_text)


def _parse_eta(eta_str: Optional[str]) -> int:
    if not eta_str:
        return 30
    m = re.search(r"(\d+)", eta_str)
    return int(m.group(1)) if m else 30


class CaviarScraper(BaseScraper):
    PLATFORM_NAME = "caviar"

    async def search(self, query: str, location: str, mode: str = "delivery") -> list[PlatformResult]:
        lat, lng = await geocode(location)
        url = CAVIAR_SEARCH_URL.format(query=quote(query, safe=""))
        loc_cookie = _build_location_cookie(lat, lng, location)
        cookie_header = f"dd_delivery_address={loc_cookie}"

        try:
            import asyncio
            html = await asyncio.to_thread(_cffi_get, url, cookie_header)

            if not html:
                # Fallback to headless browser
                return await self._browser_search(query, lat, lng, location)

            stores = _extract_stores(html)
            if not stores:
                return await self._browser_search(query, lat, lng, location)

            # Caviar shares DoorDash's backend and has the same IP-geo issue.
            full_text = _extract_rsc_text(html)
            response_lats = re.findall(r'"store_latitude":(\-?[0-9.]+)', full_text)
            response_lngs = re.findall(r'"store_longitude":(\-?[0-9.]+)', full_text)
            if response_lats and response_lngs:
                try:
                    sample_lat = sorted(float(x) for x in response_lats[:20])[len(response_lats[:20]) // 2]
                    sample_lng = sorted(float(x) for x in response_lngs[:20])[len(response_lngs[:20]) // 2]
                    if abs(sample_lat - lat) > 1.5 or abs(sample_lng - lng) > 1.5:
                        logger.warning(
                            f"[Caviar] IP-geo mismatch: asked for ({lat:.2f},{lng:.2f}) "
                            f"but results are near ({sample_lat:.2f},{sample_lng:.2f}). Dropping."
                        )
                        return []
                except (ValueError, TypeError):
                    pass

            results = self._build_results(stores)
            logger.info(f"[Caviar] {len(results)} results for '{query}'")
            return results

        except Exception as e:
            logger.warning(f"[Caviar] Search failed: {e}")
            return []

    async def _browser_search(self, query: str, lat: float, lng: float, location: str) -> list[PlatformResult]:
        """Fallback: use headless browser."""
        try:
            from app.services.browser import browser_fetch
            url = CAVIAR_SEARCH_URL.format(query=quote(query, safe=""))
            loc_cookie = _build_location_cookie(lat, lng, location)
            cookies = [
                {"name": "dd_delivery_address", "value": loc_cookie,
                 "domain": ".trycaviar.com", "path": "/"},
            ]
            html = await browser_fetch(url, cookies=cookies, wait_time=4000)
            if html:
                stores = _extract_stores(html)
                if stores:
                    return self._build_results(stores)
        except Exception as e:
            logger.warning(f"[Caviar] Browser fallback failed: {e}")
        return []

    def _build_results(self, stores: list[dict]) -> list[PlatformResult]:
        results = []
        now = datetime.now(timezone.utc).isoformat()

        for store in stores:
            try:
                store_id = store.get("store_id") or ""
                name = store.get("store_name") or ""
                if not store_id or not name:
                    continue

                rating = None
                try:
                    rating = float(store["star_rating"]) if store.get("star_rating") else None
                except (ValueError, TypeError):
                    pass

                eta = _parse_eta(store.get("eta"))
                pickup_eta = max(5, int(eta * 0.5)) if eta else 15

                delivery_fee = store.get("delivery_fee", 0.0)
                minimum_order = store.get("minimum_order")

                price_range = store.get("price_range")
                price_bucket = (
                    "$" * int(price_range)
                    if isinstance(price_range, int) and 0 < price_range <= 4
                    else None
                )

                # Caviar (DoorDash backend) never exposes the exact service
                # fee pre-checkout; build_fee_schedule backfills the
                # published 15%/min-$3 structure as estimated fields.
                fee_schedule = build_fee_schedule(
                    "caviar",
                    delivery_fee=delivery_fee,
                    minimum_order=minimum_order,
                )

                results.append(PlatformResult(
                    platform=Platform.CAVIAR,
                    restaurant_name=name,
                    restaurant_id=store_id,
                    restaurant_url=f"https://www.trycaviar.com/store/{store_id}/",
                    delivery_fee=delivery_fee,
                    service_fee=store.get("service_fee", 0.0),
                    fee_schedule=fee_schedule,
                    estimated_delivery_minutes=eta,
                    pickup_available=True,
                    pickup_fee=0.0,
                    pickup_service_fee=0.0,
                    estimated_pickup_minutes=pickup_eta,
                    minimum_order=minimum_order,
                    rating=rating,
                    rating_count=store.get("num_ratings"),
                    promo_text=store.get("promo_text"),
                    price_bucket=price_bucket,
                    fetched_at=now,
                ))
            except Exception as e:
                logger.debug(f"[Caviar] Parse error: {e}")
                continue

        return results

    async def get_restaurant(self, restaurant_id: str, location: str, mode: str = "delivery") -> Optional[PlatformResult]:
        try:
            lat, lng = await geocode(location)
            loc_cookie = _build_location_cookie(lat, lng, location)
            cookie_header = f"dd_delivery_address={loc_cookie}"
            url = CAVIAR_STORE_URL.format(store_id=restaurant_id)

            import asyncio
            html = await asyncio.to_thread(_cffi_get, url, cookie_header)

            if not html:
                # Try headless browser
                try:
                    from app.services.browser import browser_fetch
                    cookies = [
                        {"name": "dd_delivery_address", "value": loc_cookie,
                         "domain": ".trycaviar.com", "path": "/"},
                    ]
                    html = await browser_fetch(url, cookies=cookies, wait_time=4000)
                except Exception:
                    pass

            if not html:
                return None

            title_m = re.search(r"<title>([^<]+)</title>", html)
            name = ""
            if title_m:
                name = title_m.group(1).split("|")[0].split(" - ")[0].strip()

            full_text = _extract_rsc_text(html)
            delivery_fee = 0.0
            service_fee = 0.0
            eta = 30
            rating = None
            rating_count = None
            promo = None

            if full_text:
                # 2026: fee/promo from the DeliveryFeeLayout store header,
                # bounded away from DashPass marketing copy (shared parser).
                header_fees = _dd_extract_store_header_fees(full_text)
                if header_fees["delivery_fee"] is not None:
                    delivery_fee = header_fees["delivery_fee"]
                if header_fees["promo"]:
                    promo = header_fees["promo"]

                if delivery_fee == 0.0 and header_fees["delivery_fee"] is None:
                    for pattern in [
                        r'"delivery_fee":\s*\{\s*"unit_amount":\s*(\d+)',
                        r'"deliveryFee":\s*(\d+)',
                        r'"delivery_fee":(\d+)',
                    ]:
                        fm = re.search(pattern, full_text)
                        if fm:
                            val = int(fm.group(1))
                            delivery_fee = round(val / 100, 2) if val >= 100 else float(val)
                            break

                for pattern in [
                    r'"service_fee":\s*\{\s*"unit_amount":\s*(\d+)',
                    r'"serviceFee":\s*(\d+)',
                ]:
                    fm = re.search(pattern, full_text)
                    if fm:
                        val = int(fm.group(1))
                        service_fee = round(val / 100, 2) if val >= 100 else float(val)
                        break

                eta_match = re.search(r'"asap_time":\s*(\d+)', full_text)
                if eta_match:
                    eta = int(eta_match.group(1))

                rating_match = re.search(r'"star_rating":"([\d.]+)"', full_text)
                if rating_match:
                    rating = float(rating_match.group(1))

                count_match = re.search(r'"num_ratings":(\d+)', full_text)
                if count_match:
                    rating_count = int(count_match.group(1))

            menu_items = _extract_menu_items(html)
            now = datetime.now(timezone.utc).isoformat()
            pickup_eta = max(5, int(eta * 0.5))

            # No exact service fee pre-checkout: let build_fee_schedule fill
            # the published 15%/min-$3 estimate (do NOT pass a flat fee).
            fee_schedule = build_fee_schedule("caviar", delivery_fee=delivery_fee)

            return PlatformResult(
                platform=Platform.CAVIAR,
                restaurant_name=name or f"Store {restaurant_id}",
                restaurant_id=restaurant_id,
                restaurant_url=f"https://www.trycaviar.com/store/{restaurant_id}/",
                menu_items=menu_items,
                delivery_fee=delivery_fee,
                service_fee=service_fee,
                fee_schedule=fee_schedule,
                estimated_delivery_minutes=eta,
                pickup_available=True,
                pickup_fee=0.0,
                pickup_service_fee=0.0,
                estimated_pickup_minutes=pickup_eta,
                rating=rating,
                rating_count=rating_count,
                promo_text=promo,
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[Caviar] get_restaurant failed: {e}")
            return None
