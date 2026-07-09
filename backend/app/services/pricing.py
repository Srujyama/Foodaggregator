"""Fee schedules and meal-cost estimation.

Platforms differ in how much of their fee structure they reveal before
checkout:

- Grubhub exposes the exact service fee on the search payload itself
  (``price_response.delivery_response.service_fee``: ``basis_points`` % of
  subtotal plus a flat floor and a cap), so its schedule is exact.
- DoorDash / Caviar disclose only prose: "The service fee may vary but is 15%
  of your subtotal for most restaurant orders ... A flat, minimum service fee
  may apply on small orders." The exact number exists only on a cart.
- Uber Eats / Postmates expose nothing numeric pre-checkout (fareInfo.
  serviceFeeCents is null; the fee explainer is prose).

Where a value is not in the payload we fall back to the platform's own
published/disclosed rate and record the field name in
``FeeSchedule.estimated_fields`` so every consumer can label it as an
estimate rather than pass it off as exact.
"""

from typing import Optional

from app.models.food import FeeSchedule, PlatformResult

# Fields that build_fee_schedule() will backfill from defaults when the
# scraper couldn't find them in the platform payload.
_DEFAULTABLE_FIELDS = (
    "service_fee_pct",
    "service_fee_min",
    "service_fee_max",
    "small_order_fee",
    "small_order_threshold",
)

# Published/disclosed fee structures per platform. Sources in comments; keep
# these in sync with src/utils/mealCost.js (frontend mirror).
PLATFORM_FEE_DEFAULTS: dict[str, dict] = {
    # DoorDash's own pricing tooltip (store page, verified July 2026): "The
    # service fee may vary but is 15% of your subtotal for most restaurant
    # orders ... A flat, minimum service fee may apply on small orders."
    # Small-order fee is disclosed as applying "to orders with a subtotal
    # under $<amount>" with the amount withheld pre-checkout; $2.50 under $10
    # is DoorDash's widely published standard.
    "doordash": {
        "service_fee_pct": 15.0,
        "service_fee_min": 3.00,
        "small_order_fee": 2.50,
        "small_order_threshold": 10.00,
    },
    # Caviar runs on DoorDash's backend and fee structure.
    "caviar": {
        "service_fee_pct": 15.0,
        "service_fee_min": 3.00,
        "small_order_fee": 2.50,
        "small_order_threshold": 10.00,
    },
    # Uber's fee explainer (getStoreV1 priceBottomSheet) describes a
    # basket-size-dependent service fee and a city-dependent small-order fee
    # without numbers; ~15% with a ~$2 floor and ~$2 fee under $10 are Uber's
    # widely published standards for US restaurant orders.
    "uber_eats": {
        "service_fee_pct": 15.0,
        "service_fee_min": 2.00,
        "small_order_fee": 2.00,
        "small_order_threshold": 10.00,
    },
    # Postmates is the same Uber backend and fee structure.
    "postmates": {
        "service_fee_pct": 15.0,
        "service_fee_min": 2.00,
        "small_order_fee": 2.00,
        "small_order_threshold": 10.00,
    },
    # Grubhub normally ships its exact service fee in the payload
    # (basis_points + floor + cap); this fallback only applies when that
    # block is missing. Grubhub's published service fee runs ~10% with a
    # small floor.
    "grubhub": {
        "service_fee_pct": 10.0,
        "service_fee_min": 2.00,
    },
    # Seamless shares Grubhub's backend.
    "seamless": {
        "service_fee_pct": 10.0,
        "service_fee_min": 2.00,
    },
    # EatStreet's public API is delivery-fee + minimum-order only; GoPuff's
    # fee structure is unknown. No defaults — better to show nothing than to
    # invent a structure we have no source for.
    "eatstreet": {},
    "gopuff": {},
}


def build_fee_schedule(
    platform: str,
    *,
    delivery_fee: Optional[float] = None,
    service_fee_pct: Optional[float] = None,
    service_fee_flat: Optional[float] = None,
    service_fee_min: Optional[float] = None,
    service_fee_max: Optional[float] = None,
    small_order_fee: Optional[float] = None,
    small_order_threshold: Optional[float] = None,
    minimum_order: Optional[float] = None,
    tax_rate_pct: Optional[float] = None,
    notes: Optional[list[str]] = None,
) -> FeeSchedule:
    """Build a FeeSchedule from scraped values, backfilling gaps from the
    platform's published defaults and marking every backfilled field in
    ``estimated_fields``.

    A scraped exact service fee % (Grubhub basis_points) suppresses ALL
    service-fee defaulting — mixing an exact % with an estimated floor would
    blur what "exact" means.
    """
    schedule = FeeSchedule(
        delivery_fee=delivery_fee,
        service_fee_pct=service_fee_pct,
        service_fee_flat=service_fee_flat,
        service_fee_min=service_fee_min,
        service_fee_max=service_fee_max,
        small_order_fee=small_order_fee,
        small_order_threshold=small_order_threshold,
        minimum_order=minimum_order,
        tax_rate_pct=tax_rate_pct,
        notes=list(notes or []),
    )

    defaults = PLATFORM_FEE_DEFAULTS.get(platform, {})
    estimated: list[str] = []
    have_exact_pct = service_fee_pct is not None
    for field in _DEFAULTABLE_FIELDS:
        if getattr(schedule, field) is not None:
            continue
        if have_exact_pct and field.startswith("service_fee"):
            continue
        # A scraped flat service fee (no %) is the platform's own number;
        # don't graft an estimated % structure on top of it.
        if service_fee_flat is not None and field.startswith("service_fee"):
            continue
        if field in defaults:
            setattr(schedule, field, defaults[field])
            estimated.append(field)

    schedule.estimated_fields = estimated
    return schedule


def ensure_fee_schedule(result: PlatformResult) -> None:
    """Guarantee a PlatformResult carries a fee schedule.

    Scrapers with rich payloads set fee_schedule themselves; this fallback
    covers every other construction site using the flat fields they already
    populate.
    """
    if result.fee_schedule is not None:
        return
    platform = (
        result.platform.value
        if hasattr(result.platform, "value")
        else str(result.platform)
    )
    result.fee_schedule = build_fee_schedule(
        platform,
        delivery_fee=result.delivery_fee,
        # A scraped flat service fee > 0 is platform data; 0 nearly always
        # means "not exposed", so let defaults fill the structure instead.
        service_fee_flat=result.service_fee if result.service_fee > 0 else None,
        minimum_order=result.minimum_order,
    )


def compute_service_fee(schedule: FeeSchedule, subtotal: float) -> Optional[float]:
    """Service fee for a given item subtotal, or None when unknowable."""
    if schedule.service_fee_pct is not None:
        fee = subtotal * schedule.service_fee_pct / 100.0
        floor = schedule.service_fee_min
        if floor is None and schedule.service_fee_flat is not None:
            floor = schedule.service_fee_flat
        if floor is not None:
            fee = max(fee, floor)
        if schedule.service_fee_max is not None:
            fee = min(fee, schedule.service_fee_max)
        return round(fee, 2)
    if schedule.service_fee_flat is not None:
        return round(schedule.service_fee_flat, 2)
    return None


def compute_small_order_fee(schedule: FeeSchedule, subtotal: float) -> float:
    if (
        schedule.small_order_fee is not None
        and schedule.small_order_threshold is not None
        and subtotal < schedule.small_order_threshold
    ):
        return round(schedule.small_order_fee, 2)
    return 0.0


def estimate_meal_cost(
    schedule: FeeSchedule,
    subtotal: float,
    mode: str = "delivery",
    fallback_tax_rate_pct: Optional[float] = None,
) -> dict:
    """Full cost breakdown for a basket subtotal on one platform.

    Returns dollars rounded to cents:
    ``{subtotal, delivery_fee, service_fee, small_order_fee, tax_rate_pct,
    tax, total, below_minimum, minimum_order, estimated_fields}``.

    ``tax`` uses the platform-exposed rate when present, else
    ``fallback_tax_rate_pct`` (callers derive one from the delivery
    location); with neither, tax is 0 and tax_rate_pct is None so the caller
    can label the total "before tax".

    Pickup mode drops the delivery/service/small-order fees — those are
    delivery-basket fees; the platforms' (almost always $0) flat pickup fees
    live on PlatformResult.pickup_fee/pickup_service_fee and are the
    caller's to add.
    """
    subtotal = round(max(subtotal, 0.0), 2)
    if mode == "delivery":
        delivery_fee = round(schedule.delivery_fee or 0.0, 2)
        service_fee = compute_service_fee(schedule, subtotal)
        small_order_fee = compute_small_order_fee(schedule, subtotal)
    else:
        delivery_fee = 0.0
        service_fee = 0.0
        small_order_fee = 0.0

    estimated = list(schedule.estimated_fields)
    tax_rate = schedule.tax_rate_pct
    if tax_rate is None and fallback_tax_rate_pct is not None:
        tax_rate = fallback_tax_rate_pct
        estimated.append("tax_rate_pct")
    tax = round(subtotal * tax_rate / 100.0, 2) if tax_rate is not None else 0.0

    total = round(
        subtotal + delivery_fee + (service_fee or 0.0) + small_order_fee + tax, 2
    )

    below_minimum = (
        schedule.minimum_order is not None and subtotal < schedule.minimum_order
    )

    return {
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "service_fee": service_fee,
        "small_order_fee": small_order_fee,
        "tax_rate_pct": tax_rate,
        "tax": tax,
        "total": total,
        "below_minimum": below_minimum,
        "minimum_order": schedule.minimum_order,
        "estimated_fields": estimated,
    }
