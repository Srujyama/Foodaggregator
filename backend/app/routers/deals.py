from fastapi import APIRouter, Query
from app.models.food import SearchResponse
from app.services.aggregator import AggregatorService
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
_aggregator = AggregatorService()


@router.get("/deals", response_model=SearchResponse)
async def get_deals(
    location: str = Query(..., min_length=1, description="Location to find deals near"),
    limit: int = Query(10, ge=1, le=30),
):
    results = await _aggregator.get_deals(location, limit=limit)

    return SearchResponse(
        query="deals",
        location=location,
        results=results,
        total=len(results),
    )
