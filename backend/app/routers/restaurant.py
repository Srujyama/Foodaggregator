from fastapi import APIRouter, Query, HTTPException
from app.models.food import AggregatedResult
from app.services.aggregator import AggregatorService
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
_aggregator = AggregatorService()


@router.get("/restaurant/{name}", response_model=AggregatedResult)
async def get_restaurant(
    name: str,
    location: str = Query(..., min_length=1),
):
    result = await _aggregator.get_restaurant(name, location)

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Restaurant '{name}' not found near '{location}'.",
        )

    return result
