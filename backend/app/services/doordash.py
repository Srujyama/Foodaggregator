"""
DoorDash scraper - Updated March 2026.

DoorDash API landscape:
- consumer-api.doordash.com: DNS no longer resolves (dead).
- www.doordash.com/graphql storeSearchV2: requires an authenticated consumer
  address set via addConsumerAddressV3 with a valid Google Place ID. Without
  a valid Google Place ID the address mutation fails, and storeSearchV2 then
  returns "Search service: /v1/store_feed API error 404".
- The StoreV2 GQL type exposes only: id, name, coverImgUrl, priceRange,
  businessId (March 2026 schema - rating/fee/ETA fields removed).
- Both unauthenticated REST and GQL search return errors without full auth.

Strategy: Attempt GQL storeSearchV2 with Nominatim-derived address. Gracefully
returns [] with clear logging when blocked. Results will be empty until a
full consumer auth flow (including Google Place ID) is implemented.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.models.food import MenuItem, Platform, PlatformResult
from app.services.scraper_base import BaseScraper, geocode

logger = logging.getLogger(__name__)

DD_HOME = "https://www.doordash.com"
DD_GQL = "https://www.doordash.com/graphql"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",  # omit br (brotli) - not supported by httpx by default
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}

# Reverse geocode cache to avoid hammering Nominatim
_geo_address_cache: dict = {}


async def _reverse_geocode(lat: float, lng: float) -> dict:
    """Get address components from lat/lng using Nominatim reverse geocode."""
    key = (round(lat, 3), round(lng, 3))
    if key in _geo_address_cache:
        return _geo_address_cache[key]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lng, "format": "json", "addressdetails": 1},
                headers={"User-Agent": "FoodAggregator/1.0 (contact@foodaggregator.app)"},
            )
            resp.raise_for_status()
            data = resp.json()
            addr = data.get("address", {})
            result = {
                "city": addr.get("city") or addr.get("town") or addr.get("suburb") or "",
                "state": _abbreviate_state(addr.get("state") or ""),
                "zip": addr.get("postcode") or "",
                "street": _build_street(addr),
                "display": data.get("display_name", "")[:100],
            }
            _geo_address_cache[key] = result
            return result
    except Exception as e:
        logger.debug(f"[DoorDash] Reverse geocode failed: {e}")
        return {"city": "", "state": "", "zip": "", "street": "", "display": ""}


def _abbreviate_state(state: str) -> str:
    _MAP = {
        "New York": "NY", "California": "CA", "Texas": "TX", "Florida": "FL",
        "Illinois": "IL", "Pennsylvania": "PA", "Ohio": "OH", "Georgia": "GA",
        "North Carolina": "NC", "Michigan": "MI", "Washington": "WA",
        "Massachusetts": "MA", "New Jersey": "NJ", "Virginia": "VA",
        "Arizona": "AZ", "Colorado": "CO", "Tennessee": "TN", "Indiana": "IN",
        "Missouri": "MO", "Maryland": "MD", "Minnesota": "MN", "Wisconsin": "WI",
        "Connecticut": "CT", "Nevada": "NV", "Oregon": "OR", "Louisiana": "LA",
    }
    if len(state) == 2:
        return state.upper()
    return _MAP.get(state, state[:2].upper())


def _build_street(addr: dict) -> str:
    house = addr.get("house_number") or ""
    road = addr.get("road") or addr.get("street") or ""
    return f"{house} {road}".strip() if house else road


class DoorDashScraper(BaseScraper):
    PLATFORM_NAME = "doordash"

    async def search(self, query: str, location: str) -> list[PlatformResult]:
        lat, lng = await geocode(location)
        addr_info = await _reverse_geocode(lat, lng)

        try:
            async with httpx.AsyncClient(
                headers={**_BROWSER_HEADERS, "Accept": "text/html,application/xhtml+xml,*/*"},
                timeout=10.0,
                follow_redirects=True,
            ) as client:
                # Acquire session cookies from the homepage
                await client.get(DD_HOME)
                gql_headers = {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Referer": "https://www.doordash.com/",
                    "x-channel-id": "web",
                    "x-experience-id": "doordash",
                }

                # Step 1: Set delivery address (required for storeSearchV2)
                await self._set_address(client, lat, lng, addr_info, gql_headers)

                # Step 2: Search for stores
                results = await self._search_stores(client, query, lat, lng, gql_headers)
                logger.info(f"[DoorDash] {len(results)} results for '{query}'")
                return results

        except Exception as e:
            logger.warning(f"[DoorDash] Search failed: {e}")
            return []

    async def _set_address(
        self,
        client: httpx.AsyncClient,
        lat: float,
        lng: float,
        addr: dict,
        headers: dict,
    ) -> None:
        """Attempt to set delivery address in the DoorDash session."""
        city = addr.get("city") or "New York"
        state = addr.get("state") or "NY"
        zipcode = addr.get("zip") or "10001"
        street = addr.get("street") or city
        printable = f"{street}, {city}, {state} {zipcode}"

        mutation = """mutation AddAddress(
          $lat: Float!, $lng: Float!,
          $city: String!, $state: String!, $zipCode: String!,
          $printableAddress: String!, $shortname: String!, $googlePlaceId: String!
        ) {
          addConsumerAddressV3(
            lat: $lat, lng: $lng,
            city: $city, state: $state, zipCode: $zipCode,
            printableAddress: $printableAddress, shortname: $shortname,
            googlePlaceId: $googlePlaceId
          ) { id lat lng }
        }"""

        variables = {
            "lat": lat,
            "lng": lng,
            "city": city,
            "state": state,
            "zipCode": zipcode,
            "printableAddress": printable,
            "shortname": street or city,
            "googlePlaceId": "",
        }

        try:
            resp = await client.post(DD_GQL, json={"query": mutation, "variables": variables}, headers=headers)
            data = resp.json()
            if data.get("data", {}).get("addConsumerAddressV3"):
                logger.debug(f"[DoorDash] Address set for ({lat}, {lng})")
            else:
                logger.debug(f"[DoorDash] Address set failed (expected without Google Place ID)")
        except Exception as e:
            logger.debug(f"[DoorDash] Address set exception: {e}")

    async def _search_stores(
        self,
        client: httpx.AsyncClient,
        query: str,
        lat: float,
        lng: float,
        headers: dict,
    ) -> list[PlatformResult]:
        """Search for stores using storeSearchV2 GQL.

        Note: storeSearchV2 requires a consumer address set via addConsumerAddressV3
        with a valid Google Place ID. Without full auth it returns a 404 from the
        upstream store_feed service. The StoreV2 type exposes only limited fields:
        id, name, coverImgUrl, priceRange, businessId (March 2026 schema).
        """
        gql = """query SearchStores($offset: Int!, $limit: Int!) {
          storeSearchV2(offset: $offset, limit: $limit) {
            numStores
            results {
              id
              name
              coverImgUrl
              priceRange
              businessId
            }
          }
        }"""

        try:
            resp = await client.post(
                DD_GQL,
                json={"query": gql, "variables": {"offset": 0, "limit": 20}},
                headers=headers,
            )
            data = resp.json()

            sv2 = (data.get("data") or {}).get("storeSearchV2")
            if not sv2 or not sv2.get("results"):
                if data.get("errors"):
                    err_msg = data["errors"][0].get("message", "")
                    logger.warning(f"[DoorDash] storeSearchV2 error: {err_msg}")
                return []

            return self._parse_stores(sv2.get("results", []))

        except Exception as e:
            logger.warning(f"[DoorDash] storeSearchV2 failed: {e}")
            return []

    def _parse_stores(self, stores: list) -> list[PlatformResult]:
        results = []
        now = datetime.now(timezone.utc).isoformat()

        for store in stores:
            try:
                store_id = str(store.get("id") or "")
                name = store.get("name") or ""
                if not name or not store_id:
                    continue

                url = f"https://www.doordash.com/store/{store_id}/"

                results.append(PlatformResult(
                    platform=Platform.DOORDASH,
                    restaurant_name=name,
                    restaurant_id=store_id,
                    restaurant_url=url,
                    delivery_fee=0.0,
                    service_fee=0.0,
                    estimated_delivery_minutes=30,
                    rating=None,
                    rating_count=None,
                    promo_text=None,
                    fetched_at=now,
                ))
            except Exception as e:
                logger.debug(f"[DoorDash] Parse error: {e}")
                continue

        return results

    async def get_restaurant(self, restaurant_id: str, location: str) -> Optional[PlatformResult]:
        """Fetch individual restaurant details."""
        try:
            gql = """query GetStore($storeId: ID!) {
              store(id: $storeId) {
                id
                name
                averageRating
                numRatings
                deliveryTime { startTime endTime }
                deliveryFeeDetails { unitAmount displayString }
                menus { menuCategories { name items { id name description price imgUrl } } }
              }
            }"""

            async with httpx.AsyncClient(
                headers={**_BROWSER_HEADERS, "Accept": "text/html,*/*"},
                timeout=10.0,
                follow_redirects=True,
            ) as client:
                await client.get(DD_HOME)
                gql_headers = {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Referer": "https://www.doordash.com/",
                    "x-channel-id": "web",
                    "x-experience-id": "doordash",
                }
                resp = await client.post(
                    DD_GQL,
                    json={"query": gql, "variables": {"storeId": restaurant_id}},
                    headers=gql_headers,
                )
                data = resp.json()

            store = (data.get("data") or {}).get("store")
            if not store:
                return None

            now = datetime.now(timezone.utc).isoformat()
            menu_items = []
            for menu in (store.get("menus") or []):
                for cat in (menu.get("menuCategories") or []):
                    for item in (cat.get("items") or [])[:30]:
                        try:
                            menu_items.append(MenuItem(
                                name=item.get("name", ""),
                                description=item.get("description"),
                                price=_cents_to_dollars(item.get("price") or 0),
                                image_url=item.get("imgUrl"),
                            ))
                        except Exception:
                            continue

            fee_details = store.get("deliveryFeeDetails") or {}
            delivery_fee = _cents_to_dollars(fee_details.get("unitAmount") or 0)
            delivery_time = store.get("deliveryTime") or {}

            return PlatformResult(
                platform=Platform.DOORDASH,
                restaurant_name=store.get("name", ""),
                restaurant_id=restaurant_id,
                restaurant_url=f"https://www.doordash.com/store/{restaurant_id}/",
                menu_items=menu_items,
                delivery_fee=delivery_fee,
                service_fee=0.0,
                estimated_delivery_minutes=int(delivery_time.get("startTime") or 30),
                rating=float(store.get("averageRating") or 0) or None,
                rating_count=int(store.get("numRatings") or 0) or None,
                fetched_at=now,
            )
        except Exception as e:
            logger.warning(f"[DoorDash] get_restaurant failed: {e}")
            return None


def _cents_to_dollars(value) -> float:
    if value is None:
        return 0.0
    try:
        v = float(value)
        return round(v, 2) if abs(v) < 50 else round(v / 100, 2)
    except (ValueError, TypeError):
        return 0.0
