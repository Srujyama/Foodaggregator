"""DoorDash/Caviar 2026 RSC parsing: full menus with sections + item ids,
search-record numeric fields, fee schedules, and GraphQL-AST decoy immunity.

Fixtures are TRIMMED slices of a live July 2026 capture (Taco Bell store
1193580 near Bear, DE):

- ``dd_store_page_rsc.html``: store page wrapped in real
  ``self.__next_f.push([1,"..."])`` script chunks (split mid-JSON on purpose
  to exercise chunk reassembly). Contains the GraphQL query AST decoys
  ({"kind":"Name","value":"menuBook"} nodes and a
  {"kind":"NamedType",...,"value":"MenuPageItemList"} type condition),
  DashPass marketing copy ("Enjoy up to 12 months of $0 delivery fees."),
  the real menuBook (17 categories), the real DeliveryFeeLayout header, and
  3 complete MenuPageItemList blocks: Most Ordered (12), Quesadillas (4),
  Bowls (2) — with "Chicken Quesadilla" (id 201243370) present in BOTH Most
  Ordered and Quesadillas to prove per-id dedupe.
- ``dd_search_page_rsc.html``: a window_shopping preview row plus two full
  search-record T-rows: the real Taco Bell record (delivery_fee_amount 0,
  "$0 delivery fee, first order" promo) and a McDonald's record patched to
  carry nonzero cents fees (delivery_fee_amount 399,
  minimum_subtotal_amount 1200) since the live capture had an anonymous
  first-order promo zeroing every fee.
- ``dd_rsc_ast_decoy.txt``: ONLY the AST decoys + DashPass marketing — no
  data blocks — for anchor-immunity tests.
"""

from pathlib import Path

import pytest

from app.services import caviar, doordash

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture(scope="module")
def store_html() -> str:
    return _load("dd_store_page_rsc.html")


@pytest.fixture(scope="module")
def search_html() -> str:
    return _load("dd_search_page_rsc.html")


@pytest.fixture(scope="module")
def decoy_text() -> str:
    return _load("dd_rsc_ast_decoy.txt")


# ---------------------------------------------------------------------------
# Full menu extraction
# ---------------------------------------------------------------------------

def test_full_menu_items_with_sections_ids_and_cents_prices(store_html):
    items = doordash._extract_menu_items(store_html)

    # 12 (Most Ordered) + 4 (Quesadillas) + 2 (Bowls) = 18 raw items, minus
    # the Chicken Quesadilla duplicate = 17.
    assert len(items) == 17

    sections = {i.section for i in items}
    assert sections == {"Most Ordered", "Quesadillas", "Bowls"}

    # Every item carries the platform's stable id and its section.
    assert all(i.item_id for i in items)
    assert all(i.section for i in items)

    # Price comes from quickAddContext.price.unitAmount (877 cents), NOT
    # from the doubled-dollar "$$8.77" display string.
    cq = [i for i in items if i.name == "Chicken Quesadilla"]
    assert len(cq) == 1
    assert cq[0].price == 8.77
    assert cq[0].item_id == "201243370"
    assert cq[0].description and "tortilla" in cq[0].description.lower()
    assert cq[0].image_url and cq[0].image_url.startswith("https://")

    # No price ever leaks the doubled '$' (would parse as 0.0 with a bad
    # parser) and none went negative.
    assert all(i.price >= 0 for i in items)


def test_per_id_dedupe_first_occurrence_wins(store_html):
    items = doordash._extract_menu_items(store_html)
    ids = [i.item_id for i in items]
    assert len(ids) == len(set(ids)), "item ids must be unique after dedupe"

    # Chicken Quesadilla exists in both Most Ordered and Quesadillas in the
    # raw payload; first occurrence (Most Ordered) wins.
    cq = next(i for i in items if i.item_id == "201243370")
    assert cq.section == "Most Ordered"


def test_same_name_in_different_sections_is_not_deduped():
    # Two sections each sell a "Large Drink" under different item ids: both
    # must survive (name-level dedupe across sections is wrong).
    rsc = (
        '{"itemLists":['
        '{"__typename":"MenuPageItemList","id":"category-1","name":"Drinks","items":['
        '{"__typename":"MenuPageItem","id":"111","name":"Large Drink",'
        '"displayPrice":"$$2.49","quickAddContext":{"price":{"unitAmount":249}}}]},'
        '{"__typename":"MenuPageItemList","id":"category-2","name":"Combos","items":['
        '{"__typename":"MenuPageItem","id":"222","name":"Large Drink",'
        '"displayPrice":"$$0.00","quickAddContext":{"price":{"unitAmount":0}}}]}]}'
    )
    items = doordash._extract_menu_items_from_text(rsc)
    assert [(i.item_id, i.section) for i in items] == [
        ("111", "Drinks"),
        ("222", "Combos"),
    ]
    # Zero-price items (e.g. included drinks) are kept.
    assert items[1].price == 0.0


def test_doubled_dollar_display_price_fallback():
    # No quickAddContext -> price falls back to displayPrice, and the
    # RSC-doubled "$$4.50" must read as 4.50 (not 0, not 44.50).
    rsc = (
        '{"__typename":"MenuPageItemList","id":"category-9","name":"Sides","items":['
        '{"__typename":"MenuPageItem","id":"333","name":"Fries","displayPrice":"$$4.50"}]}'
    )
    items = doordash._extract_menu_items_from_text(rsc)
    assert len(items) == 1
    assert items[0].price == 4.50
    assert doordash._display_money_to_float("$$8.77") == 8.77
    assert doordash._display_money_to_float("$8.77") == 8.77
    assert doordash._display_money_to_float("") is None


def test_menu_parser_ignores_graphql_ast_decoys(decoy_text):
    """The blob embeds the same key names inside GraphQL query ASTs
    ({"kind":"Name","value":"menuBook"}, a NamedType node whose value is
    "MenuPageItemList", ...). The parser must find NOTHING there."""
    assert '"value":"menuBook"' in decoy_text
    assert '"value":"MenuPageItemList"' in decoy_text
    assert doordash._menu_items_from_item_lists(decoy_text) == []


def test_menu_parser_finds_data_despite_decoys_in_same_blob(store_html):
    # The store fixture contains those same AST decoys *plus* the real data;
    # extraction must anchor on the data blocks only (no {"kind": ...} noise
    # ever surfaces as an item).
    items = doordash._extract_menu_items(store_html)
    names = {i.name for i in items}
    assert "menuBook" not in names
    assert not any(n in {"Name", "Field", "SelectionSet"} for n in names)
    assert len(items) == 17


# ---------------------------------------------------------------------------
# Search-page store records
# ---------------------------------------------------------------------------

def test_search_records_numeric_fields(search_html):
    stores = doordash._extract_rsc_stores(search_html)
    assert len(stores) == 2  # window_shopping preview row must NOT count

    tb = next(s for s in stores if s["store_name"] == "Taco Bell")
    assert tb["store_id"] == "1193580"
    assert tb["star_rating"] == "4.3"        # QUOTED string in the payload
    assert tb["num_ratings"] == 12550        # from quoted "num_star_rating"
    assert tb["delivery_fee"] == 0.0
    assert tb["minimum_order"] is None       # 0 in payload -> unknown
    assert tb["promo_text"] == "$0 delivery fee, first order"
    assert tb["store_display_asap_time"] == "31 min"  # asap_time 31
    assert tb["price_range"] == 2

    mc = next(s for s in stores if s["store_name"] == "McDonald's")
    # Cents convention: 399 -> $3.99, 1200 -> $12.00; the numeric fee wins
    # over any promo-string parsing when > 0.
    assert mc["delivery_fee"] == 3.99
    assert mc["minimum_order"] == 12.0
    assert mc["promo_text"] is None


def test_search_build_results_wires_fields_and_fee_schedule(search_html):
    stores = doordash._extract_rsc_stores(search_html)
    results = doordash.DoorDashScraper()._build_results(stores)
    by_name = {r.restaurant_name: r for r in results}

    tb = by_name["Taco Bell"]
    assert tb.rating == 4.3
    assert tb.rating_count == 12550
    assert tb.estimated_delivery_minutes == 31
    assert tb.price_bucket == "$$"
    assert tb.minimum_order is None

    mc = by_name["McDonald's"]
    assert mc.delivery_fee == 3.99
    assert mc.minimum_order == 12.0

    # Fee schedule: scraped delivery fee + minimum, service fee filled from
    # DoorDash's published 15%/min-$3 disclosure and labelled estimated.
    for r in (tb, mc):
        fs = r.fee_schedule
        assert fs is not None
        assert fs.delivery_fee == r.delivery_fee
        assert fs.service_fee_pct == 15.0
        assert fs.service_fee_min == 3.0
        assert fs.service_fee_flat is None   # DoorDash never exposes a flat fee
        assert "service_fee_pct" in fs.estimated_fields
    assert mc.fee_schedule.minimum_order == 12.0


def test_amount_field_cents_convention():
    f = doordash._amount_field_to_dollars
    assert f(0) == 0.0
    assert f(399) == 3.99
    assert f(1200) == 12.0
    assert f(3.99) == 3.99   # fractional -> already dollars (defensive)
    assert f(None) is None
    assert f("nope") is None


# ---------------------------------------------------------------------------
# Store-page header fees / promo bounding
# ---------------------------------------------------------------------------

def test_store_header_fees_from_delivery_fee_layout(store_html):
    full_text = doordash._extract_rsc_text(store_html)
    header = doordash._extract_store_header_fees(full_text)
    # The real header says "$$0 delivery fee, first order": fee 0 + promo,
    # normalized to a single '$'.
    assert header["delivery_fee"] == 0.0
    assert header["promo"] == "$0 delivery fee, first order"
    assert "DashPass" not in header["promo"]


def test_promo_scan_ignores_dashpass_marketing(decoy_text):
    # The decoy blob contains ONLY DashPass ad copy ("Enjoy up to 12 months
    # of $0 delivery fees.") — no store header. The old blob-wide regex
    # matched this on every store; the bounded scan must not.
    assert "months of $0 delivery fees" in decoy_text
    header = doordash._extract_store_header_fees(decoy_text)
    assert header["promo"] is None
    assert header["delivery_fee"] is None


def test_promo_scan_still_matches_genuine_zero_fee_snippet():
    # A legit store-level $0 promo (no marketing context) still parses when
    # there is no DeliveryFeeLayout (older payloads).
    text = '..."delivery_fee_str":"$0 delivery fee on your order",...'
    header = doordash._extract_store_header_fees(text)
    assert header["delivery_fee"] == 0.0
    assert header["promo"] == "$0 delivery fee on your order"


# ---------------------------------------------------------------------------
# Caviar mirrors the DoorDash RSC shape
# ---------------------------------------------------------------------------

def test_caviar_full_menu_and_fee_schedule(store_html, search_html):
    # Same RSC shape -> same full menu with sections/ids/prices.
    items = caviar._extract_menu_items(store_html)
    assert len(items) == 17
    assert {i.section for i in items} == {"Most Ordered", "Quesadillas", "Bowls"}
    cq = next(i for i in items if i.item_id == "201243370")
    assert cq.price == 8.77

    # Search records parse through the shared path too, and results carry a
    # Caviar fee schedule (DoorDash's published structure).
    stores = caviar._extract_stores(search_html)
    assert {s["store_name"] for s in stores} == {"Taco Bell", "McDonald's"}
    results = caviar.CaviarScraper()._build_results(stores)
    mc = next(r for r in results if r.restaurant_name == "McDonald's")
    assert mc.delivery_fee == 3.99
    assert mc.minimum_order == 12.0
    fs = mc.fee_schedule
    assert fs is not None
    assert fs.delivery_fee == 3.99
    assert fs.service_fee_pct == 15.0
    assert "service_fee_pct" in fs.estimated_fields
