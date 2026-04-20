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
from app.services.caviar import CaviarScraper
from app.services.doordash import DoorDashScraper
from app.services.eatstreet import EatStreetScraper
from app.services.gopuff import GopuffScraper
from app.services.grubhub import GrubhubScraper
from app.services.postmates import PostmatesScraper
from app.services.seamless import SeamlessScraper
from app.services.ubereats import UberEatsScraper

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 78  # minimum score to consider same restaurant
MENU_ITEM_FUZZY_THRESHOLD = 82  # minimum score to consider same menu item


def _compute_total_cost(p: PlatformResult) -> float:
    return p.delivery_fee + p.service_fee


def _compute_pickup_cost(p: PlatformResult) -> float:
    return p.pickup_fee + p.pickup_service_fee


_NON_RESTAURANT_KEYWORDS = {
    # Convenience / gas
    "7-eleven", "7 eleven", "711", "speedway", "circle k", "chevron",
    "wawa", "sheetz", "cumberland farms", "rebel convenience",
    "farragut gas", "smoke stax", "quickstop", "convenience",
    # Drug / pharmacy
    "cvs", "walgreens", "rite aid", "duane reade", "pharmacy",
    # Pet
    "pet shop", "petsmart", "petco", "pet food express", "pet market",
    "pets square", "pet store", "pet supply", "dog food", "cat food",
    # Grocery / supermarket
    "grocery", "groceries", "grocer", "grocers",
    "supermarket", "deli & grocery", "grocery & beer",
    "beer & grocery", "fresh market", "farmers market", "fruit market",
    "grocery outlet", "foodsco", "foodtown", "food town", "smart & final",
    "costco", "restaurant depot", "chef'store", "chefstore",
    "sprouts farmers", "jetro cash", "price choice",
    "safeway", "wegmans", "trader joe", "whole foods", "citarella",
    "morton williams", "westside market", "save a lot", "pioneer supermarkets",
    "freshdirect", "fresh direct", "green valley", "cherry valley",
    "ajay grocery", "uber eats market", "liberty deli", "green fruit",
    "king fruit", "village farm", "big apple essential", "essential grocery",
    "best beer", "brooklyn grocery", "brooklyn grocers", "chestnut market",
    "atlantis (", "union market", "indian groceries", "ermina",
    "greenwood market", "east village beer", "pioneer supermarket",
    "international groceries", "sun liquor", "portofino wine",
    "green star foods", "fresh foods", "star foods",
    "gourmet market", "food mart", "foodmart",
    # Liquor / wine / beer
    "wine & liquor", "wine and liquor", "liquor", "beer shop",
    "wine shop", "spirits", "liquors", "wine & spirits", "grandview wine",
    "stop & go liquors", "nyc beer", "keg store", "central wine",
    "village wines", "liberty beer",
    # Dollar / hardware / general merchandise
    "dollar tree", "dollar general", "family dollar", "five below",
    "home depot", "lowes", "lowe's", "target", "walmart",
    "ace hardware", "michaels", "bed bath", "staples", "office depot",
    "best buy", "autozone", "super bros", "pacsun", "emilia george",
    "gopuff", "go puff",
    # Delis / corner stores masquerading as restaurants
    "gourmet deli", "deli and grocery", "corner deli", "farmers deli",
    "ice cream shop", "ice cream and dessert", "cut flowers",
    "canal smoke", "smoke gift", "smoke beer", "smoke convenience",
    "brbr", "supreme pizza and grocery", "beer and grocery",
    "island deli", "super buy-rite", "pool and spa", "flower",
    "grocers and fresh",
    # Smoke / vape shops
    "smoke shop", "vape shop", "cbd", "head shop",
    # Non-food
    "nail salon", "barber", "hair salon", "gas station",
    "housewares", "hardware", "flower shop", "florist",
    "bodega", "smoke & beer", "news stand", "newsstand",
    # National grocery / supermarket chains commonly on UE/Postmates
    "royal farms", "redner", "acme markets", "acme market",
    "giant food", "food lion", "stop & shop", "shoprite",
    "shop rite", "harris teeter", "publix", "kroger",
    "vons", "ralphs", "albertsons", "ralph's", "save mart",
    "food 4 less", "winn-dixie", "winn dixie", "hannaford",
    "weis markets", "ingles", "fresh thyme", "sprouts",
    "h mart", "h-mart", "99 ranch", "asia market",
    # Cinema / entertainment
    "cinemas", "regal cinemas", "amc theatres", "amc theatre",
    "movie theatre", "movie theater",
    # Flowers / gifts / tobacco
    "bouquet", "flower bar",
}


def _is_likely_non_restaurant(name: str) -> bool:
    """Filter out convenience stores, pet shops, groceries, etc."""
    lower = name.lower()
    return any(kw in lower for kw in _NON_RESTAURANT_KEYWORDS)


def _normalize_name(name: str) -> str:
    """Lowercase and strip common suffixes for better fuzzy matching.

    Strips parenthetical location suffixes like '(45 Catherine St)' and
    dash-separated location tags like '- Tribeca' that platforms add.
    """
    name = name.lower().strip()
    # Strip trademark symbols (Chipotle uses ®, McDonald's® etc.)
    name = re.sub(r"[®™©]", "", name)
    # Strip parenthetical address/location suffixes: "(45 Catherine St)", "(Downtown)"
    name = re.sub(r"\s*\([^)]*(?:st|ave|blvd|rd|dr|way|ln|ct|pl|pkwy|hwy|\d{3,})[^)]*\)$", "", name, flags=re.IGNORECASE)
    # Strip any trailing parenthetical (handles "(Eden Square SC.)" etc.)
    name = re.sub(r"\s*\([^)]{1,60}\)\s*$", "", name)
    # Strip trailing dash-location: "- Tribeca", "- Downtown", "- Hudson Yards"
    name = re.sub(r"\s*-\s*(?:downtown|midtown|uptown|soho|tribeca|fidi|chelsea|harlem|williamsburg|brooklyn|queens|bronx|astoria|bushwick|les|uws|ues|hudson yards|east village|west village|murray hill|flatiron|gramercy|hell'?s kitchen|nolita|noho|dumbo|cobble hill|park slope|prospect heights|crown heights|bed-stuy|greenpoint|sunset park|bay ridge|jackson heights|long island city|times square|union square|financial district|lower east side|upper west side|upper east side|newark|oakland|berkeley|manhattan)\s*$", "", name, flags=re.IGNORECASE)
    # Strip common brand qualifiers that differ between platforms
    for suffix in [
        r"\s*-\s*delivery$", r"\s*\(delivery\)$", r"\s*restaurant$",
        r"\s+mexican\s+grill$", r"\s+grill\s*&?\s*chill$",
        r"\s+grill$", r"\s+kitchen$", r"\s+express$",
        r"\s+pizza$",  # "Domino's Pizza" vs "Domino's"
        r"\s+bar\s*&\s*grill$", r"\s+bar\s+and\s+grill$",
    ]:
        name = re.sub(suffix, "", name)
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


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
    """Group PlatformResults by restaurant name using fuzzy matching.

    Only merges results from *different* platforms. If a group already contains
    a result from the same platform, treat the new result as a separate restaurant.
    """
    groups: dict[str, list[PlatformResult]] = {}
    group_keys: list[str] = []

    def _matches(a: str, b: str) -> bool:
        if not a or not b:
            return False
        if a == b:
            return True
        # Primary: token_sort_ratio threshold
        if fuzz.token_sort_ratio(a, b) >= FUZZY_THRESHOLD:
            return True
        # Secondary: token_set_ratio handles unordered and missing tokens
        # (e.g. "chipotle" vs "chipotle mexican"), but gate on a strong
        # partial_ratio so we don't merge "pizza" with "taco bell pizza".
        if (
            fuzz.token_set_ratio(a, b) >= 92
            and fuzz.partial_ratio(a, b) >= 88
        ):
            return True
        # Tertiary: one name is a strict prefix of the other AND the shorter
        # one is at least 5 chars (avoid 'joe' merging into 'joe's pizza').
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        if len(shorter) >= 5 and (
            longer.startswith(shorter + " ") or longer.endswith(" " + shorter)
        ):
            return True
        return False

    for result in all_results:
        norm = _normalize_name(result.restaurant_name)
        matched_key = None

        for key in group_keys:
            if _matches(norm, key):
                # Don't merge if group already has a result from this platform
                existing_platforms = {r.platform for r in groups[key]}
                if result.platform in existing_platforms:
                    continue
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
        # Core platforms: actively maintained integrations.
        # Secondary integrations (Seamless/EatStreet/GoPuff) are disabled by
        # default because (a) Seamless shares its entire backend with Grubhub
        # so duplicating it adds noise without value, (b) EatStreet requires
        # client-side auth we can't replicate from a backend, and (c) GoPuff
        # is essentials-delivery (pharmacy/convenience) which we filter out.
        # Set ENABLE_SECONDARY_PLATFORMS=1 to include them.
        import os
        self.scrapers = {
            Platform.UBER_EATS: UberEatsScraper(),
            Platform.DOORDASH: DoorDashScraper(),
            Platform.GRUBHUB: GrubhubScraper(),
            Platform.POSTMATES: PostmatesScraper(),
            Platform.CAVIAR: CaviarScraper(),
        }
        if os.environ.get("ENABLE_SECONDARY_PLATFORMS"):
            self.scrapers[Platform.SEAMLESS] = SeamlessScraper()
            self.scrapers[Platform.EATSTREET] = EatStreetScraper()
            self.scrapers[Platform.GOPUFF] = GopuffScraper()

    async def search(
        self, query: str, location: str, timeout: float = 20.0
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

        all_results = [
            r for results in results_by_platform.values() for r in results
            if not _is_likely_non_restaurant(r.restaurant_name)
        ]

        if not all_results:
            return []

        groups = _fuzzy_group(all_results)

        aggregated = [
            _build_aggregated(query, location, group)
            for group in groups.values()
            if group
        ]

        # Rank: prefer (a) results matching the query, (b) more platforms,
        # (c) lower fees. Pure fee-sort buries actual query matches behind
        # unrelated $0-delivery-fee groceries.
        query_tokens = {t for t in _normalize_name(query).split() if len(t) >= 3}

        def _match_score(a: AggregatedResult) -> int:
            norm = _normalize_name(a.restaurant_name)
            if not query_tokens:
                return 0
            hits = sum(1 for t in query_tokens if t in norm)
            return hits

        aggregated.sort(
            key=lambda a: (
                -_match_score(a),              # query-matching first
                -len(a.platforms),             # more platforms = higher confidence
                min(_compute_total_cost(p) for p in a.platforms),
            )
        )

        # Enrich top results with menu data (parallel, best-effort)
        ENRICH_TOP_N = 25
        await self._enrich_menus(aggregated[:ENRICH_TOP_N], location)

        # Menus were empty when _build_aggregated first ran, so the cross-platform
        # price comparison was empty. Rebuild it now that menus are populated.
        for agg_result in aggregated[:ENRICH_TOP_N]:
            agg_result.menu_comparison = _build_menu_comparison(agg_result.platforms)
            agg_result.avg_menu_markup_by_platform = _compute_avg_markup(
                agg_result.platforms, agg_result.menu_comparison
            )

        return aggregated

    async def _enrich_menus(
        self, results: list[AggregatedResult], location: str
    ) -> None:
        """Fetch menu items for the top search results in parallel."""
        menu_tasks = []
        task_info = []  # (result_idx, platform_idx)

        for r_idx, result in enumerate(results):
            for p_idx, platform_result in enumerate(result.platforms):
                if platform_result.menu_items:
                    continue  # Already has menu
                scraper = self.scrapers.get(platform_result.platform)
                if scraper:
                    menu_tasks.append(
                        asyncio.create_task(
                            asyncio.wait_for(
                                scraper.get_restaurant(
                                    platform_result.restaurant_id, location
                                ),
                                timeout=10.0,
                            )
                        )
                    )
                    task_info.append((r_idx, p_idx))

        if not menu_tasks:
            return

        done = await asyncio.gather(*menu_tasks, return_exceptions=True)

        for (r_idx, p_idx), detail in zip(task_info, done):
            if isinstance(detail, Exception) or detail is None:
                continue
            if detail.menu_items:
                results[r_idx].platforms[p_idx].menu_items = detail.menu_items
                # Also update fees if the detail has better data
                if detail.delivery_fee > 0:
                    results[r_idx].platforms[p_idx].delivery_fee = detail.delivery_fee
                if detail.service_fee > 0:
                    results[r_idx].platforms[p_idx].service_fee = detail.service_fee

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
