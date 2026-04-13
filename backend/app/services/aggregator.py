import asyncio
import logging
import re
from typing import Optional

from rapidfuzz import fuzz

from app.models.food import (
    AggregatedResult,
    MenuItemComparison,
    Platform,
    PlatformResult,
)
from app.services.doordash import DoorDashScraper
from app.services.grubhub import GrubhubScraper
from app.services.ubereats import UberEatsScraper

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 78  # minimum score to consider same restaurant
MENU_ITEM_FUZZY_THRESHOLD = 82  # minimum score to consider same menu item


def _compute_total_cost(p: PlatformResult) -> float:
    return p.delivery_fee + p.service_fee


def _compute_pickup_cost(p: PlatformResult) -> float:
    return p.pickup_fee + p.pickup_service_fee


def _normalize_name(name: str) -> str:
    """Lowercase and strip common suffixes for better fuzzy matching."""
    name = name.lower().strip()
    for suffix in [
        r"\s*-\s*delivery$", r"\s*\(delivery\)$", r"\s*restaurant$",
        r"\s*grill$", r"\s*kitchen$", r"\s*express$",
    ]:
        name = re.sub(suffix, "", name)
    name = re.sub(r"[^\w\s]", "", name)
    return name.strip()


def _normalize_menu_item_name(name: str) -> str:
    """Normalize a menu item name for fuzzy matching across platforms."""
    name = name.lower().strip()
    # Remove common size/variant suffixes
    for pattern in [
        r"\s*\(.*?\)$",        # (Small), (Large)
        r"\s*-\s*\w+$",        # "- Small"
        r"\s*\d+\s*(?:pc|piece|oz|inch|in)\.?$",  # "10 pc", "16 oz"
    ]:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^\w\s]", "", name)
    return name.strip()


def _fuzzy_group(all_results: list[PlatformResult]) -> dict[str, list[PlatformResult]]:
    """Group PlatformResults by restaurant name using fuzzy matching."""
    groups: dict[str, list[PlatformResult]] = {}
    group_keys: list[str] = []

    for result in all_results:
        norm = _normalize_name(result.restaurant_name)
        matched_key = None

        for key in group_keys:
            score = fuzz.token_sort_ratio(norm, key)
            if score >= FUZZY_THRESHOLD:
                matched_key = key
                break

        if matched_key is None:
            matched_key = norm
            group_keys.append(norm)
            groups[matched_key] = []

        groups[matched_key].append(result)

    return groups


def _build_menu_comparison(platforms: list[PlatformResult]) -> list[MenuItemComparison]:
    """Build a cross-platform menu item price comparison.

    Uses fuzzy matching to find the same menu item across different platforms,
    then compares their prices side-by-side.
    """
    # Collect all menu items grouped by normalized name
    # Key: normalized name, Value: {platform: (original_name, price)}
    item_groups: dict[str, dict[str, tuple[str, float]]] = {}
    group_keys: list[str] = []

    for platform_result in platforms:
        platform_name = platform_result.platform.value
        for menu_item in platform_result.menu_items:
            norm = _normalize_menu_item_name(menu_item.name)
            if not norm or len(norm) < 2:
                continue

            matched_key = None
            for key in group_keys:
                score = fuzz.token_sort_ratio(norm, key)
                if score >= MENU_ITEM_FUZZY_THRESHOLD:
                    matched_key = key
                    break

            if matched_key is None:
                matched_key = norm
                group_keys.append(norm)
                item_groups[matched_key] = {}

            # Don't overwrite if already present for this platform
            if platform_name not in item_groups[matched_key]:
                item_groups[matched_key][platform_name] = (menu_item.name, menu_item.price)

    # Build comparisons - only include items that appear on 2+ platforms
    comparisons = []
    all_platforms = [p.platform.value for p in platforms]

    for _norm_name, platform_prices in item_groups.items():
        if len(platform_prices) < 2:
            continue

        # Use the longest name as the canonical name
        canonical_name = max(
            platform_prices.values(), key=lambda x: len(x[0])
        )[0]

        prices: dict[str, Optional[float]] = {}
        for platform in all_platforms:
            if platform in platform_prices:
                prices[platform] = platform_prices[platform][1]
            else:
                prices[platform] = None

        # Find cheapest and price difference
        available_prices = {k: v for k, v in prices.items() if v is not None}
        if not available_prices:
            continue

        cheapest = min(available_prices, key=available_prices.get)
        price_vals = list(available_prices.values())
        diff = round(max(price_vals) - min(price_vals), 2)

        comparisons.append(MenuItemComparison(
            item_name=canonical_name,
            prices=prices,
            cheapest_platform=cheapest,
            price_difference=diff,
        ))

    # Sort by price difference descending (biggest savings first)
    comparisons.sort(key=lambda c: c.price_difference, reverse=True)
    return comparisons


def _compute_avg_markup(
    platforms: list[PlatformResult],
    menu_comparison: list[MenuItemComparison],
) -> dict[str, float]:
    """Compute average menu price markup percentage for each platform.

    For each platform, compute how much more/less expensive its items are
    compared to the cheapest price available for each item.
    Returns {platform: avg_markup_percentage} where 0 = cheapest, positive = more expensive.
    """
    all_platform_names = [p.platform.value for p in platforms]
    platform_markups: dict[str, list[float]] = {p: [] for p in all_platform_names}

    for comp in menu_comparison:
        available = {k: v for k, v in comp.prices.items() if v is not None}
        if not available:
            continue
        min_price = min(available.values())
        if min_price <= 0:
            continue

        for platform, price in available.items():
            markup_pct = round(((price - min_price) / min_price) * 100, 1)
            platform_markups[platform].append(markup_pct)

    result = {}
    for platform, markups in platform_markups.items():
        if markups:
            result[platform] = round(sum(markups) / len(markups), 1)
        else:
            result[platform] = 0.0

    return result


def _build_aggregated(query: str, location: str, group: list[PlatformResult]) -> AggregatedResult:
    """Build an AggregatedResult from a group of platform results for the same restaurant."""
    canonical_name = max(group, key=lambda p: len(p.restaurant_name)).restaurant_name

    total_cost_by_platform = {
        p.platform.value: round(_compute_total_cost(p), 2)
        for p in group
    }

    pickup_cost_by_platform = {
        p.platform.value: round(_compute_pickup_cost(p), 2)
        for p in group
        if p.pickup_available
    }

    best_platform = min(group, key=_compute_total_cost)

    # Build menu comparison if any platform has menu items
    menu_comparison = _build_menu_comparison(group)
    avg_markup = _compute_avg_markup(group, menu_comparison)

    return AggregatedResult(
        query=query,
        location=location,
        restaurant_name=canonical_name,
        platforms=group,
        best_deal_platform=best_platform.platform,
        total_cost_by_platform=total_cost_by_platform,
        pickup_cost_by_platform=pickup_cost_by_platform,
        menu_comparison=menu_comparison,
        avg_menu_markup_by_platform=avg_markup,
    )


class AggregatorService:
    def __init__(self):
        self.scrapers = {
            Platform.UBER_EATS: UberEatsScraper(),
            Platform.DOORDASH: DoorDashScraper(),
            Platform.GRUBHUB: GrubhubScraper(),
        }

    async def search(
        self, query: str, location: str, timeout: float = 8.0
    ) -> list[AggregatedResult]:
        """Fan out to all scrapers concurrently, merge results, rank by best deal."""
        tasks = {
            platform: asyncio.create_task(
                asyncio.wait_for(scraper._safe_search(query, location), timeout=timeout)
            )
            for platform, scraper in self.scrapers.items()
        }

        results_by_platform: dict[Platform, list[PlatformResult]] = {}
        for platform, task in tasks.items():
            try:
                results_by_platform[platform] = await task
            except asyncio.TimeoutError:
                logger.warning(f"[Aggregator] {platform.value} timed out")
                results_by_platform[platform] = []
            except Exception as e:
                logger.warning(f"[Aggregator] {platform.value} failed: {e}")
                results_by_platform[platform] = []

        all_results = [r for results in results_by_platform.values() for r in results]

        if not all_results:
            return []

        groups = _fuzzy_group(all_results)

        aggregated = [
            _build_aggregated(query, location, group)
            for group in groups.values()
            if group
        ]

        # Sort by best deal (lowest total fees) across all platforms
        aggregated.sort(
            key=lambda a: min(_compute_total_cost(p) for p in a.platforms)
        )

        return aggregated

    async def get_restaurant(self, name: str, location: str) -> Optional[AggregatedResult]:
        """Get detailed data for a specific restaurant across all platforms.

        1. Search to find the restaurant on each platform
        2. Fetch detailed data (menu items, fees) for each platform
        3. Build cross-platform price comparison
        """
        # First do a search to find the restaurant IDs
        search_results = await self.search(name, location)
        if not search_results:
            return None

        # Find the best match
        target = search_results[0]

        # Fetch detailed data for each platform result (with menu items)
        detail_tasks = []
        for platform_result in target.platforms:
            scraper = self.scrapers.get(platform_result.platform)
            if scraper:
                detail_tasks.append(
                    asyncio.create_task(
                        asyncio.wait_for(
                            scraper.get_restaurant(platform_result.restaurant_id, location),
                            timeout=12.0,
                        )
                    )
                )

        detailed_platforms = []
        for task in detail_tasks:
            try:
                result = await task
                if result:
                    detailed_platforms.append(result)
            except Exception as e:
                logger.warning(f"[Aggregator] Detail fetch failed: {e}")

        if not detailed_platforms:
            return target  # Return summary if detail fetch fails

        return _build_aggregated(name, location, detailed_platforms)

    async def get_deals(self, location: str, limit: int = 10) -> list[AggregatedResult]:
        """Get top deals (zero delivery fee, promos) near a location."""
        all_results = await self.search("restaurant", location, timeout=10.0)

        # Filter to restaurants with promotions or free delivery
        deals = [r for r in all_results if any(
            p.delivery_fee == 0 or p.promo_text for p in r.platforms
        )]

        if not deals:
            deals = all_results

        deals.sort(key=lambda a: min(_compute_total_cost(p) for p in a.platforms))
        return deals[:limit]

    async def get_scraper_health(self) -> dict:
        """Check which scrapers are reachable."""
        health = {}
        for platform, scraper in self.scrapers.items():
            try:
                results = await asyncio.wait_for(
                    scraper._safe_search("test", "New York, NY"), timeout=5.0
                )
                health[platform.value] = "ok" if results else "degraded"
            except Exception:
                health[platform.value] = "down"
        return health
