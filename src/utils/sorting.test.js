import { describe, it, expect } from 'vitest'
import {
  computeTotalCost,
  computePickupCost,
  computeCost,
  rankByBestDeal,
  getBestDealPlatform,
  getSavings,
  getMenuSavings,
  getCheapestMenuPlatform,
  getBestRating,
  getFastestEta,
  hasPromo,
  isOpenNow,
  sortResults,
  filterResults,
  hasActiveFilters,
  EMPTY_FILTERS,
} from './sorting.js'

const _platform = (overrides = {}) => ({
  platform: 'uber_eats',
  delivery_fee: 0,
  service_fee: 0,
  pickup_fee: 0,
  pickup_service_fee: 0,
  estimated_delivery_minutes: 30,
  estimated_pickup_minutes: 15,
  ...overrides,
})

describe('computeTotalCost', () => {
  it('sums delivery + service fees', () => {
    expect(computeTotalCost(_platform({ delivery_fee: 2.99, service_fee: 1.5 }))).toBeCloseTo(4.49)
  })
  it('handles missing fields as 0', () => {
    expect(computeTotalCost({})).toBe(0)
  })
})

describe('computePickupCost', () => {
  it('sums pickup fees', () => {
    expect(computePickupCost(_platform({ pickup_fee: 0, pickup_service_fee: 0.99 }))).toBeCloseTo(0.99)
  })
})

describe('computeCost respects mode', () => {
  it('returns delivery cost for mode=delivery', () => {
    const p = _platform({ delivery_fee: 5, pickup_fee: 99 })
    expect(computeCost(p, 'delivery')).toBe(5)
  })
  it('returns pickup cost for mode=pickup', () => {
    const p = _platform({ delivery_fee: 99, pickup_fee: 1 })
    expect(computeCost(p, 'pickup')).toBe(1)
  })
})

describe('rankByBestDeal', () => {
  it('sorts platforms ascending by total cost', () => {
    const result = {
      platforms: [
        _platform({ platform: 'a', delivery_fee: 5 }),
        _platform({ platform: 'b', delivery_fee: 1 }),
        _platform({ platform: 'c', delivery_fee: 3 }),
      ],
    }
    expect(rankByBestDeal(result).map((p) => p.platform)).toEqual(['b', 'c', 'a'])
  })

  it('does not mutate the input array', () => {
    const platforms = [
      _platform({ platform: 'a', delivery_fee: 5 }),
      _platform({ platform: 'b', delivery_fee: 1 }),
    ]
    const original = [...platforms]
    rankByBestDeal({ platforms })
    expect(platforms).toEqual(original)
  })
})

describe('getBestDealPlatform', () => {
  it('returns null when no platforms', () => {
    expect(getBestDealPlatform({ platforms: [] })).toBeNull()
  })
  it('returns the cheapest platform', () => {
    const result = {
      platforms: [
        _platform({ platform: 'a', delivery_fee: 5 }),
        _platform({ platform: 'b', delivery_fee: 1 }),
      ],
    }
    expect(getBestDealPlatform(result).platform).toBe('b')
  })
})

describe('getSavings', () => {
  it('returns 0 with one platform', () => {
    expect(getSavings({ platforms: [_platform()] })).toBe(0)
  })
  it('returns max - min total cost', () => {
    const result = {
      platforms: [
        _platform({ delivery_fee: 1, service_fee: 0 }),
        _platform({ delivery_fee: 5, service_fee: 1 }),
      ],
    }
    expect(getSavings(result)).toBeCloseTo(5)
  })
})

describe('getMenuSavings', () => {
  it('returns 0 when there is no comparison', () => {
    expect(getMenuSavings({})).toBe(0)
    expect(getMenuSavings({ menu_comparison: [] })).toBe(0)
  })
  it('sums price differences', () => {
    expect(getMenuSavings({
      menu_comparison: [
        { price_difference: 0.5 },
        { price_difference: 1.25 },
      ],
    })).toBeCloseTo(1.75)
  })
})

const _agg = (name, platforms, extra = {}) => ({
  restaurant_name: name,
  platforms,
  ...extra,
})

describe('getBestRating / getFastestEta', () => {
  it('returns the max rating across platforms, ignoring missing', () => {
    const agg = _agg('A', [
      _platform({ rating: 4.2 }),
      _platform({ rating: null }),
      _platform({ rating: 4.8 }),
    ])
    expect(getBestRating(agg)).toBe(4.8)
  })
  it('returns 0 when no platform has a rating', () => {
    expect(getBestRating(_agg('A', [_platform({ rating: null })]))).toBe(0)
  })
  it('returns the fastest ETA for the active mode', () => {
    const agg = _agg('A', [
      _platform({ estimated_delivery_minutes: 40, estimated_pickup_minutes: 10 }),
      _platform({ estimated_delivery_minutes: 25, estimated_pickup_minutes: 20 }),
    ])
    expect(getFastestEta(agg, 'delivery')).toBe(25)
    expect(getFastestEta(agg, 'pickup')).toBe(10)
  })
  it('returns Infinity when no ETAs exist (sorts last)', () => {
    expect(getFastestEta(_agg('A', [_platform({ estimated_delivery_minutes: null })]))).toBe(Infinity)
  })
})

describe('hasPromo / isOpenNow', () => {
  it('detects a promo on any platform', () => {
    expect(hasPromo(_agg('A', [_platform(), _platform({ promo_text: '20% off' })]))).toBe(true)
    expect(hasPromo(_agg('A', [_platform()]))).toBe(false)
  })
  it('treats unknown open status as open', () => {
    expect(isOpenNow(_agg('A', [_platform()]))).toBe(true)
  })
  it('is closed only when every platform is explicitly closed', () => {
    expect(isOpenNow(_agg('A', [
      _platform({ is_open: false }),
      _platform({ accepting_orders: false }),
    ]))).toBe(false)
    expect(isOpenNow(_agg('A', [
      _platform({ is_open: false }),
      _platform({ is_open: true }),
    ]))).toBe(true)
  })
})

describe('sortResults', () => {
  const cheapFast = _agg('CheapFast', [
    _platform({ delivery_fee: 1, rating: 3.5, estimated_delivery_minutes: 15 }),
  ])
  const pricyTopRated = _agg('PricyTopRated', [
    _platform({ delivery_fee: 8, rating: 4.9, estimated_delivery_minutes: 50 }),
    _platform({ platform: 'doordash', delivery_fee: 9, estimated_delivery_minutes: 45 }),
  ])
  const midSaver = _agg(
    'MidSaver',
    [
      _platform({ delivery_fee: 4, rating: 4.0, estimated_delivery_minutes: 30 }),
      _platform({ platform: 'grubhub', delivery_fee: 7, estimated_delivery_minutes: 35 }),
    ],
    { menu_comparison: [{ price_difference: 2.5 }] },
  )
  const results = [pricyTopRated, midSaver, cheapFast]

  it('best keeps the backend order', () => {
    expect(sortResults(results, 'best').map((r) => r.restaurant_name))
      .toEqual(['PricyTopRated', 'MidSaver', 'CheapFast'])
  })
  it('fees sorts by cheapest best-deal platform', () => {
    expect(sortResults(results, 'fees').map((r) => r.restaurant_name))
      .toEqual(['CheapFast', 'MidSaver', 'PricyTopRated'])
  })
  it('rating sorts by best rating descending', () => {
    expect(sortResults(results, 'rating')[0].restaurant_name).toBe('PricyTopRated')
  })
  it('eta sorts by fastest option ascending', () => {
    expect(sortResults(results, 'eta')[0].restaurant_name).toBe('CheapFast')
  })
  it('platforms sorts by platform count, stable for ties', () => {
    const sorted = sortResults(results, 'platforms').map((r) => r.restaurant_name)
    expect(sorted).toEqual(['PricyTopRated', 'MidSaver', 'CheapFast'])
  })
  it('savings combines fee savings and menu savings', () => {
    // MidSaver: $3 fee spread + $2.50 menu = $5.50; PricyTopRated: $1 fee spread
    expect(sortResults(results, 'savings')[0].restaurant_name).toBe('MidSaver')
  })
  it('does not mutate the input', () => {
    const copy = [...results]
    sortResults(results, 'fees')
    expect(results).toEqual(copy)
  })
})

describe('filterResults', () => {
  const ubered = _agg('OnUber', [_platform({ platform: 'uber_eats' })])
  const doordashed = _agg('OnDD', [
    _platform({ platform: 'doordash', promo_text: 'Free delivery' }),
    _platform({ platform: 'grubhub', is_open: false }),
  ])
  const closed = _agg('Closed', [_platform({ platform: 'uber_eats', is_open: false, accepting_orders: false })])
  const results = [ubered, doordashed, closed]

  it('returns everything when no filters are active', () => {
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false)
    expect(filterResults(results, EMPTY_FILTERS)).toEqual(results)
  })
  it('filters by platform membership', () => {
    const out = filterResults(results, { ...EMPTY_FILTERS, platforms: ['doordash'] })
    expect(out.map((r) => r.restaurant_name)).toEqual(['OnDD'])
  })
  it('openNow drops fully-closed restaurants only', () => {
    const out = filterResults(results, { ...EMPTY_FILTERS, openNow: true })
    expect(out.map((r) => r.restaurant_name)).toEqual(['OnUber', 'OnDD'])
  })
  it('promoOnly keeps restaurants with any promo', () => {
    const out = filterResults(results, { ...EMPTY_FILTERS, promoOnly: true })
    expect(out.map((r) => r.restaurant_name)).toEqual(['OnDD'])
  })
  it('multiOnly keeps cross-platform matches', () => {
    const out = filterResults(results, { ...EMPTY_FILTERS, multiOnly: true })
    expect(out.map((r) => r.restaurant_name)).toEqual(['OnDD'])
  })
  it('combines filters with AND semantics', () => {
    const out = filterResults(results, {
      ...EMPTY_FILTERS, platforms: ['uber_eats'], openNow: true,
    })
    expect(out.map((r) => r.restaurant_name)).toEqual(['OnUber'])
  })
})

describe('getCheapestMenuPlatform', () => {
  it('returns null when no markup data', () => {
    expect(getCheapestMenuPlatform({})).toBeNull()
    expect(getCheapestMenuPlatform({ avg_menu_markup_by_platform: {} })).toBeNull()
  })
  it('returns the lowest-markup platform', () => {
    const result = {
      avg_menu_markup_by_platform: { uber_eats: 6.7, doordash: 2.5, grubhub: 6.2 },
    }
    expect(getCheapestMenuPlatform(result)).toBe('doordash')
  })
})
