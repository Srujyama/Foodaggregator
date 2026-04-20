"""Try various UberEats query variants to find a working restaurant search."""
import asyncio
import json
import sys
sys.path.insert(0, ".")

from app.services.ubereats import _get_session_cookies, _build_cookie_str, _BROWSER_HEADERS, FEED_URL
from app.services.scraper_base import geocode
import httpx

async def probe(client, headers, payload, label):
    resp = await client.post(FEED_URL, json=payload)
    try:
        data = resp.json()
    except Exception:
        print(f"{label}: status={resp.status_code} (not json)")
        return
    items = data.get("data", {}).get("feedItems") or []
    restaurants = []
    groceries = 0
    pickup = 0
    for it in items:
        s = it.get("store") or {}
        url = s.get("actionUrl") or ""
        title = s.get("title", {}).get("text") if isinstance(s.get("title"), dict) else s.get("title")
        lower = (title or "").lower()
        if "diningMode=PICKUP" in url:
            pickup += 1
            continue
        if any(kw in lower for kw in ["grocery", "pharmacy", "liquor", "pet", "wine", "beer", "convenience", "speedway", "7-eleven", "market", "deli", "cvs", "walgreens", "petco", "pacsun", "hardware", "ace hardware"]):
            groceries += 1
            continue
        restaurants.append(title)
    print(f"{label}: total={len(items)} pickup={pickup} groceries={groceries} restaurants={len(restaurants)}")
    for r in restaurants[:6]:
        print(f"    {r}")


async def main():
    lat, lng = await geocode("New York, NY")
    session_cookies = await _get_session_cookies()
    cookie_str = _build_cookie_str(session_cookies, lat, lng, "New York, NY")
    headers = {
        **_BROWSER_HEADERS,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "x-csrf-token": "x",
        "Referer": "https://www.ubereats.com/feed?diningMode=DELIVERY",
        "Origin": "https://www.ubereats.com",
        "Cookie": cookie_str,
    }
    base = {"pageInfo": {"offset": 0, "pageSize": 80}, "targetLocation": {"latitude": lat, "longitude": lng}}

    async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
        for q in ["pizza", "Domino's Pizza", "pizza restaurant", "italian pizza"]:
            payload = {**base, "userQuery": q, "diningMode": "DELIVERY"}
            await probe(client, headers, payload, f"q={q!r} DELIVERY")
        print()
        # Try with storeType=restaurants
        payload = {**base, "userQuery": "pizza", "diningMode": "DELIVERY", "storeFilters": {"cuisines": ["pizza"]}}
        await probe(client, headers, payload, "pizza + storeFilters.cuisines=pizza")

        # Try offset 10
        payload = {**base, "userQuery": "pizza", "diningMode": "DELIVERY", "pageInfo": {"offset": 20, "pageSize": 80}}
        await probe(client, headers, payload, "pizza offset=20")


if __name__ == "__main__":
    asyncio.run(main())
