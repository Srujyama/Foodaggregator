import { describe, it, expect } from 'vitest'
import {
  parseQueryState,
  applyQueryState,
  SORT_PARAM,
  PLATFORMS_PARAM,
  OPEN_PARAM,
  PROMO_PARAM,
  MULTI_PARAM,
  DEFAULT_SORT,
  KNOWN_PLATFORM_IDS,
} from './queryState.js'
import { EMPTY_FILTERS } from './sorting.js'

const params = (init = '') => new URLSearchParams(init)

describe('parseQueryState', () => {
  it('returns defaults for empty params', () => {
    expect(parseQueryState(params())).toEqual({
      sortKey: DEFAULT_SORT,
      filters: EMPTY_FILTERS,
    })
  })

  it('reads a valid sort key', () => {
    expect(parseQueryState(params('sort=fees')).sortKey).toBe('fees')
    expect(parseQueryState(params('sort=eta')).sortKey).toBe('eta')
  })

  it('falls back to default sort on garbage', () => {
    expect(parseQueryState(params('sort=banana')).sortKey).toBe(DEFAULT_SORT)
    expect(parseQueryState(params('sort=')).sortKey).toBe(DEFAULT_SORT)
  })

  it('reads a comma list of platforms', () => {
    const { filters } = parseQueryState(params('fplat=doordash,grubhub'))
    expect(filters.platforms).toEqual(['doordash', 'grubhub'])
  })

  it('accepts every known platform id', () => {
    const { filters } = parseQueryState(params(`fplat=${KNOWN_PLATFORM_IDS.join(',')}`))
    expect(filters.platforms).toEqual(KNOWN_PLATFORM_IDS)
  })

  it('drops unknown platforms silently', () => {
    expect(parseQueryState(params('fplat=netflix')).filters.platforms).toEqual([])
    expect(parseQueryState(params('fplat=netflix,doordash,hulu')).filters.platforms)
      .toEqual(['doordash'])
  })

  it('dedupes repeated platforms', () => {
    expect(parseQueryState(params('fplat=caviar,caviar')).filters.platforms).toEqual(['caviar'])
  })

  it('reads toggle params only when set to 1', () => {
    const { filters } = parseQueryState(params('open=1&promo=1&multi=1'))
    expect(filters.openNow).toBe(true)
    expect(filters.promoOnly).toBe(true)
    expect(filters.multiOnly).toBe(true)

    const off = parseQueryState(params('open=0&promo=true&multi=yes')).filters
    expect(off.openNow).toBe(false)
    expect(off.promoOnly).toBe(false)
    expect(off.multiOnly).toBe(false)
  })
})

describe('applyQueryState', () => {
  it('omits all params at default values', () => {
    const next = applyQueryState(params(), DEFAULT_SORT, EMPTY_FILTERS)
    expect(next.toString()).toBe('')
  })

  it('sets non-default sort and filters', () => {
    const next = applyQueryState(params(), 'rating', {
      platforms: ['uber_eats', 'gopuff'],
      openNow: true,
      promoOnly: false,
      multiOnly: true,
    })
    expect(next.get(SORT_PARAM)).toBe('rating')
    expect(next.get(PLATFORMS_PARAM)).toBe('uber_eats,gopuff')
    expect(next.get(OPEN_PARAM)).toBe('1')
    expect(next.get(PROMO_PARAM)).toBe(null)
    expect(next.get(MULTI_PARAM)).toBe('1')
  })

  it('removes previously set params when state returns to defaults', () => {
    const prev = params('sort=fees&fplat=doordash&open=1&promo=1&multi=1')
    const next = applyQueryState(prev, DEFAULT_SORT, EMPTY_FILTERS)
    expect(next.toString()).toBe('')
  })

  it('preserves unrelated params (q, location, mode)', () => {
    const prev = params('q=pizza&location=Berkeley%2C+CA&mode=pickup')
    const next = applyQueryState(prev, 'savings', { ...EMPTY_FILTERS, promoOnly: true })
    expect(next.get('q')).toBe('pizza')
    expect(next.get('location')).toBe('Berkeley, CA')
    expect(next.get('mode')).toBe('pickup')
    expect(next.get(SORT_PARAM)).toBe('savings')
    expect(next.get(PROMO_PARAM)).toBe('1')

    const cleared = applyQueryState(next, DEFAULT_SORT, EMPTY_FILTERS)
    expect(cleared.get('q')).toBe('pizza')
    expect(cleared.get('location')).toBe('Berkeley, CA')
    expect(cleared.get('mode')).toBe('pickup')
    expect(cleared.get(SORT_PARAM)).toBe(null)
  })

  it('does not mutate the input params', () => {
    const prev = params('q=tacos')
    applyQueryState(prev, 'eta', { ...EMPTY_FILTERS, openNow: true })
    expect(prev.toString()).toBe('q=tacos')
  })

  it('round-trips through parseQueryState', () => {
    const state = {
      sortKey: 'platforms',
      filters: {
        platforms: ['seamless', 'eatstreet'],
        openNow: false,
        promoOnly: true,
        multiOnly: false,
      },
    }
    const next = applyQueryState(params('q=sushi'), state.sortKey, state.filters)
    expect(parseQueryState(next)).toEqual(state)
  })

  it('round-trips the default state', () => {
    const next = applyQueryState(params(), DEFAULT_SORT, EMPTY_FILTERS)
    expect(parseQueryState(next)).toEqual({ sortKey: DEFAULT_SORT, filters: EMPTY_FILTERS })
  })
})
