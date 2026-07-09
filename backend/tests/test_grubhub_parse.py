"""Tests for app.services.grubhub parsing helpers — phone normalization,
the cents-based fee/minimum parsing, query-token name matching (all were
live-data bugs), full-menu parsing (sections/item ids, no 30/60 caps,
zero-price items kept), and the exact service-fee schedule extracted from
price_response.delivery_response.service_fee (basis_points/flat_cents/
maximum_flat_amount — key names verified live July 2026)."""

import app.services.grubhub as gh
from app.services.grubhub import (
    GrubhubScraper,
    _name_matches_query,
    _normalize_phone,
    _parse_menu,
    _parse_restaurant,
    _query_tokens,
)


# ---------- phone normalization ----------


def test_normalize_phone_passthrough_string():
    assert _normalize_phone("3024549938") == "3024549938"


def test_normalize_phone_dict_with_country_code():
    # The shape that previously crashed pydantic validation (dict -> str).
    assert _normalize_phone(
        {"country_code": "1", "phone_number": "3024549938"}
    ) == "+1 3024549938"


def test_normalize_phone_none_and_empty():
    assert _normalize_phone(None) is None
    assert _normalize_phone({}) is None
    assert _normalize_phone("") is None


# ---------- cents-based fee / minimum parsing ----------


def test_delivery_fee_parsed_as_cents():
    rd = _parse_restaurant({
        "name": "Tico's Tacos",
        "restaurant_id": "123",
        "delivery_fee": {"price": 300, "currency": "USD"},
    })
    assert rd["delivery_fee"] == 3.00  # not $300


def test_free_delivery_stays_zero():
    rd = _parse_restaurant({
        "name": "X",
        "restaurant_id": "1",
        "delivery_fee": {"price": 0, "currency": "USD"},
    })
    assert rd["delivery_fee"] == 0.0


def test_minimum_order_parsed_as_cents():
    rd = _parse_restaurant({
        "name": "Tico's Tacos",
        "restaurant_id": "123",
        "delivery_minimum": {"price": 2000, "currency": "USD"},
    })
    assert rd["minimum_order"] == 20.00  # not $2000


# ---------- query-token name matching ----------


def test_name_match_survives_apostrophes_in_name():
    """Live bug: searching "mcdonalds" wiped Grubhub's only hit because the
    alpha-only token never substring-matched the apostrophized "McDonald's",
    so the scraper fell back to a web scrape that found nothing."""
    assert _name_matches_query("McDonald's® (815 South College Ave)", _query_tokens("mcdonalds"))
    assert _name_matches_query("Wendy's", _query_tokens("wendys"))
    assert _name_matches_query("Chili's Grill & Bar", _query_tokens("chilis"))


def test_name_match_still_requires_all_tokens():
    assert not _name_matches_query("Burger King", _query_tokens("mcdonalds"))
    assert _name_matches_query("Taco Bell Cantina", _query_tokens("taco bell"))
    assert not _name_matches_query("Taco Loco", _query_tokens("taco bell"))


# ---------- full menu: sections, item ids, no caps ----------


def _item(i: int, cents: int = 500, **overrides) -> dict:
    d = {
        "id": 1000 + i,
        "name": f"Item {i}",
        "price": {"amount": cents, "currency": "USD"},
    }
    d.update(overrides)
    return d


def _category(name: str, items: list) -> dict:
    return {"name": name, "id": abs(hash(name)) % 10**9, "menu_item_list": items}


def test_menu_sections_and_item_ids_extracted():
    menu = _parse_menu({"menu_category_list": [
        _category("Burritos", [_item(1), _item(2)]),
        _category("Tacos", [_item(3, cents=289)]),
    ]})
    assert [m.section for m in menu] == ["Burritos", "Burritos", "Tacos"]
    assert [m.item_id for m in menu] == ["1001", "1002", "1003"]
    assert menu[2].price == 2.89


def test_menu_no_more_30_per_category_or_60_total_caps():
    # 3 categories x 40 items: the old code kept 30/category and stopped at
    # 60 total; the full menu is 120 items.
    payload = {"menu_category_list": [
        _category(f"Cat {c}", [_item(c * 100 + i) for i in range(40)])
        for c in range(3)
    ]}
    menu = _parse_menu(payload)
    assert len(menu) == 120
    assert sum(1 for m in menu if m.section == "Cat 2") == 40


def test_menu_safety_bound_still_applies(monkeypatch):
    monkeypatch.setattr(gh, "MAX_MENU_ITEMS", 5)
    payload = {"menu_category_list": [
        _category("Big", [_item(i) for i in range(10)]),
    ]}
    assert len(_parse_menu(payload)) == 5


def test_menu_dedupes_repeated_item_ids_across_categories():
    shared = _item(7)
    menu = _parse_menu({"menu_category_list": [
        _category("Popular", [shared]),
        _category("Tacos", [dict(shared), _item(8)]),
    ]})
    assert [m.item_id for m in menu] == ["1007", "1008"]


def test_zero_price_items_retained_at_zero():
    menu = _parse_menu({"menu_category_list": [
        _category("Sauces", [
            _item(1, cents=0, name="Hot Sauce Packet"),
            _item(2, cents=-100, name="Weird Negative"),
            _item(3, cents=365),
        ]),
    ]})
    assert [m.name for m in menu] == ["Hot Sauce Packet", "Weird Negative", "Item 3"]
    assert menu[0].price == 0.0
    assert menu[1].price == 0.0  # negative clamps to 0, never negative
    assert menu[2].price == 3.65


def test_menu_item_available_flag_mapped():
    menu = _parse_menu({"menu_category_list": [
        _category("Tacos", [
            _item(1, available=False),
            _item(2, available=True),
            _item(3),  # no 'available' key -> unknown
        ]),
    ]})
    assert [m.is_available for m in menu] == [False, True, None]


# ---------- exact service-fee schedule from price_response ----------


def _search_restaurant(service_fee: dict | None = None, **overrides) -> dict:
    d = {
        "name": "Taco Bell",
        "restaurant_id": "928831",
        "delivery_fee": {"price": 300, "currency": "USD"},
        "delivery_minimum": {"price": 1500, "currency": "USD"},
    }
    if service_fee is not None:
        d["price_response"] = {"delivery_response": {"service_fee": service_fee}}
    d.update(overrides)
    return d


def test_basis_points_converted_to_pct_with_cap():
    # Live shape (Berkeley Taco Bell, July 2026): basis_points=1250,
    # flat_cents=0, maximum_flat_amount=900 (cents), minimum_flat_amount=null.
    rd = _parse_restaurant(_search_restaurant({
        "flat_cents": 0,
        "basis_points": 1250,
        "maximum_flat_amount": 900,
        "minimum_flat_amount": None,
    }))
    assert rd["service_fee_pct"] == 12.5
    assert rd["service_fee_max"] == 9.0
    assert rd["service_fee_min"] is None
    assert rd["service_fee"] == 0.0  # legacy flat float: flat_cents only


def test_flat_cents_sets_floor_and_legacy_flat_fee():
    rd = _parse_restaurant(_search_restaurant({
        "flat_cents": 200,
        "basis_points": 1035,
        "maximum_flat_amount": 1400,
    }))
    assert rd["service_fee_pct"] == 10.35
    assert rd["service_fee_min"] == 2.0
    assert rd["service_fee_max"] == 14.0
    assert rd["service_fee"] == 2.0  # unchanged legacy behavior


def test_minimum_flat_amount_used_as_floor_when_no_flat_cents():
    rd = _parse_restaurant(_search_restaurant({
        "flat_cents": 0,
        "basis_points": 1500,
        "minimum_flat_amount": 300,
    }))
    assert rd["service_fee_min"] == 3.0
    assert rd["service_fee"] == 0.0  # floor is schedule-only; flat float untouched


def test_flat_only_service_fee_is_exact_flat_not_a_floor():
    """flat_cents with no positive basis_points is Grubhub's exact flat
    service fee; it must land in service_fee_flat so build_fee_schedule
    doesn't graft the estimated 10% default on top of it."""
    rd = _parse_restaurant(_search_restaurant({
        "flat_cents": 250,
        "basis_points": 0,
        "flat": True,
        "percent": False,
    }))
    assert rd["service_fee_flat"] == 2.5
    assert rd["service_fee_min"] is None
    assert rd["service_fee_pct"] is None
    assert rd["service_fee"] == 2.5  # legacy flat float unchanged

    scraper = GrubhubScraper()
    results = scraper._build_results([{"restaurant": _search_restaurant({
        "flat_cents": 250,
        "basis_points": 0,
    })}])
    fs = results[0].fee_schedule
    assert fs.service_fee_flat == 2.5
    assert fs.service_fee_pct is None
    assert not any(f.startswith("service_fee") for f in fs.estimated_fields)
    from app.services.pricing import compute_service_fee
    assert compute_service_fee(fs, 100.0) == 2.5  # flat at any subtotal


def test_missing_service_fee_block_yields_none_components():
    rd = _parse_restaurant(_search_restaurant(None))
    assert rd["service_fee_pct"] is None
    assert rd["service_fee_min"] is None
    assert rd["service_fee_max"] is None
    assert rd["small_order_fee"] is None
    assert rd["service_fee"] == 0.0


# ---------- fee_schedule attachment on PlatformResult ----------


def test_api_results_attach_exact_fee_schedule_not_estimated():
    scraper = GrubhubScraper()
    results = scraper._build_results([{"restaurant": _search_restaurant({
        "flat_cents": 0,
        "basis_points": 1250,
        "maximum_flat_amount": 900,
    })}])
    assert len(results) == 1
    fs = results[0].fee_schedule
    assert fs is not None
    assert fs.service_fee_pct == 12.5
    assert fs.service_fee_max == 9.0
    assert fs.delivery_fee == 3.0
    assert fs.minimum_order == 15.0
    # Exact scraped pct must suppress service-fee defaulting entirely.
    assert not any(f.startswith("service_fee") for f in fs.estimated_fields)


def test_api_results_without_fee_block_get_labeled_defaults():
    scraper = GrubhubScraper()
    results = scraper._build_results([{"restaurant": _search_restaurant(None)}])
    fs = results[0].fee_schedule
    assert fs is not None
    assert fs.service_fee_pct == 10.0  # Grubhub's published fallback
    assert "service_fee_pct" in fs.estimated_fields
    assert "service_fee_min" in fs.estimated_fields


def test_web_scrape_results_attach_no_fee_schedule():
    # Web-scrape extractors fabricate delivery_fee=0; a schedule built from
    # that would launder fake numbers. The aggregator's ensure_fee_schedule
    # fallback owns those.
    scraper = GrubhubScraper()
    results = scraper._build_results_from_raw([{
        "name": "Taco Bell",
        "restaurant_id": "tb-1",
        "delivery_fee": 0,
        "delivery_time_estimate": 35,
    }])
    assert len(results) == 1
    assert results[0].fee_schedule is None


# ---------- get_restaurant detail path (fake HTTP) ----------


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        return _FakeResp(self._payload)


async def test_get_restaurant_full_menu_and_availability_schedule(monkeypatch):
    """The /restaurants/{id} detail payload keeps fees on the sibling
    restaurant_availability object (keys verified live July 2026):
    service_fee.delivery_fee.percent_value / maximum_amount_for_percent,
    sales_tax (pre-checkout %!), order_minimum, delivery_fee."""
    detail = {
        "restaurant": {
            "name": "Taco Bell",
            "restaurant_id": "928831",
            "menu_category_list": [
                _category(f"Cat {c}", [_item(c * 100 + i) for i in range(40)])
                for c in range(3)
            ],
        },
        "restaurant_availability": {
            "sales_tax": 10.25,
            "service_fee": {
                "delivery_fee": {
                    "fee_type": "PERCENT",
                    "percent_value": 12.5,
                    "maximum_amount_for_percent": {"amount": 900, "currency": "USD"},
                },
            },
            "order_minimum": {"amount": 1000, "currency": "USD"},
            "delivery_fee": {"amount": 199, "currency": "USD"},
        },
    }

    async def fake_token():
        return "test-token"

    monkeypatch.setattr(gh, "_get_token", fake_token)
    monkeypatch.setattr(gh.httpx, "AsyncClient", lambda **kw: _FakeClient(detail))

    result = await GrubhubScraper().get_restaurant("928831", "Berkeley, CA")
    assert result is not None
    assert len(result.menu_items) == 120  # no 30/60 caps
    assert result.menu_items[0].section == "Cat 0"
    assert result.menu_items[0].item_id == "1000"

    fs = result.fee_schedule
    assert fs is not None
    assert fs.service_fee_pct == 12.5
    assert fs.service_fee_max == 9.0
    assert fs.tax_rate_pct == 10.25
    assert fs.minimum_order == 10.0
    assert fs.delivery_fee == 1.99
    assert not any(f.startswith("service_fee") for f in fs.estimated_fields)
    assert result.minimum_order == 10.0


# ---------- seamless mirrors the grubhub menu parsing ----------


def test_seamless_menu_mirror_no_caps_sections_and_ids():
    from app.services.seamless import _parse_menu as sl_parse_menu

    payload = {"menu_category_list": [
        _category(f"Cat {c}", [_item(c * 100 + i) for i in range(40)])
        for c in range(3)
    ]}
    menu = sl_parse_menu(payload)
    assert len(menu) == 120
    assert menu[0].section == "Cat 0"
    assert menu[0].item_id == "1000"
