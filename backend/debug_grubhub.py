"""Debug Grubhub fees."""
import asyncio
import json
import sys
sys.path.insert(0, ".")

import httpx
from app.services.grubhub import _get_token, _API_HEADERS, GH_SEARCH_API
from app.services.scraper_base import geocode


async def main():
    lat, lng = await geocode("New York, NY")
    token = await _get_token()
    print(f"Token: {token[:40]}...")

    headers = {**_API_HEADERS, "Authorization": f"Bearer {token}"}
    params = {
        "orderMethod": "delivery",
        "locationMode": "DELIVERY",
        "facetSet": "umaNew",
        "pageSize": 20,
        "hideHateos": "true",
        "queryText": "pizza",
        "latitude": lat,
        "longitude": lng,
    }

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(GH_SEARCH_API, params=params, headers=headers)
        data = resp.json()

    results = data.get("search_result", {}).get("results") or data.get("results") or []
    print(f"Total results: {len(results)}")

    for r in results[:3]:
        restaurant = r.get("restaurant") or r
        print(f"\n=== {restaurant.get('name')} ===")
        for key in ["delivery_fee", "service_fee", "delivery_minimum", "minimum_order_amount",
                    "delivery_time_estimate", "delivery_estimate", "ratings", "deals",
                    "fees", "price_response"]:
            v = restaurant.get(key)
            if v is not None:
                print(f"  {key}: {json.dumps(v) if isinstance(v, (dict, list)) else v}"[:500])
        # print top-level keys
        print(f"  keys: {list(restaurant.keys())[:30]}")


if __name__ == "__main__":
    asyncio.run(main())
