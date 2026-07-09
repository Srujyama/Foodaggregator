from pydantic import BaseModel
from typing import List, Optional, Dict
from enum import Enum


class Platform(str, Enum):
    UBER_EATS = "uber_eats"
    DOORDASH = "doordash"
    GRUBHUB = "grubhub"
    POSTMATES = "postmates"
    SEAMLESS = "seamless"
    CAVIAR = "caviar"
    GOPUFF = "gopuff"
    EATSTREET = "eatstreet"


class MenuItem(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    section: Optional[str] = None       # menu category, e.g. "Burritos"
    item_id: Optional[str] = None       # platform's stable item id
    is_available: Optional[bool] = None  # False when the platform marks it sold out


class FeeSchedule(BaseModel):
    """Complete pre-checkout fee picture for one platform listing.

    All monetary fields are dollars. `estimated_fields` lists the field names
    whose values come from the platform's published/disclosed rates rather
    than this listing's own payload (platforms like Uber Eats and DoorDash
    only reveal the exact service fee at checkout), so the UI can label them.
    """
    delivery_fee: Optional[float] = None
    service_fee_pct: Optional[float] = None    # % of the item subtotal
    service_fee_flat: Optional[float] = None   # flat fee (used when pct is None)
    service_fee_min: Optional[float] = None    # floor when pct-based
    service_fee_max: Optional[float] = None    # cap when pct-based
    small_order_fee: Optional[float] = None
    small_order_threshold: Optional[float] = None  # fee applies below this subtotal
    minimum_order: Optional[float] = None
    tax_rate_pct: Optional[float] = None       # only when the platform exposes it
    estimated_fields: List[str] = []
    notes: List[str] = []


class MenuItemComparison(BaseModel):
    """Side-by-side price comparison for the same menu item across platforms."""
    item_name: str
    prices: Dict[str, Optional[float]]  # platform -> price (None if not available)
    cheapest_platform: Optional[str] = None
    price_difference: float = 0.0  # max price - min price


class PlatformResult(BaseModel):
    platform: Platform
    restaurant_name: str
    restaurant_id: str
    restaurant_url: str
    menu_items: List[MenuItem] = []
    # Delivery pricing
    delivery_fee: float
    service_fee: float
    fee_schedule: Optional[FeeSchedule] = None
    estimated_delivery_minutes: int
    estimated_delivery_minutes_max: Optional[int] = None
    # Pickup pricing
    pickup_available: bool = True
    pickup_fee: float = 0.0
    pickup_service_fee: float = 0.0
    estimated_pickup_minutes: Optional[int] = None
    # Other
    minimum_order: Optional[float] = None
    rating: Optional[float] = None
    rating_count: Optional[int] = None
    promo_text: Optional[str] = None
    fetched_at: str
    # Consumer-decision fields
    is_open: Optional[bool] = None
    accepting_orders: Optional[bool] = None
    is_within_delivery_range: Optional[bool] = None
    distance_text: Optional[str] = None  # "1.2 mi"
    categories: List[str] = []           # ["Mexican", "Burritos", ...]
    price_bucket: Optional[str] = None   # "$" / "$$" / "$$$"
    address: Optional[str] = None
    phone: Optional[str] = None
    hours_today_text: Optional[str] = None  # "Open until 11:00 PM"
    closing_soon: Optional[bool] = None
    allergen_disclaimer_html: Optional[str] = None
    status_text: Optional[str] = None    # human-readable status (e.g., "Not accepting orders", "No couriers nearby")


class AggregatedResult(BaseModel):
    query: str
    location: str
    restaurant_name: str
    platforms: List[PlatformResult]
    best_deal_platform: Optional[Platform] = None
    total_cost_by_platform: dict = {}
    pickup_cost_by_platform: dict = {}
    menu_comparison: List[MenuItemComparison] = []
    avg_menu_markup_by_platform: Dict[str, float] = {}  # platform -> avg markup %
    cached: bool = False


class SearchResponse(BaseModel):
    query: str
    location: str
    results: List[AggregatedResult]
    total: int
    cached: bool = False
    # Per-platform scrape outcome: "ok" | "empty" | "timeout" | "error",
    # keyed by Platform enum value. Empty for legacy cached payloads.
    platform_status: Dict[str, str] = {}


class HealthResponse(BaseModel):
    status: str
    timestamp: float
    scrapers: dict
