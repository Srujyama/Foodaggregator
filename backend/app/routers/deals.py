from fastapi import APIRouter, Query
from app.models.food import SearchResponse
from app.services.aggregator import AggregatorService
from app.services.cache import coalesce
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
_aggregator = AggregatorService()


@router.get("/deals", response_model=SearchResponse)
async def get_deals(
    location: str = Query(..., min_length=1, description="Location to find deals near"),
    limit: int = Query(10, ge=1, le=30),
):
    # The home page requests deals for every visitor; coalesce concurrent
    # identical requests so a traffic burst triggers one scrape, not N.
    key = f"deals:{location.lower().strip()}:{limit}"
    results = await coalesce(key, lambda: _aggregator.get_deals(location, limit=limit))

    return SearchResponse(
        query="deals",
        location=location,
        results=results,
        total=len(results),
    )
