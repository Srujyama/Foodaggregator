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
