"""
Grubhub scraper - Rewritten March 2026.

Previous approach: Anonymous OAuth at api-gtm.grubhub.com/auth, blocked by PerimeterX.

New approach: HTML scraping of grubhub.com search and restaurant pages.
Grubhub's website uses Next.js with server-side rendering. Restaurant data
is embedded in:
  1. JSON-LD structured data (<script type="application/ld+json">)
  2. __NEXT_DATA__ script tag (Next.js page props)
  3. Inline <script> tags with window.__GRUBHUB_SEARCH_RESULTS__ or similar

The search page at /search?query=X&location=Y embeds search results.
Restaurant detail pages at /restaurant/slug embed menu items with prices.

If GRUBHUB_BEARER_TOKEN is set, the API approach is still tried first as a
fast path. The HTML scraping is the fallback that doesn't require auth.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote, quote_plus

import httpx

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

logger = logging.getLogger(__name__)

# API endpoints (used only when GRUBHUB_BEARER_TOKEN is available)
AUTH_URL = "https://api-gtm.grubhub.com/auth"
SEARCH_URL_API = "https://api-gtm.grubhub.com/restaurants/search/search_listing"
SEARCH_URL_LEGACY = "https://api-gtm.grubhub.com/restaurants/search"
RESTAURANT_URL_API = "https://api-gtm.grubhub.com/restaurants/{restaurant_id}"

# HTML scraping URLs
GH_SEARCH_URL = "https://www.grubhub.com/search"
GH_RESTAURANT_URL = "https://www.grubhub.com/restaurant/{slug}"

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
    "Accept-Encoding": "gzip, deflate",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


def _extract_next_data(html: str) -> dict:
    """Extract __NEXT_DATA__ JSON from a Next.js page."""
    pattern = re.compile(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">\s*(\{.*?\})\s*</script>',
        re.DOTALL,
    )
    m = pattern.search(html)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def _extract_jsonld(html: str) -> list[dict]:
    """Extract all JSON-LD blocks from HTML."""
    results = []
    for m in re.finditer(
        r'<script\s+type="application/ld\+json">\s*(\{.*?\})\s*</script>',
        html,
        re.DOTALL,
    ):
        try:
            results.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass
    return results


def _extract_inline_json(html: str) -> list[dict]:
    """Extract inline JSON objects that contain restaurant data."""
    results = []
    # Look for window.__INITIAL_STATE__ or similar patterns
    for pattern in [
        r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
        r'window\.__GRUBHUB_SEARCH_RESULTS__\s*=\s*(\{.*?\});',
        r'window\.__NEXT_DATA__\s*=\s*(\{.*?\});',
    ]:
        m = re.search(pattern, html, re.DOTALL)
        if m:
            try:
                results.append(json.loads(m.group(1)))
            except json.JSONDecodeError:
                pass
    return results


def _deep_find(obj, key: str, results: list = None) -> list:
    """Recursively find all values for a given key in a nested dict/list."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                results.append(v)
            _deep_find(v, key, results)
    elif isinstance(obj, list):
        for item in obj:
            _deep_find(item, key, results)
    return results


def _cents_to_dollars(value) -> float:
    """Convert a value to dollars. Uses context: values >= 100 are assumed cents."""
    if value is None:
        return 0.0
    try:
        v = float(value)
        if v == 0:
            return 0.0
        # If the value looks like cents (>= 100), convert
        if abs(v) >= 100:
            return round(v / 100, 2)
        # If it has no decimal and is between 1-99, it's ambiguous.
        # Treat values 1-99 with no decimal as cents if they seem high.
        # For fees, values > 10 are very likely cents (nobody pays >$10 delivery fee commonly)
        if abs(v) > 10 and v == int(v):
            return round(v / 100, 2)
        return round(v, 2)
    except (ValueError, TypeError):
        return 0.0


def _parse_search_page(html: str) -> list[dict]:
    """Parse Grubhub search results page HTML to extract restaurant data."""
    restaurants = []

    # Strategy 1: __NEXT_DATA__ (most reliable for Next.js pages)
    next_data = _extract_next_data(html)
    if next_data:
        # Grubhub's Next.js page props contain search results
        page_props = next_data.get("props", {}).get("pageProps", {})

        # Look for restaurant results in various possible locations
        search_results = (
            page_props.get("searchResults", {}).get("results", [])
            or page_props.get("results", [])
            or _deep_find(page_props, "results")
        )

        if isinstance(search_results, list) and search_results:
            # If deep_find returned nested lists, flatten
            if search_results and isinstance(search_results[0], list):
                search_results = [
                    item for sublist in search_results
                    for item in (sublist if isinstance(sublist, list) else [sublist])
                ]

            for item in search_results:
                if not isinstance(item, dict):
                    continue
                restaurant = item.get("restaurant") or item
                if not isinstance(restaurant, dict):
                    continue

                name = (
                    restaurant.get("name")
                    or restaurant.get("restaurant_name")
                    or restaurant.get("restaurantName")
                    or ""
                )
                rest_id = str(
                    restaurant.get("id")
                    or restaurant.get("restaurant_id")
                    or restaurant.get("restaurantId")
                    or ""
                )

                if name and rest_id:
                    restaurants.append(_extract_restaurant_data(restaurant))

    # Strategy 2: JSON-LD structured data
    if not restaurants:
        for ld in _extract_jsonld(html):
            if ld.get("@type") == "Restaurant" or ld.get("@type") == "FoodEstablishment":
                restaurants.append({
                    "name": ld.get("name", ""),
                    "restaurant_id": ld.get("identifier", ld.get("@id", "")),
                    "rating": ld.get("aggregateRating", {}).get("ratingValue"),
                    "rating_count": ld.get("aggregateRating", {}).get("reviewCount"),
                    "delivery_fee": 0.0,
                    "service_fee": 0.0,
                    "eta": 35,
                    "promo": None,
                    "slug": "",
                    "url": ld.get("url", ""),
                })

    # Strategy 3: Regex extraction from inline scripts
    if not restaurants:
        inline_data = _extract_inline_json(html)
        for data in inline_data:
            for result in _deep_find(data, "restaurants") or _deep_find(data, "results"):
                if isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict) and (item.get("name") or item.get("restaurant_name")):
                            restaurants.append(_extract_restaurant_data(item))
                elif isinstance(result, dict) and (result.get("name") or result.get("restaurant_name")):
                    restaurants.append(_extract_restaurant_data(result))

    # Strategy 4: Raw HTML scraping as last resort
    # Grubhub renders restaurant cards with data attributes
    if not restaurants:
        restaurants = _scrape_html_cards(html)

    return restaurants


def _extract_restaurant_data(restaurant: dict) -> dict:
    """Extract normalized restaurant data from a Grubhub API/JSON object."""
    name = (
        restaurant.get("name")
        or restaurant.get("restaurant_name")
        or restaurant.get("restaurantName")
        or ""
    )
    rest_id = str(
        restaurant.get("id")
        or restaurant.get("restaurant_id")
        or restaurant.get("restaurantId")
        or ""
    )

    # Delivery fee
    fee_obj = restaurant.get("delivery_fee") or restaurant.get("deliveryFee") or {}
    if isinstance(fee_obj, dict):
        delivery_fee = _cents_to_dollars(fee_obj.get("amount") or fee_obj.get("unit_amount") or 0)
    else:
        delivery_fee = _cents_to_dollars(fee_obj)

    # Service fee
    svc_obj = restaurant.get("service_fee") or restaurant.get("serviceFee") or {}
    if isinstance(svc_obj, dict):
        service_fee = _cents_to_dollars(svc_obj.get("amount") or svc_obj.get("unit_amount") or 0)
    else:
        service_fee = _cents_to_dollars(svc_obj)

    # ETA
    eta = int(
        restaurant.get("estimated_delivery_time")
        or restaurant.get("estimatedDeliveryTime")
        or restaurant.get("delivery_time_estimate")
        or restaurant.get("pickup_estimate")
        or 35
    )

    # Rating
    rating_data = restaurant.get("ratings") or restaurant.get("rating") or {}
    if isinstance(rating_data, dict):
        rating = float(rating_data.get("actual_rating_value") or rating_data.get("ratingValue") or 0) or None
        rating_count = int(rating_data.get("rating_count") or rating_data.get("reviewCount") or 0) or None
    else:
        try:
            rating = float(rating_data) if rating_data else None
        except (ValueError, TypeError):
            rating = None
        rating_count = None

    # Promo
    promo = None
    promo_info = (
        restaurant.get("promoted_delivery_fee")
        or restaurant.get("promo_info")
        or restaurant.get("promotion")
        or {}
    )
    if isinstance(promo_info, dict):
        promo = promo_info.get("promo_message") or promo_info.get("display_string") or promo_info.get("text")
    elif isinstance(promo_info, str):
        promo = promo_info

    # Slug/URL
    slug = (
        restaurant.get("slug")
        or restaurant.get("restaurant_path")
        or restaurant.get("restaurantSlug")
        or ""
    )
    url = ""
    if slug:
        if slug.startswith("/"):
            url = f"https://www.grubhub.com{slug}"
        elif slug.startswith("http"):
            url = slug
        else:
            url = f"https://www.grubhub.com/restaurant/{slug}"
    elif rest_id:
        url = f"https://www.grubhub.com/restaurant/{rest_id}"

    # Minimum order
    min_obj = restaurant.get("minimum_order_amount") or restaurant.get("orderMinimum") or {}
    minimum_order = None
    if isinstance(min_obj, dict):
        minimum_order = _cents_to_dollars(min_obj.get("amount") or 0) or None
    elif min_obj:
        minimum_order = _cents_to_dollars(min_obj) or None

    return {
        "name": name,
        "restaurant_id": rest_id,
        "delivery_fee": delivery_fee,
        "service_fee": service_fee,
        "eta": eta,
        "rating": rating,
        "rating_count": rating_count,
        "promo": promo,
        "slug": slug,
        "url": url,
        "minimum_order": minimum_order,
    }


def _scrape_html_cards(html: str) -> list[dict]:
    """Fallback: extract restaurant data from HTML card elements."""
    restaurants = []

    # Look for restaurant card patterns with data in the markup
    # Grubhub uses data-testid or class-based restaurant cards
    card_pattern = re.compile(
        r'<a[^>]*href="(/restaurant/[^"]+)"[^>]*>.*?</a>',
        re.DOTALL,
    )

    for card_match in card_pattern.finditer(html):
        card_html = card_match.group(0)
        slug_match = re.search(r'href="/restaurant/([^"?]+)', card_html)
        if not slug_match:
            continue

        slug = slug_match.group(1)

        # Extract name from aria-label or inner text
        name_match = re.search(r'aria-label="([^"]+)"', card_html)
        if not name_match:
            name_match = re.search(r'<h\d[^>]*>([^<]+)</h\d>', card_html)
        if not name_match:
            continue

        name = name_match.group(1).strip()

        # Extract rating
        rating = None
        rating_match = re.search(r'(\d+\.?\d*)\s*(?:stars?|rating)', card_html, re.IGNORECASE)
        if rating_match:
            try:
                rating = float(rating_match.group(1))
            except ValueError:
                pass

        # Extract delivery fee from card text
        delivery_fee = 0.0
        fee_match = re.search(r'\$(\d+\.?\d*)\s*delivery', card_html, re.IGNORECASE)
        if fee_match:
            try:
                delivery_fee = float(fee_match.group(1))
            except ValueError:
                pass

        # Extract ETA
        eta = 35
        eta_match = re.search(r'(\d+)[-–]?(\d+)?\s*min', card_html, re.IGNORECASE)
        if eta_match:
            try:
                eta = int(eta_match.group(1))
            except ValueError:
                pass

        restaurants.append({
            "name": name,
            "restaurant_id": slug,
            "delivery_fee": delivery_fee,
            "service_fee": 0.0,
            "eta": eta,
            "rating": rating,
            "rating_count": None,
            "promo": None,
            "slug": slug,
            "url": f"https://www.grubhub.com/restaurant/{slug}",
            "minimum_order": None,
        })

    return restaurants


def _parse_menu_page(html: str) -> tuple[dict, list[MenuItem]]:
    """Parse a Grubhub restaurant page to extract restaurant info and menu items."""
    restaurant_info = {}
    menu_items = []

    # Extract from __NEXT_DATA__
    next_data = _extract_next_data(html)
    if next_data:
        page_props = next_data.get("props", {}).get("pageProps", {})

        # Restaurant info
        rest_data = (
            page_props.get("restaurant")
            or page_props.get("restaurantData")
            or page_props.get("storeData")
            or {}
        )
        if rest_data:
            restaurant_info = _extract_restaurant_data(rest_data)

        # Menu items from page props
        menu_categories = (
            _deep_find(page_props, "menu_category_list")
            or _deep_find(page_props, "menuCategories")
            or _deep_find(page_props, "menu_items")
            or _deep_find(page_props, "categories")
        )

        for categories in menu_categories:
            if isinstance(categories, list):
                for category in categories:
                    if not isinstance(category, dict):
                        continue
                    items = (
                        category.get("menu_item_list")
                        or category.get("menuItems")
                        or category.get("items")
                        or []
                    )
                    for item in items[:30]:
                        if not isinstance(item, dict):
                            continue
                        mi = _parse_menu_item(item)
                        if mi:
                            menu_items.append(mi)
                        if len(menu_items) >= 50:
                            break
                    if len(menu_items) >= 50:
                        break

    # Fallback: JSON-LD for menu items
    if not menu_items:
        for ld in _extract_jsonld(html):
            if ld.get("@type") == "Menu" or ld.get("hasMenu"):
                menu_data = ld.get("hasMenu") or ld
                if isinstance(menu_data, dict):
                    sections = menu_data.get("hasMenuSection") or []
                    if isinstance(sections, list):
                        for section in sections:
                            items = section.get("hasMenuItem") or []
                            if isinstance(items, list):
                                for item in items:
                                    if isinstance(item, dict):
                                        name = item.get("name", "")
                                        price = 0.0
                                        offers = item.get("offers") or {}
                                        if isinstance(offers, dict):
                                            try:
                                                price = float(offers.get("price", 0))
                                            except (ValueError, TypeError):
                                                pass
                                        if name and price > 0:
                                            menu_items.append(MenuItem(
                                                name=name,
                                                description=item.get("description"),
                                                price=price,
                                                image_url=item.get("image"),
                                            ))
                                        if len(menu_items) >= 50:
                                            break
                            if len(menu_items) >= 50:
                                break

    # Fallback: regex for menu items from HTML
    if not menu_items:
        menu_items = _scrape_menu_html(html)

    return restaurant_info, menu_items


def _parse_menu_item(item: dict) -> Optional[MenuItem]:
    """Parse a single menu item dict into a MenuItem model."""
    name = item.get("name") or item.get("item_name") or item.get("itemName") or ""
    if not name or len(name) < 2:
        return None

    # Price
    price_obj = item.get("price") or item.get("itemPrice") or {}
    if isinstance(price_obj, dict):
        price = _cents_to_dollars(price_obj.get("amount") or price_obj.get("unit_amount") or 0)
    else:
        price = _cents_to_dollars(price_obj)

    if price <= 0:
        # Try display price
        display = item.get("display_price") or item.get("displayPrice") or ""
        if display:
            try:
                price = float(str(display).replace("$", "").replace(",", ""))
            except ValueError:
                pass

    if price <= 0:
        return None

    description = item.get("description") or item.get("item_description") or None
    if description and len(description) < 3:
        description = None

    # Image
    image_url = None
    media = item.get("media_image") or item.get("image") or item.get("imageUrl")
    if isinstance(media, dict):
        image_url = media.get("base_url") or media.get("url")
    elif isinstance(media, str) and media.startswith("http"):
        image_url = media

    return MenuItem(
        name=name,
        description=description,
        price=round(price, 2),
        image_url=image_url,
    )


def _scrape_menu_html(html: str) -> list[MenuItem]:
    """Last-resort: scrape menu items from the raw HTML of a restaurant page."""
    items = []
    seen = set()

    # Look for menu item patterns in HTML
    # Grubhub renders menu items with price data
    item_pattern = re.compile(
        r'<(?:div|li|article)[^>]*class="[^"]*menu[-_]?item[^"]*"[^>]*>(.*?)</(?:div|li|article)>',
        re.DOTALL | re.IGNORECASE,
    )

    for m in item_pattern.finditer(html):
        item_html = m.group(1)

        # Extract name
        name_match = re.search(r'<(?:h\d|span|p)[^>]*class="[^"]*name[^"]*"[^>]*>([^<]+)', item_html)
        if not name_match:
            name_match = re.search(r'<(?:h\d|span)[^>]*>([^<]{3,60})</(?:h\d|span)>', item_html)
        if not name_match:
            continue

        name = name_match.group(1).strip()
        if name.lower() in seen or len(name) < 3:
            continue

        # Extract price
        price_match = re.search(r'\$(\d+\.?\d{0,2})', item_html)
        if not price_match:
            continue

        try:
            price = float(price_match.group(1))
        except ValueError:
            continue

        if price <= 0 or price > 200:
            continue

        # Extract description
        desc_match = re.search(r'<p[^>]*class="[^"]*desc[^"]*"[^>]*>([^<]+)', item_html)
        description = desc_match.group(1).strip() if desc_match else None

        seen.add(name.lower())
        items.append(MenuItem(
            name=name,
            description=description,
            price=round(price, 2),
            image_url=None,
        ))

        if len(items) >= 50:
            break

    return items


class GrubhubScraper(BaseScraper):
    PLATFORM_NAME = "grubhub"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)

        # Fast path: try API if bearer token is available
        env_token = os.environ.get("GRUBHUB_BEARER_TOKEN", "").strip()
        if env_token:
            api_results = await self._search_api(query, lat, lng, env_token)
            if api_results:
                return api_results

        # Main path: HTML scraping (no auth needed)
        return await self._search_html(query, location, lat, lng)

    async def _search_html(
        self, query: str, location: str, lat: float, lng: float
    ) -> list[PlatformResult]:
        """Search by scraping the Grubhub website HTML."""
        # Grubhub search URL format
        params = {
            "orderMethod": "delivery",
            "locationMode": "DELIVERY",
            "facetSet": "umaNew",
            "pageSize": "20",
            "hideHateos": "true",
            "queryText": query,
            "latitude": str(lat),
            "longitude": str(lng),
        }

        # Build the search URL - try the direct food search page
        search_url = f"https://www.grubhub.com/search?queryText={quote_plus(query)}"

        # Also set cookies for location
        location_cookie = json.dumps({
            "latitude": lat,
            "longitude": lng,
            "address": location,
        })

        headers = {
            **_BROWSER_HEADERS,
            "Cookie": f"ghs_userLocation={quote(location_cookie)}",
            "Referer": "https://www.grubhub.com/",
        }

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
            ) as client:
                # Try the search page first
                resp = await client.get(search_url, headers=headers)

                if resp.status_code != 200:
                    # Try alternative search path
                    alt_url = f"https://www.grubhub.com/delivery/search?query={quote_plus(query)}&lat={lat}&lng={lng}"
                    resp = await client.get(alt_url, headers=headers)

                if resp.status_code != 200:
                    logger.warning(f"[Grubhub] Search page returned {resp.status_code}")
                    return []

            html = resp.text
            restaurant_data = _parse_search_page(html)

            if not restaurant_data:
                logger.warning(f"[Grubhub] No restaurants found in HTML for '{query}'")
                return []

            results = self._build_results(restaurant_data, query, location)
            logger.info(f"[Grubhub] {len(results)} results via HTML scraping for '{query}'")
            return results

        except Exception as e:
            logger.warning(f"[Grubhub] HTML search failed: {e}")
            return []

    async def _search_api(
        self, query: str, lat: float, lng: float, token: str
    ) -> list[PlatformResult]:
        """Search using the Grubhub API (requires valid bearer token)."""
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.grubhub.com/",
            "Origin": "https://www.grubhub.com",
        }

        params = {
            "orderMethod": "delivery",
            "locationMode": "DELIVERY",
            "facetSet": "umaNew",
            "pageSize": 20,
            "hideHateos": "true",
            "sortSetId": "umaSorts",
            "queryText": query,
            "latitude": lat,
            "longitude": lng,
            "timezoneOffset": -300,
        }

        for url in [SEARCH_URL_API, SEARCH_URL_LEGACY]:
            api_params = dict(params)
            if url == SEARCH_URL_LEGACY:
                api_params["facetSet"] = "umamiV6"
                api_params["facet"] = "open_now:true"
                api_params["searchMetrics"] = "true"
                del api_params["sortSetId"]

            try:
                async with self._make_client(headers) as client:
                    resp = await client.get(url, params=api_params)
                    resp.raise_for_status()
                    data = resp.json()

                results_data = (
                    data.get("search_result", {}).get("results", [])
                    or data.get("results", [])
                    or data.get("restaurants", [])
                    or []
                )

                parsed = []
                now = datetime.now(timezone.utc).isoformat()
                for item in results_data:
                    restaurant = item.get("restaurant") or item
                    rd = _extract_restaurant_data(restaurant)
                    if rd["name"] and rd["restaurant_id"]:
                        parsed.append(PlatformResult(
                            platform=Platform.GRUBHUB,
                            restaurant_name=rd["name"],
                            restaurant_id=rd["restaurant_id"],
                            restaurant_url=rd["url"],
                            delivery_fee=rd["delivery_fee"],
                            service_fee=rd["service_fee"],
                            estimated_delivery_minutes=rd["eta"],
                            minimum_order=rd["minimum_order"],
                            rating=rd["rating"],
                            rating_count=rd["rating_count"],
                            promo_text=rd["promo"],
                            fetched_at=now,
                        ))

                if parsed:
                    logger.info(f"[Grubhub] {len(parsed)} results via API for '{query}'")
                    return parsed

            except httpx.HTTPStatusError as e:
                logger.warning(f"[Grubhub] API {e.response.status_code}: {e.response.text[:200]}")
                if e.response.status_code in (401, 403):
                    break  # Token is invalid, don't retry
            except Exception as e:
                logger.warning(f"[Grubhub] API search error: {e}")

        return []

    def _build_results(
        self, restaurant_data: list[dict], query: str, location: str
    ) -> list[PlatformResult]:
        results = []
        now = datetime.now(timezone.utc).isoformat()

        for rd in restaurant_data:
            try:
                name = rd.get("name", "")
                rest_id = str(rd.get("restaurant_id", ""))
                if not name or not rest_id:
                    continue

                results.append(PlatformResult(
                    platform=Platform.GRUBHUB,
                    restaurant_name=name,
                    restaurant_id=rest_id,
                    restaurant_url=rd.get("url") or f"https://www.grubhub.com/restaurant/{rest_id}",
                    delivery_fee=rd.get("delivery_fee", 0.0),
                    service_fee=rd.get("service_fee", 0.0),
                    estimated_delivery_minutes=rd.get("eta", 35),
                    minimum_order=rd.get("minimum_order"),
                    rating=rd.get("rating"),
                    rating_count=rd.get("rating_count"),
                    promo_text=rd.get("promo"),
                    fetched_at=now,
                ))
            except Exception as e:
                logger.debug(f"[Grubhub] Build result error: {e}")
                continue

        return results

    async def get_restaurant(
        self, restaurant_id: str, location: str
    ) -> Optional[PlatformResult]:
        """Fetch restaurant details + menu from the restaurant page."""
        # Try API first if token available
        env_token = os.environ.get("GRUBHUB_BEARER_TOKEN", "").strip()
        if env_token:
            result = await self._get_restaurant_api(restaurant_id, env_token)
            if result:
                return result

        # HTML scraping fallback
        return await self._get_restaurant_html(restaurant_id, location)

    async def _get_restaurant_html(
        self, restaurant_id: str, location: str
    ) -> Optional[PlatformResult]:
        """Fetch restaurant details from the HTML page."""
        try:
            lat, lng = await geocode(location)
            location_cookie = json.dumps({
                "latitude": lat,
                "longitude": lng,
                "address": location,
            })

            headers = {
                **_BROWSER_HEADERS,
                "Cookie": f"ghs_userLocation={quote(location_cookie)}",
                "Referer": "https://www.grubhub.com/search",
            }

            # restaurant_id might be a slug or numeric ID
            url = f"https://www.grubhub.com/restaurant/{restaurant_id}"

            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)

            if resp.status_code != 200:
                logger.warning(f"[Grubhub] Restaurant page returned {resp.status_code} for {restaurant_id}")
                return None

            html = resp.text
            restaurant_info, menu_items = _parse_menu_page(html)

            # Extract name from title as fallback
            if not restaurant_info.get("name"):
                title_match = re.search(r"<title>([^<]+)</title>", html)
                if title_match:
                    raw = title_match.group(1)
                    restaurant_info["name"] = raw.split("|")[0].split(" - ")[0].strip()

            now = datetime.now(timezone.utc).isoformat()
            return PlatformResult(
                platform=Platform.GRUBHUB,
                restaurant_name=restaurant_info.get("name") or f"Restaurant {restaurant_id}",
                restaurant_id=restaurant_id,
                restaurant_url=url,
                menu_items=menu_items,
                delivery_fee=restaurant_info.get("delivery_fee", 0.0),
                service_fee=restaurant_info.get("service_fee", 0.0),
                estimated_delivery_minutes=restaurant_info.get("eta", 35),
                minimum_order=restaurant_info.get("minimum_order"),
                rating=restaurant_info.get("rating"),
                rating_count=restaurant_info.get("rating_count"),
                promo_text=restaurant_info.get("promo"),
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[Grubhub] get_restaurant HTML failed: {e}")
            return None

    async def _get_restaurant_api(
        self, restaurant_id: str, token: str
    ) -> Optional[PlatformResult]:
        """Fetch restaurant details via API (requires valid bearer token)."""
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0 AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.grubhub.com/",
        }

        try:
            async with self._make_client(headers) as client:
                resp = await client.get(
                    RESTAURANT_URL_API.format(restaurant_id=restaurant_id),
                    params={"orderMethod": "delivery"},
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

            fee_obj = restaurant.get("delivery_fee") or {}
            delivery_fee = _cents_to_dollars(
                fee_obj.get("amount", 0) if isinstance(fee_obj, dict) else fee_obj
            )

            return PlatformResult(
                platform=Platform.GRUBHUB,
                restaurant_name=restaurant.get("name", ""),
                restaurant_id=restaurant_id,
                restaurant_url=f"https://www.grubhub.com/restaurant/{restaurant_id}",
                menu_items=menu_items,
                delivery_fee=delivery_fee,
                service_fee=0.0,
                estimated_delivery_minutes=int(
                    restaurant.get("estimated_delivery_time") or 35
                ),
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[Grubhub] API get_restaurant failed: {e}")
            return None
