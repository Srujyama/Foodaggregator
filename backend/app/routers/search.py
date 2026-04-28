from fastapi import APIRouter, Query
from app.models.food import SearchResponse
from app.services.aggregator import AggregatorService
from app.services.cache import get_cached, set_cached, track_popular_search
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
        results = [AggregatedResult(**r) for r in cached]
        results = _apply_platform_filter(results, platforms)
        return SearchResponse(
            query=q,
            location=location,
            results=results[:limit],
            total=len(results),
            cached=True,
        )

    results = await _aggregator.search(q, location, mode=mode)

    if not results:
        return SearchResponse(query=q, location=location, results=[], total=0)

    # Cache the unfiltered results so platform-filtered queries reuse the data.
    await set_cached(q, location, [r.model_dump() for r in results], mode)
    await track_popular_search(q)

    results = _apply_platform_filter(results, platforms)

    return SearchResponse(
        query=q,
        location=location,
        results=results[:limit],
        total=len(results),
    )
