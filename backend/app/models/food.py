from pydantic import BaseModel
from typing import List, Optional
from enum import Enum


class Platform(str, Enum):
    UBER_EATS = "uber_eats"
    DOORDASH = "doordash"
    GRUBHUB = "grubhub"


class MenuItem(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None


class PlatformResult(BaseModel):
    platform: Platform
    restaurant_name: str
    restaurant_id: str
    restaurant_url: str
    menu_items: List[MenuItem] = []
    delivery_fee: float
    service_fee: float
    estimated_delivery_minutes: int
    minimum_order: Optional[float] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    promo_text: Optional[str] = None
    fetched_at: str


class AggregatedResult(BaseModel):
    query: str
    location: str
    restaurant_name: str
    platforms: List[PlatformResult]
    best_deal_platform: Optional[Platform] = None
    total_cost_by_platform: dict = {}
    cached: bool = False


class SearchResponse(BaseModel):
    query: str
    location: str
    results: List[AggregatedResult]
    total: int
    cached: bool = False


class HealthResponse(BaseModel):
    status: str
    timestamp: float
    scrapers: dict
