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
    mode: str = Query("delivery", description="Order mode: delivery or pickup"),
):
    mode = (mode or "delivery").lower()
    if mode not in ("delivery", "pickup"):
        mode = "delivery"
    result = await _aggregator.get_restaurant(name, location, mode=mode)

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Restaurant '{name}' not found near '{location}'.",
        )

    return result
