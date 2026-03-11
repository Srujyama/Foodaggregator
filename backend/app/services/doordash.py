"""
DoorDash scraper - Updated March 2026.

Strategy: DoorDash's /search/store/{query}/ page is Next.js App Router with
React Server Components (RSC). The server renders the store listing server-side
and streams JSON store data inside <script>self.__next_f.push([1,"..."])</script>
tags. Each tag's string argument (when JSON-parsed) contains RSC payload chunks
that include store records with:
  - store_name, store_id, star_rating, store_display_asap_time,
    store_distance_in_miles, store_latitude, store_longitude

Location is passed via the `dd_delivery_address` cookie — a base64-encoded
JSON object containing latitude, longitude and address details. When this cookie
is set, DoorDash's SSR uses it to localise the store feed.

No GQL, no auth required — just an HTTP GET + HTML parse.
"""

import base64
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx

from app.models.food import Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

logger = logging.getLogger(__name__)

DD_SEARCH_URL = "https://www.doordash.com/search/store/{query}/"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # omit br — not supported by httpx default
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


def _build_location_cookie(lat: float, lng: float, address: str = "") -> str:
    """Build the dd_delivery_address cookie value that tells DoorDash where to search.

    DoorDash's SSR reads this cookie to localise the store feed. The value is a
    base64-encoded JSON blob (no padding, URL-safe).
    """
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


def _extract_rsc_stores(html: str) -> list[dict]:
    """Parse DoorDash Next.js RSC streaming payload to extract store records.

    DoorDash embeds store data as:
      <script>self.__next_f.push([1,"...escaped JSON RSC chunk..."])</script>

    Each chunk, once JSON-parsed (to unescape), contains store records like:
      {"store_name":"Pizza Place","store_id":"12345","star_rating":"4.5",
       "store_display_asap_time":"30 min","store_distance_in_miles":0.5, ...}
    """
    # Collect all RSC string chunks
    combined = []
    # Match the argument of each push call — it's a JSON string or [int, string]
    pattern = re.compile(
        r'self\.__next_f\.push\(\s*\[1\s*,\s*("(?:[^"\\]|\\.)*")\s*\]\s*\)',
        re.DOTALL,
    )
    for m in pattern.finditer(html):
        try:
            chunk = json.loads(m.group(1))  # unescape the JSON string
            combined.append(chunk)
        except (json.JSONDecodeError, ValueError):
            pass

    full_text = "".join(combined)
    if not full_text:
        return []

    # Each store appears as a JSON object embedded in the text.
    # We match each store_name occurrence and extract a window of text around it
    # to pull sibling fields, then parse them out individually.
    stores = []
    seen_ids: set = set()

    # Find each store block by locating "store_id":"..." and grabbing context
    # Use a broad regex to find a chunk that includes both store_id and store_name
    store_block_pattern = re.compile(
        r'\{[^{}]*"store_id":"(\d+)"[^{}]*"store_name":"([^"]+)"[^{}]*\}|'
        r'\{[^{}]*"store_name":"([^"]+)"[^{}]*"store_id":"(\d+)"[^{}]*\}',
        re.DOTALL,
    )

    # Broader approach: find store_id and collect surrounding JSON object
    for m in re.finditer(r'"store_id":"(\d+)"', full_text):
        store_id = m.group(1)
        if store_id in seen_ids:
            continue

        # Extract a window of characters around this match to find sibling fields
        start = max(0, m.start() - 1500)
        end = min(len(full_text), m.end() + 1500)
        window = full_text[start:end]

        def _field(field: str) -> Optional[str]:
            fm = re.search(rf'"{re.escape(field)}":"([^"]*)"', window)
            return fm.group(1) if fm else None

        def _num_field(field: str) -> Optional[float]:
            fm = re.search(rf'"{re.escape(field)}":([\d.]+)', window)
            try:
                return float(fm.group(1)) if fm else None
            except (ValueError, TypeError):
                return None

        name = _field("store_name")
        if not name:
            continue

        seen_ids.add(store_id)
        stores.append({
            "store_id": store_id,
            "store_name": name,
            "star_rating": _field("star_rating"),
            "store_display_asap_time": _field("store_display_asap_time"),
            "store_distance_in_miles": _num_field("store_distance_in_miles"),
            "store_latitude": _num_field("store_latitude"),
            "store_longitude": _num_field("store_longitude"),
        })

    return stores


def _parse_eta(eta_str: Optional[str]) -> int:
    """Parse '30 min' → 30, '25-35 min' → 25, None → 30."""
    if not eta_str:
        return 30
    m = re.search(r"(\d+)", eta_str)
    return int(m.group(1)) if m else 30


class DoorDashScraper(BaseScraper):
    PLATFORM_NAME = "doordash"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)

        url = DD_SEARCH_URL.format(query=quote(query, safe=""))

        # Build location cookie so DoorDash SSR localises results to the user
        loc_cookie = _build_location_cookie(lat, lng, location)
        cookie_header = f"dd_delivery_address={loc_cookie}"

        headers = {
            **_BROWSER_HEADERS,
            "Cookie": cookie_header,
            "Referer": "https://www.doordash.com/",
        }

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                logger.warning(
                    f"[DoorDash] Search page returned {resp.status_code} for '{query}'"
                )
                return []

            html = resp.text
            stores = _extract_rsc_stores(html)
            if not stores:
                logger.warning(f"[DoorDash] No stores found in RSC payload for '{query}'")
                return []

            results = self._build_results(stores)
            logger.info(f"[DoorDash] {len(results)} results for '{query}' near ({lat:.3f},{lng:.3f})")
            return results

        except Exception as e:
            logger.warning(f"[DoorDash] Search failed: {e}")
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

                rating_str = store.get("star_rating")
                rating: Optional[float] = None
                try:
                    rating = float(rating_str) if rating_str else None
                except (ValueError, TypeError):
                    pass

                eta = _parse_eta(store.get("store_display_asap_time"))
                url = f"https://www.doordash.com/store/{store_id}/"

                results.append(PlatformResult(
                    platform=Platform.DOORDASH,
                    restaurant_name=name,
                    restaurant_id=store_id,
                    restaurant_url=url,
                    delivery_fee=0.0,   # DoorDash shows $0 for first order promotions
                    service_fee=0.0,
                    estimated_delivery_minutes=eta,
                    rating=rating,
                    rating_count=None,
                    promo_text="$0 delivery fee, first order",
                    fetched_at=now,
                ))
            except Exception as e:
                logger.debug(f"[DoorDash] Parse error for store {store}: {e}")
                continue

        return results

    async def get_restaurant(
        self, restaurant_id: str, location: str
    ) -> Optional[PlatformResult]:
        """Fetch individual restaurant details from the store page HTML."""
        try:
            lat, lng = await geocode(location)
            loc_cookie = _build_location_cookie(lat, lng, location)
            headers = {
                **_BROWSER_HEADERS,
                "Cookie": f"dd_delivery_address={loc_cookie}",
                "Referer": "https://www.doordash.com/search/",
            }
            url = f"https://www.doordash.com/store/{restaurant_id}/"

            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                return None

            # Extract name from page title
            title_m = re.search(r"<title>([^<]+)</title>", resp.text)
            name = ""
            if title_m:
                name = title_m.group(1).split("|")[0].split("-")[0].strip()

            now = datetime.now(timezone.utc).isoformat()
            return PlatformResult(
                platform=Platform.DOORDASH,
                restaurant_name=name or f"Store {restaurant_id}",
                restaurant_id=restaurant_id,
                restaurant_url=url,
                delivery_fee=0.0,
                service_fee=0.0,
                estimated_delivery_minutes=30,
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[DoorDash] get_restaurant failed: {e}")
            return None
