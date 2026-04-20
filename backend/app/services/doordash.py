"""
DoorDash scraper - April 2026.

Uses curl_cffi to impersonate Chrome's TLS fingerprint, bypassing Cloudflare.
DoorDash's /search/store/{query}/ page uses Next.js RSC streaming.
Store data is embedded in <script>self.__next_f.push([1,"..."])</script> tags.
"""

import base64
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import httpx
from curl_cffi import requests as cffi_requests

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

logger = logging.getLogger(__name__)

DD_SEARCH_URL = "https://www.doordash.com/search/store/{query}/"


def _build_location_cookie(lat: float, lng: float, address: str = "") -> str:
    """Build the dd_delivery_address cookie value."""
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


def _extract_rsc_text(html: str) -> str:
    """Extract and combine all RSC text chunks from the HTML page."""
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


def _extract_rsc_stores(html: str) -> list[dict]:
    """Parse DoorDash Next.js RSC streaming payload to extract store records
    with actual fee data from the search page."""
    full_text = _extract_rsc_text(html)
    if not full_text:
        logger.warning("[DoorDash] RSC text extraction returned empty")
        return []

    logger.info(f"[DoorDash] RSC text length: {len(full_text)}")

    stores = []
    seen_ids: set = set()

    # Try primary pattern first
    store_id_matches = list(re.finditer(r'"store_id":"(\d+)"', full_text))
    logger.info(f"[DoorDash] store_id matches: {len(store_id_matches)}")

    # Diagnostic: log some identifiable patterns to understand the RSC format
    if not store_id_matches:
        for diag_pat, diag_name in [
            (r'"store_name"', "store_name_field"),
            (r'"storeName"', "storeName_field"),
            (r'store_id', "store_id_text"),
            (r'storeId', "storeId_text"),
            (r'"delivery_fee"', "delivery_fee_field"),
            (r'"__typename":"Store"', "typename_Store"),
            (r'"__typename":"SearchResult', "typename_SearchResult"),
            (r'Taco Bell|McDonald|Pizza', "known_brands"),
        ]:
            count = len(re.findall(diag_pat, full_text[:200000]))
            if count > 0:
                logger.info(f"[DoorDash] diag: {diag_name}={count}")

    # If no store_id found, try alternate patterns used in some regions
    if not store_id_matches:
        # DoorDash sometimes uses numeric id fields or "storeId"
        alt_patterns = [
            (r'"storeId":"(\d+)"', "storeId"),
            (r'"storeId":(\d+)', "storeId_num"),
            (r'"id":"(\d+)","name":"([^"]+)".*?"store_name"', "id_with_store_name"),
        ]
        for alt_pat, alt_name in alt_patterns:
            alt_matches = re.findall(alt_pat, full_text[:50000])
            if alt_matches:
                logger.info(f"[DoorDash] Found {len(alt_matches)} matches via {alt_name}")
                break

        # Try extracting stores from StoreCard or SearchResultStore patterns
        store_card_matches = re.findall(
            r'"__typename":"(?:Store|StoreSearchResult|SearchResultStore)"[^}]*?"id":"(\d+)"[^}]*?"name":"([^"]+)"',
            full_text,
        )
        if store_card_matches:
            logger.info(f"[DoorDash] Found {len(store_card_matches)} StoreCard matches")
            for store_id, store_name in store_card_matches:
                if store_id in seen_ids:
                    continue
                seen_ids.add(store_id)
                stores.append({
                    "store_id": store_id,
                    "store_name": store_name,
                    "star_rating": None,
                    "num_ratings": None,
                    "store_display_asap_time": None,
                    "store_distance_in_miles": None,
                    "delivery_fee": 0.0,
                    "service_fee": 0.0,
                    "promo_text": None,
                })
            if stores:
                return stores

    for m in store_id_matches or re.finditer(r'"store_id":"(\d+)"', full_text):
        store_id = m.group(1)
        if store_id in seen_ids:
            continue

        # Find the enclosing JSON-like object by searching for { before the match
        # Use a tighter window to avoid capturing data from adjacent stores
        obj_start = full_text.rfind("{", max(0, m.start() - 800), m.start())
        if obj_start == -1:
            obj_start = max(0, m.start() - 500)

        # Find the matching closing brace (approximate - look for next store_id or limit)
        next_store = re.search(r'"store_id":"', full_text[m.end():])
        if next_store:
            obj_end = min(m.end() + next_store.start(), m.end() + 2000)
        else:
            obj_end = min(len(full_text), m.end() + 2000)

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
            """Extract a money field - DoorDash uses cents (unit_amount) or dollar strings."""
            # Try unit_amount pattern: "delivery_fee":{"unit_amount":299,...}
            fm = re.search(
                rf'"{re.escape(field)}":\s*\{{\s*"unit_amount":\s*(\d+)',
                window,
            )
            if fm:
                try:
                    return round(int(fm.group(1)) / 100, 2)
                except (ValueError, TypeError):
                    pass
            # Try display_string pattern: "delivery_fee":{"display_string":"$2.99",...}
            fm = re.search(
                rf'"{re.escape(field)}":\s*\{{[^}}]*"display_string":"(\$?[\d.]+)"',
                window,
            )
            if fm:
                try:
                    return round(float(fm.group(1).replace("$", "")), 2)
                except (ValueError, TypeError):
                    pass
            # Try simple numeric: "delivery_fee":299
            fm = re.search(rf'"{re.escape(field)}":(\d+)', window)
            if fm:
                val = int(fm.group(1))
                if val > 100:
                    return round(val / 100, 2)
                return round(val / 1, 2)  # Already dollars if < 100
            # Try dollar string: "delivery_fee":"$2.99" or "delivery_fee":"2.99"
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

        # Extract fee data - try multiple field names DoorDash uses
        delivery_fee = 0.0
        service_fee = 0.0

        # Try various delivery fee field patterns
        for fee_field in ["delivery_fee", "deliveryFee", "delivery_fee_details"]:
            val = _money_field(fee_field)
            if val > 0:
                delivery_fee = val
                break

        # Also look for "$X.XX delivery fee" or "Delivery Fee $X.XX" text
        if delivery_fee == 0.0:
            fee_text_match = re.search(
                r'\$(\d+\.?\d*)\s*delivery\s*fee',
                window,
                re.IGNORECASE,
            )
            if fee_text_match:
                try:
                    delivery_fee = round(float(fee_text_match.group(1)), 2)
                except ValueError:
                    pass

        # Try various service fee field patterns
        for fee_field in ["service_fee", "serviceFee", "service_fee_details"]:
            val = _money_field(fee_field)
            if val > 0:
                service_fee = val
                break

        # Check for header_text with fee info: "$$2.99 delivery fee"
        header_text = _field("header_text") or ""
        if delivery_fee == 0.0 and header_text:
            fee_match = re.search(r'\$(\d+\.?\d*)', header_text)
            if fee_match:
                try:
                    delivery_fee = round(float(fee_match.group(1)), 2)
                except ValueError:
                    pass

        # Extract promo text
        promo = None
        promo_text = _field("promotion_delivery_fee") or _field("promo_text")
        if promo_text:
            promo = promo_text

        # Check for "$0 delivery fee" patterns indicating a promo
        free_delivery_match = re.search(
            r'(\$0(?:\.00)?\s+delivery\s+fee[^"]*)',
            window,
            re.IGNORECASE,
        )
        if free_delivery_match:
            promo = free_delivery_match.group(1).strip()
            delivery_fee = 0.0

        # Check for num_ratings
        num_ratings = _num_field("num_ratings")

        stores.append({
            "store_id": store_id,
            "store_name": name,
            "star_rating": _field("star_rating"),
            "num_ratings": int(num_ratings) if num_ratings else None,
            "store_display_asap_time": _field("store_display_asap_time"),
            "store_distance_in_miles": _num_field("store_distance_in_miles"),
            "delivery_fee": delivery_fee,
            "service_fee": service_fee,
            "promo_text": promo,
        })

    return stores


def _extract_menu_items(html: str) -> list[MenuItem]:
    """Extract menu items with prices from a DoorDash store detail page RSC payload."""
    full_text = _extract_rsc_text(html)
    if not full_text:
        return []

    menu_items = []
    seen_items: set = set()

    # 2026 format: StorePageCarouselItem with name, description, displayPrice, imgUrl
    for m in re.finditer(
        r'StorePageCarouselItem","id":"(\d+)","name":"([^"]+)"',
        full_text,
    ):
        item_id = m.group(1)
        item_name = m.group(2)

        if item_id in seen_items or not item_name or len(item_name) < 2:
            continue

        if item_name.lower() in seen_items:
            continue

        # Look forward for price, description, image
        window = full_text[m.end():m.end() + 800]

        # Description
        desc_match = re.search(r'"description":"([^"]{0,500})"', window)
        description = desc_match.group(1) if desc_match else None
        if description and len(description) < 3:
            description = None

        # Price: displayPrice is like "$$9.75" or "$9.75"
        price = 0.0
        price_match = re.search(r'"displayPrice":"\$*(\d+\.?\d*)"', window)
        if price_match:
            try:
                price = round(float(price_match.group(1)), 2)
            except ValueError:
                pass

        if price == 0.0:
            price_match = re.search(r'"unitAmount":(\d+)', window)
            if price_match:
                try:
                    val = int(price_match.group(1))
                    price = round(val / 100, 2) if val >= 100 else float(val)
                except ValueError:
                    pass

        if price <= 0:
            continue

        # Image
        img_match = re.search(r'"imgUrl":"(https?://[^"]+)"', window)
        image_url = img_match.group(1) if img_match else None

        seen_items.add(item_id)
        seen_items.add(item_name.lower())

        menu_items.append(MenuItem(
            name=item_name,
            description=description,
            price=price,
            image_url=image_url,
        ))

        if len(menu_items) >= 100:
            break

    # Fallback: old item_id / item_name pattern
    if not menu_items:
        for m in re.finditer(r'"item_id":"(\d+)"', full_text):
            item_id = m.group(1)
            if item_id in seen_items:
                continue

            window = full_text[max(0, m.start() - 300):min(len(full_text), m.end() + 500)]

            name_match = re.search(r'"item_name":"([^"]+)"', window)
            if not name_match:
                name_match = re.search(r'"name":"([^"]+)"', window)
            if not name_match:
                continue

            item_name = name_match.group(1)
            if not item_name or item_name.lower() in seen_items:
                continue

            price = 0.0
            for pat in [r'"unit_amount":(\d+)', r'"price":(\d+)']:
                pm = re.search(pat, window)
                if pm:
                    val = int(pm.group(1))
                    price = round(val / 100, 2) if val >= 100 else float(val)
                    break

            if price <= 0:
                dp = re.search(r'"display_price":"\$?([\d.]+)"', window)
                if dp:
                    price = round(float(dp.group(1)), 2)

            if price <= 0:
                continue

            desc_match = re.search(r'"description":"([^"]{3,300})"', window)
            description = desc_match.group(1) if desc_match else None

            img_match = re.search(r'"image_url":"(https?://[^"]+)"', window)
            if not img_match:
                img_match = re.search(r'"imgUrl":"(https?://[^"]+)"', window)
            image_url = img_match.group(1) if img_match else None

            seen_items.add(item_name.lower())
            seen_items.add(item_id)
            menu_items.append(MenuItem(
                name=item_name,
                description=description,
                price=price,
                image_url=image_url,
            ))

            if len(menu_items) >= 100:
                break

    return menu_items


def _parse_eta(eta_str: Optional[str]) -> int:
    """Parse '30 min' -> 30, '25-35 min' -> 25, None -> 30."""
    if not eta_str:
        return 30
    m = re.search(r"(\d+)", eta_str)
    return int(m.group(1)) if m else 30


def _cffi_get(url: str, cookies: str = "", timeout: int = 15, retries: int = 2) -> Optional[str]:
    """Fetch a URL using curl_cffi with Chrome TLS impersonation (sync).

    DoorDash uses Cloudflare which blocks datacenter IPs even with correct TLS
    fingerprints. This works from residential IPs but may get challenged from
    cloud servers. Retries with different browser impersonation on failure.
    """
    browsers = ["chrome", "chrome110", "chrome120"]
    attempts = min(retries + 1, len(browsers))

    for attempt in range(attempts):
        browser = browsers[attempt % len(browsers)]
        try:
            headers = {
                "Referer": "https://www.doordash.com/",
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
                logger.warning(f"[DoorDash] curl_cffi ({browser}) returned {resp.status_code} for {url[:80]}")
                continue
            html = resp.text

            # Detect Cloudflare challenge/waiting room
            if "waitingroom" in html.lower() or (
                "challenge" in html.lower() and len(html) < 50000
            ):
                logger.warning(f"[DoorDash] Cloudflare challenge ({browser}), attempt {attempt + 1}/{attempts}")
                if attempt < attempts - 1:
                    import time as _time
                    _time.sleep(1)
                continue

            # Check if we got actual page content (RSC data)
            if "store_id" not in html and "store_name" not in html and "__next_f.push" in html:
                logger.warning(f"[DoorDash] Empty RSC shell ({browser}), attempt {attempt + 1}/{attempts}")
                if attempt < attempts - 1:
                    continue
                return None

            logger.info(f"[DoorDash] curl_cffi ({browser}) got {len(html)} bytes for {url[:60]}")
            return html
        except Exception as e:
            logger.warning(f"[DoorDash] curl_cffi ({browser}) request failed: {e}")
            continue

    return None


class DoorDashScraper(BaseScraper):
    PLATFORM_NAME = "doordash"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)

        url = DD_SEARCH_URL.format(query=quote(query, safe=""))

        loc_cookie = _build_location_cookie(lat, lng, location)
        cookie_header = f"dd_delivery_address={loc_cookie}"

        try:
            import asyncio
            html = await asyncio.to_thread(_cffi_get, url, cookie_header)

            if not html:
                return []

            stores = _extract_rsc_stores(html)
            if not stores:
                logger.warning(f"[DoorDash] No stores found in RSC payload for '{query}'")
                return []

            # Sanity-check the location DoorDash actually used. DoorDash ignores
            # the dd_delivery_address cookie and relies on the caller's public
            # IP for geolocation. From a non-residential/datacenter IP this
            # routes to a wrong market, giving irrelevant results.
            full_text = _extract_rsc_text(html)
            response_lats = re.findall(r'"store_latitude":(\-?[0-9.]+)', full_text)
            response_lngs = re.findall(r'"store_longitude":(\-?[0-9.]+)', full_text)
            mismatch = False
            if response_lats and response_lngs:
                try:
                    # Use median to avoid outliers
                    sample_lat = sorted(float(x) for x in response_lats[:20])[len(response_lats[:20]) // 2]
                    sample_lng = sorted(float(x) for x in response_lngs[:20])[len(response_lngs[:20]) // 2]
                    if abs(sample_lat - lat) > 1.5 or abs(sample_lng - lng) > 1.5:
                        logger.warning(
                            f"[DoorDash] IP-geo mismatch: asked for ({lat:.2f},{lng:.2f}) "
                            f"but results are near ({sample_lat:.2f},{sample_lng:.2f}). "
                            f"Dropping results — would be irrelevant to requested location."
                        )
                        mismatch = True
                except (ValueError, TypeError):
                    pass

            if mismatch:
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

                rating_count = store.get("num_ratings")

                eta = _parse_eta(store.get("store_display_asap_time"))
                url = f"https://www.doordash.com/store/{store_id}/"

                delivery_fee = store.get("delivery_fee", 0.0)
                service_fee = store.get("service_fee", 0.0)
                promo = store.get("promo_text")

                pickup_eta = max(5, int(eta * 0.5)) if eta else 15

                results.append(PlatformResult(
                    platform=Platform.DOORDASH,
                    restaurant_name=name,
                    restaurant_id=store_id,
                    restaurant_url=url,
                    delivery_fee=delivery_fee,
                    service_fee=service_fee,
                    estimated_delivery_minutes=eta,
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
                logger.debug(f"[DoorDash] Parse error for store {store}: {e}")
                continue

        return results

    async def get_restaurant(
        self, restaurant_id: str, location: str
    ) -> Optional[PlatformResult]:
        """Fetch full restaurant details + menu from the store page RSC payload."""
        try:
            lat, lng = await geocode(location)
            loc_cookie = _build_location_cookie(lat, lng, location)
            cookie_header = f"dd_delivery_address={loc_cookie}"
            url = f"https://www.doordash.com/store/{restaurant_id}/"

            import asyncio
            html = await asyncio.to_thread(_cffi_get, url, cookie_header)

            if not html:
                return None

            # Extract name from page title
            title_m = re.search(r"<title>([^<]+)</title>", html)
            name = ""
            if title_m:
                # Title format: "Restaurant Name - Delivery Menu | DoorDash"
                raw_title = title_m.group(1)
                name = raw_title.split("|")[0].split(" - ")[0].strip()

            # Extract store data from RSC payload
            full_text = _extract_rsc_text(html)

            delivery_fee = 0.0
            service_fee = 0.0
            eta = 30
            rating = None
            rating_count = None
            promo = None

            if full_text:
                # Look for fee data in the store detail RSC
                # Delivery fee
                for pattern in [
                    r'"delivery_fee":\s*\{\s*"unit_amount":\s*(\d+)',
                    r'"deliveryFee":\s*(\d+)',
                    r'"delivery_fee":(\d+)',
                ]:
                    fm = re.search(pattern, full_text)
                    if fm:
                        try:
                            val = int(fm.group(1))
                            delivery_fee = round(val / 100, 2) if val >= 100 else float(val)
                            break
                        except ValueError:
                            pass

                # Dollar string pattern
                if delivery_fee == 0.0:
                    fm = re.search(r'"delivery_fee":\s*\{[^}]*"display_string":"?\$?([\d.]+)', full_text)
                    if fm:
                        try:
                            delivery_fee = round(float(fm.group(1)), 2)
                        except ValueError:
                            pass

                # Service fee
                for pattern in [
                    r'"service_fee":\s*\{\s*"unit_amount":\s*(\d+)',
                    r'"serviceFee":\s*(\d+)',
                    r'"service_fee":(\d+)',
                ]:
                    fm = re.search(pattern, full_text)
                    if fm:
                        try:
                            val = int(fm.group(1))
                            service_fee = round(val / 100, 2) if val >= 100 else float(val)
                            break
                        except ValueError:
                            pass

                # ETA
                eta_match = re.search(r'"asap_time":\s*(\d+)', full_text)
                if not eta_match:
                    eta_match = re.search(r'"store_display_asap_time":"([^"]+)"', full_text)
                if eta_match:
                    try:
                        eta_val = eta_match.group(1)
                        nums = re.findall(r'\d+', eta_val)
                        if nums:
                            eta = int(nums[0])
                    except (ValueError, IndexError):
                        pass

                # Rating
                rating_match = re.search(r'"star_rating":"([\d.]+)"', full_text)
                if not rating_match:
                    rating_match = re.search(r'"averageRating":([\d.]+)', full_text)
                if rating_match:
                    try:
                        rating = float(rating_match.group(1))
                    except ValueError:
                        pass

                # Rating count
                count_match = re.search(r'"num_ratings":(\d+)', full_text)
                if not count_match:
                    count_match = re.search(r'"numRatings":(\d+)', full_text)
                if count_match:
                    try:
                        rating_count = int(count_match.group(1))
                    except ValueError:
                        pass

                # Promo
                promo_match = re.search(r'"promotion_delivery_fee":"([^"]+)"', full_text)
                if not promo_match:
                    free_match = re.search(r'(\$0(?:\.00)?\s+delivery\s+fee[^"]*)', full_text, re.IGNORECASE)
                    if free_match:
                        promo = free_match.group(1).strip()
                        delivery_fee = 0.0
                else:
                    promo = promo_match.group(1)

            # Extract menu items
            menu_items = _extract_menu_items(html)

            now = datetime.now(timezone.utc).isoformat()
            pickup_eta = max(5, int(eta * 0.5)) if eta else 15
            return PlatformResult(
                platform=Platform.DOORDASH,
                restaurant_name=name or f"Store {restaurant_id}",
                restaurant_id=restaurant_id,
                restaurant_url=url,
                menu_items=menu_items,
                delivery_fee=delivery_fee,
                service_fee=service_fee,
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
            logger.warning(f"[DoorDash] get_restaurant failed: {e}")
            return None
