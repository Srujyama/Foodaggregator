import { describe, it, expect } from 'vitest'
// Shared JS/Python parity vectors — the backend runs the SAME file in
// backend/tests/test_pricing.py::test_meal_cost_parity_vectors.
import vectors from '../../backend/tests/fixtures/meal_cost_vectors.json'
import {
  computeServiceFee,
  computeSmallOrderFee,
  estimateMealCost,
  taxRateForLocation,
} from './mealCost.js'

describe('estimateMealCost parity with backend vectors', () => {
  it('loads the full shared vector set', () => {
    expect(vectors.length).toBeGreaterThanOrEqual(12)
  })

  for (const vec of vectors) {
    it(`matches the backend for '${vec.name}'`, () => {
      const est = estimateMealCost(
        vec.schedule,
        vec.subtotal,
        vec.mode ?? 'delivery',
        vec.fallback_tax_rate_pct ?? null,
      )
      for (const [key, expected] of Object.entries(vec.expected)) {
        expect(est[key], `key '${key}' of vector '${vec.name}'`).toEqual(expected)
      }
    })
  }
})

describe('computeServiceFee', () => {
  it('uses service_fee_flat as the floor when service_fee_min is absent', () => {
    const schedule = { service_fee_pct: 10, service_fee_flat: 3 }
    expect(computeServiceFee(schedule, 10)).toBe(3) // 10% of $10 = $1 < $3 floor
    expect(computeServiceFee(schedule, 100)).toBe(10)
  })

  it('returns null with no fee data at all', () => {
    expect(computeServiceFee({}, 25)).toBeNull()
    expect(computeServiceFee(null, 25)).toBeNull()
  })
})

describe('computeSmallOrderFee', () => {
  it('needs both the fee and the threshold', () => {
    expect(computeSmallOrderFee({ small_order_fee: 2.5 }, 5)).toBe(0)
    expect(computeSmallOrderFee({ small_order_threshold: 10 }, 5)).toBe(0)
    expect(
      computeSmallOrderFee({ small_order_fee: 2.5, small_order_threshold: 10 }, 5),
    ).toBe(2.5)
  })

  it('does not trigger at or above the threshold', () => {
    const schedule = { small_order_fee: 2.5, small_order_threshold: 10 }
    expect(computeSmallOrderFee(schedule, 10)).toBe(0)
    expect(computeSmallOrderFee(schedule, 25)).toBe(0)
  })
})

describe('taxRateForLocation', () => {
  it('parses a trailing 2-letter abbreviation after a comma', () => {
    expect(taxRateForLocation('2100 University Ave, Berkeley, CA')).toEqual({
      statecode: 'CA',
      ratePct: 8.75,
    })
  })

  it('parses a lowercase abbreviation token', () => {
    expect(taxRateForLocation('brooklyn ny')).toEqual({
      statecode: 'NY',
      ratePct: 8.5,
    })
  })

  it('takes the LAST abbreviation token (addresses end with the state)', () => {
    // "la" (Louisiana) appears first but California is the actual state.
    expect(taxRateForLocation('la jolla ca')?.statecode).toBe('CA')
  })

  it('parses a full state name, preferring the longer match', () => {
    expect(taxRateForLocation('Austin, Texas')).toEqual({
      statecode: 'TX',
      ratePct: 8.2,
    })
    expect(taxRateForLocation('Charleston, West Virginia')?.statecode).toBe('WV')
    expect(taxRateForLocation('Seattle, Washington')?.statecode).toBe('WA')
    expect(taxRateForLocation('Washington, DC')?.statecode).toBe('DC')
  })

  it('parses a bare 5-digit ZIP via the ZIP3 table', () => {
    expect(taxRateForLocation('94704')).toEqual({ statecode: 'CA', ratePct: 8.75 })
    expect(taxRateForLocation('10001')?.statecode).toBe('NY')
    expect(taxRateForLocation('97201')).toEqual({ statecode: 'OR', ratePct: 0 })
    expect(taxRateForLocation('60614-1234')?.statecode).toBe('IL')
  })

  it('uses the last ZIP so street numbers do not win', () => {
    expect(taxRateForLocation('12345 Elm Street 78701')?.statecode).toBe('TX')
  })

  it('returns null for garbage, empty, and non-string input', () => {
    expect(taxRateForLocation('???!!!')).toBeNull()
    expect(taxRateForLocation('somewhere far away')).toBeNull()
    expect(taxRateForLocation('')).toBeNull()
    expect(taxRateForLocation(null)).toBeNull()
    expect(taxRateForLocation(undefined)).toBeNull()
    expect(taxRateForLocation(12345)).toBeNull()
  })

  it('returns null for a ZIP prefix outside every USPS range', () => {
    expect(taxRateForLocation('00000')).toBeNull()
  })

  it('lets an explicit ZIP beat an embedded 2-letter word', () => {
    // "in" (Indiana) is embedded in the name; the ZIP is the real evidence.
    expect(taxRateForLocation('in-n-out 94103')?.statecode).toBe('CA')
  })

  it('rejects lowercase mid-string city particles as state codes', () => {
    expect(taxRateForLocation('La Jolla, San Diego')).toBeNull()
    expect(taxRateForLocation('la mesa')).toBeNull()
    expect(taxRateForLocation('De Pere')).toBeNull()
    expect(taxRateForLocation('somewhere in the void')).toBeNull()
  })

  it('still accepts credible abbreviation positions', () => {
    expect(taxRateForLocation('la jolla ca')?.statecode).toBe('CA') // final token
    expect(taxRateForLocation('Berkeley, CA 94704')?.statecode).toBe('CA')
    expect(taxRateForLocation('123 Main St, WA')?.statecode).toBe('WA') // after comma
  })
})
