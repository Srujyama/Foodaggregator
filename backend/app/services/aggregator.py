import asyncio
import logging
import re
from typing import Optional

from rapidfuzz import fuzz

from app.models.food import AggregatedResult, Platform, PlatformResult
from app.services.doordash import DoorDashScraper
from app.services.grubhub import GrubhubScraper
from app.services.ubereats import UberEatsScraper

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 78  # minimum score to consider same restaurant


def _compute_total_cost(p: PlatformResult) -> float:
    return p.delivery_fee + p.service_fee


def _normalize_name(name: str) -> str:
    """Lowercase and strip common suffixes for better fuzzy matching."""
    name = name.lower().strip()
    # Remove common suffixes
    for suffix in [
        r"\s*-\s*delivery$", r"\s*\(delivery\)$", r"\s*restaurant$",
        r"\s*grill$", r"\s*kitchen$", r"\s*express$",
    ]:
        name = re.sub(suffix, "", name)
    # Remove non-alphanumeric except spaces
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


def _build_aggregated(query: str, location: str, group: list[PlatformResult]) -> AggregatedResult:
    """Build an AggregatedResult from a group of platform results for the same restaurant."""
    # Use the most common/longest name as the canonical name
    canonical_name = max(group, key=lambda p: len(p.restaurant_name)).restaurant_name

    total_cost_by_platform = {
        p.platform.value: round(_compute_total_cost(p), 2)
        for p in group
    }

    # Best deal = platform with lowest total fees
    best_platform = min(group, key=_compute_total_cost)

    return AggregatedResult(
        query=query,
        location=location,
        restaurant_name=canonical_name,
        platforms=group,
        best_deal_platform=best_platform.platform,
        total_cost_by_platform=total_cost_by_platform,
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
        """Get detailed data for a specific restaurant across all platforms."""
        # First do a search to find the restaurant IDs
        search_results = await self.search(name, location)
        if not search_results:
            return None

        # Find the best match
        target = search_results[0]

        # Fetch detailed data for each platform result
        detail_tasks = []
        for platform_result in target.platforms:
            scraper = self.scrapers.get(platform_result.platform)
            if scraper:
                detail_tasks.append(
                    asyncio.create_task(
                        asyncio.wait_for(
                            scraper.get_restaurant(platform_result.restaurant_id, location),
                            timeout=8.0,
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
        # Search with a broad query to get a feed
        all_results = await self.search("restaurant", location, timeout=10.0)

        # Filter and sort by best deals
        deals = [r for r in all_results if any(
            p.delivery_fee == 0 or p.promo_text for p in r.platforms
        )]

        # If no promos found, just return sorted by lowest fees
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
