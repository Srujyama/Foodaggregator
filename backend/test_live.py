"""Live integration test.

Exercises each scraper individually across multiple real locations, then the
full aggregator pipeline (search -> normalize -> group -> menu-enrich -> compare).

Run from the backend/ directory:
    python3 test_live.py
or with secondary platforms:
    ENABLE_SECONDARY_PLATFORMS=1 python3 test_live.py
"""
import asyncio
import logging
import sys
import time

sys.path.insert(0, ".")

from app.services.doordash import DoorDashScraper
from app.services.grubhub import GrubhubScraper
from app.services.ubereats import UberEatsScraper
from app.services.postmates import PostmatesScraper
from app.services.caviar import CaviarScraper
from app.services.seamless import SeamlessScraper
from app.services.eatstreet import EatStreetScraper
from app.services.gopuff import GopuffScraper
from app.services.aggregator import AggregatorService

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


SCENARIOS = [
    ("taco bell", "19713", "taco bell"),
    ("pizza", "Berkeley, CA", "pizza"),
    ("chipotle", "10001", "chipotle"),
    ("mcdonalds", "94103", "mcdonald"),
    ("sushi", "New York, NY", "sushi"),
]


async def test_scrapers(query, location, scrapers):
    print(f"\n--- Raw scraper output: {query!r} in {location!r} ---")
    for name, scraper in scrapers.items():
        start = time.time()
        try:
            results = await asyncio.wait_for(
                scraper._safe_search(query, location), timeout=25.0
            )
        except asyncio.TimeoutError:
            print(f"  {name:10s}  TIMEOUT")
            continue
        except Exception as e:
            print(f"  {name:10s}  ERROR: {e}")
            continue
        elapsed = time.time() - start
        sample = ", ".join(r.restaurant_name[:30] for r in results[:2])
        print(
            f"  {name:10s}  {len(results):3d} results ({elapsed:4.1f}s)"
            f"{'  samples: ' + sample if sample else ''}"
        )


async def test_aggregator(query, location, expected_keyword):
    agg = AggregatorService()
    start = time.time()
    results = await agg.search(query, location, timeout=30.0)
    elapsed = time.time() - start

    plat_counts = {}
    multi = with_menu = with_comp = 0
    for r in results:
        for p in r.platforms:
            plat_counts[p.platform.value] = plat_counts.get(p.platform.value, 0) + 1
        if len(r.platforms) > 1:
            multi += 1
        if any(p.menu_items for p in r.platforms):
            with_menu += 1
        if r.menu_comparison:
            with_comp += 1

    print(f"\n=== Aggregator: {query!r} in {location!r} ({elapsed:.1f}s) ===")
    print(f"  total grouped: {len(results)}  per-platform: {plat_counts}")
    print(f"  multi-platform groups: {multi}, w/ menus: {with_menu}, w/ comparisons: {with_comp}")

    if expected_keyword:
        hit = next(
            (r for r in results if expected_keyword.lower() in r.restaurant_name.lower()),
            None,
        )
        if hit:
            platforms = ",".join(p.platform.value for p in hit.platforms)
            menu_total = sum(len(p.menu_items) for p in hit.platforms)
            print(f"  [PASS] {hit.restaurant_name}")
            print(f"         platforms=[{platforms}]  menu_items={menu_total}  comparisons={len(hit.menu_comparison)}")
            print(f"         avg markup %: {hit.avg_menu_markup_by_platform}")
            if hit.menu_comparison:
                c0 = hit.menu_comparison[0]
                prices = ", ".join(
                    f"{k}=${v:.2f}" for k, v in c0.prices.items() if v is not None
                )
                print(f"         sample item: {c0.item_name!r}: {prices}  cheapest={c0.cheapest_platform}")
        else:
            print(f"  [MISS] No {expected_keyword!r} found")

    for r in results[:3]:
        p = ",".join(pl.platform.value for pl in r.platforms)
        print(f"    - {r.restaurant_name[:50]:50s} [{p}]")


async def main():
    scrapers = {
        "doordash": DoorDashScraper(),
        "grubhub": GrubhubScraper(),
        "ubereats": UberEatsScraper(),
        "postmates": PostmatesScraper(),
        "caviar": CaviarScraper(),
        # Secondary / known-limited platforms:
        "seamless": SeamlessScraper(),
        "eatstreet": EatStreetScraper(),
        "gopuff": GopuffScraper(),
    }

    # First scenario: show raw per-platform output for diagnostics.
    q, l, _ = SCENARIOS[0]
    await test_scrapers(q, l, scrapers)

    # All scenarios: aggregator end-to-end.
    for q, l, expected in SCENARIOS:
        await test_aggregator(q, l, expected)


if __name__ == "__main__":
    asyncio.run(main())
