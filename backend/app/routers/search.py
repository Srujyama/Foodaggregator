from fastapi import APIRouter, Query
from app.models.food import SearchResponse
from app.services.aggregator import AggregatorService
from app.services.cache import (
    _make_key,
    coalesce,
    get_cached,
    set_cached,
    track_popular_search,
)
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
_aggregator = AggregatorService()


def _apply_platform_filter(results, platforms: str | None):
    if not platforms:
        return results
    allowed = {p.strip() for p in platforms.split(",") if p.strip()}
    if not allowed:
        return results
    filtered = []
    for r in results:
        kept = [p for p in r.platforms if (p.platform.value if hasattr(p.platform, "value") else p.platform) in allowed]
        if kept:
            r.platforms = kept
            filtered.append(r)
    return filtered


@router.get("/search", response_model=SearchResponse)
async def search_restaurants(
    q: str = Query(..., min_length=1, description="Search query (restaurant name or dish)"),
    location: str = Query(..., min_length=1, description="Location (city, ZIP, or address)"),
    limit: int = Query(100, ge=1, le=200),
    platforms: str = Query(None, description="Comma-separated platform filter"),
    mode: str = Query("delivery", description="Order mode: delivery or pickup"),
):
    mode = (mode or "delivery").lower()
    if mode not in ("delivery", "pickup"):
        mode = "delivery"

    cached = await get_cached(q, location, mode)
    if cached:
        from app.models.food import AggregatedResult
        # New cache entries are {"results": [...], "platform_status": {...}};
        # legacy Firestore entries are a bare list of result dicts.
        if isinstance(cached, dict):
            raw_results = cached.get("results", [])
            platform_status = cached.get("platform_status", {})
        else:
            raw_results = cached
            platform_status = {}
        results = [AggregatedResult(**r) for r in raw_results]
        results = _apply_platform_filter(results, platforms)
        return SearchResponse(
            query=q,
            location=location,
            results=results[:limit],
            total=len(results),
            cached=True,
            platform_status=platform_status,
        )

    # Coalesce concurrent identical searches into a single scrape: the first
    # request runs the aggregator (and writes the cache), everyone else who
    # arrives mid-flight awaits the same task instead of re-scraping.
    async def _scrape_and_cache():
        found, status = await _aggregator.search(q, location, mode=mode, with_status=True)
        payload = {
            "results": [r.model_dump() for r in found],
            "platform_status": status,
        }
        if found:
            # Cache the unfiltered results so platform-filtered queries reuse the data.
            await set_cached(q, location, payload, mode)
            await track_popular_search(q)
        return payload

    payload = await coalesce(f"search:{_make_key(q, location, mode)}", _scrape_and_cache)
    platform_status = payload["platform_status"]

    if not payload["results"]:
        return SearchResponse(
            query=q, location=location, results=[], total=0,
            platform_status=platform_status,
        )

    # Coalesced waiters share the leader's payload, and the platform filter
    # below mutates result objects — rebuilding models from the dumped dicts
    # gives each response its own deep copy (same protection the previous
    # model_copy(deep=True) provided).
    from app.models.food import AggregatedResult
    results = [AggregatedResult(**r) for r in payload["results"]]
    results = _apply_platform_filter(results, platforms)

    return SearchResponse(
        query=q,
        location=location,
        results=results[:limit],
        total=len(results),
        platform_status=platform_status,
    )
