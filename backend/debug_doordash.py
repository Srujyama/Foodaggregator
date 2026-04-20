"""Check DoorDash store detail page for fee info."""
import asyncio
import re
import sys
sys.path.insert(0, ".")

from curl_cffi import requests as cffi_requests
from app.services.doordash import _extract_rsc_text


async def main():
    # Use one of the store IDs we know works (from previous search)
    store_id = "1780044"  # Taco Bell from SJ

    def _go():
        return cffi_requests.get(
            f"https://www.doordash.com/store/{store_id}/",
            impersonate="chrome",
            timeout=20,
            allow_redirects=True,
        )
    resp = await asyncio.to_thread(_go)
    print(f"status={resp.status_code} len={len(resp.text)}")

    full = _extract_rsc_text(resp.text)
    print(f"RSC len={len(full)}")

    # Look for fee fields on the detail page
    for pat_name, pat in [
        ("delivery_fee", r'"delivery_fee":[^,}]{1,80}'),
        ("delivery_fee_monetary", r'"delivery_fee_monetary_fields":\{[^}]{0,400}'),
        ("service_fee", r'"service_fee":[^,}]{1,80}'),
        ("service_fee_monetary", r'"service_fee_monetary_fields":\{[^}]{0,400}'),
        ("delivery_fee_tooltip", r'"delivery_fee_tooltip":"[^"]{1,200}"'),
        ("asap_time", r'"asap_time":\d+'),
        ("header_text", r'"header_text":"[^"]{1,120}"'),
        ("fee_text", r'\$[\d.]+ [Dd]elivery [Ff]ee'),
        ("free_text", r'[Ff]ree [Dd]elivery'),
    ]:
        matches = re.findall(pat, full)
        if matches:
            unique = list(set(matches[:10]))[:5]
            print(f"\n{pat_name} ({len(matches)}):")
            for m in unique:
                print(f"  {m!r}")

    # Find menu items count
    menu_items = re.findall(r'StorePageCarouselItem","id":"(\d+)","name":"([^"]+)"', full)
    print(f"\nMenu items: {len(menu_items)}")
    for iid, name in menu_items[:3]:
        print(f"  {iid}: {name}")

if __name__ == "__main__":
    asyncio.run(main())
