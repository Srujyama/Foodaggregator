from fastapi import APIRouter, Query, HTTPException
from app.models.food import SearchResponse
from app.services.aggregator import AggregatorService
from app.services.cache import get_cached, set_cached, track_popular_search
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
_aggregator = AggregatorService()


@router.get("/search", response_model=SearchResponse)
async def search_restaurants(
    q: str = Query(..., min_length=1, description="Search query (restaurant name or dish)"),
    location: str = Query(..., min_length=1, description="Location (city, ZIP, or address)"),
    limit: int = Query(20, ge=1, le=50),
    platforms: str = Query(None, description="Comma-separated platform filter"),
):
    # Check cache
    cached = await get_cached(q, location)
    if cached:
        return SearchResponse(
            query=q,
            location=location,
            results=[r for r in cached[:limit]],
            total=len(cached),
            cached=True,
        )

    # Fan out to scrapers
    results = await _aggregator.search(q, location)

    if not results:
        return SearchResponse(query=q, location=location, results=[], total=0)

    # Platform filter
    if platforms:
        allowed = {p.strip() for p in platforms.split(",")}
        for r in results:
            r.platforms = [p for p in r.platforms if p.platform.value in allowed]
        results = [r for r in results if r.platforms]

    # Cache results
    await set_cached(q, location, [r.model_dump() for r in results])
    await track_popular_search(q)

    return SearchResponse(
        query=q,
        location=location,
        results=results[:limit],
        total=len(results),
    )
