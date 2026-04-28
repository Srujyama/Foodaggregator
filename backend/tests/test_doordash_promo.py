"""The original DoorDash promo regex used `[^"]*` which greedily consumed
the entire next-RSC-stream legalese block when '$0 delivery fees' appeared
inside DoorDash's terms-and-conditions text. This test reconstructs that
exact pathological input and asserts the new bounded match keeps the promo
short."""

import re


# The replacement regex from doordash.py:
PROMO_FREE_RE = re.compile(
    r'\$0(?:\.00)?\s+[Dd]elivery\s+[Ff]ees?\b[^\n.]{0,40}',
)
PROMO_NAMED_RE = re.compile(r'"promotion_delivery_fee":"([^"]{1,200})"')


def test_named_promo_matches_short_string():
    text = '...,"promotion_delivery_fee":"Free delivery on $20+","next":'
    m = PROMO_NAMED_RE.search(text)
    assert m
    assert m.group(1) == "Free delivery on $20+"


def test_named_promo_caps_at_200_chars():
    huge = "x" * 5000
    text = f'"promotion_delivery_fee":"{huge}",rest'
    # The bounded regex must NOT match (the captured value exceeds 200 chars
    # and there's no closing quote within range), so we fall through.
    assert PROMO_NAMED_RE.search(text) is None


def test_free_delivery_match_does_not_include_legalese_blob():
    """This is the literal kind of input that broke the old parser. The text
    includes '$0 delivery fees' immediately followed by giant legalese ending
    in a quote ~5KB later. The old `[^"]*` would slurp all of it."""
    legalese = (
        "and 10% off due to\nreduced service fees only apply when eligible "
        "order subtotal\nminimum met on DashPass eligible orders. All orders "
        "subject to\navailability. No cash value. Non-transferable.22:T460,"
        "Free trial only available to new members who have not previously "
        "redeemed free trial. Must be an eligible DashPass member ..."
    )
    text = f'"foo":"$0 delivery fees {legalese}"'
    m = PROMO_FREE_RE.search(text)
    assert m, "expected to find the free-delivery snippet"
    matched = m.group(0)
    # Must stop at the first sentence terminator or 40 chars of context.
    assert len(matched) <= 60, f"promo match too long: {len(matched)} chars: {matched!r}"
    assert "Non-transferable" not in matched
    assert "Referrer" not in matched
    assert "DashPass" not in matched
    # Newline must not be in the match (regex denies \n).
    assert "\n" not in matched


def test_free_delivery_match_handles_real_case_from_production():
    """Reproduces the exact failure mode we saw in /api/restaurant for Taco
    Bell at 19713: the delivery_fee promo string carried 5KB of legalese
    plus stream markers like '22:T460,' into the API response."""
    text = (
        '"description":"$0 delivery fees and 10% off due to\\n'
        'reduced service fees only apply when eligible order subtotal..."'
    )
    m = PROMO_FREE_RE.search(text)
    assert m
    matched = m.group(0)
    assert "T460" not in matched
    assert "subtotal" not in matched
