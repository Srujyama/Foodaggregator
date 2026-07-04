import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  getRecentSearches, addRecentSearch, clearRecentSearches,
  getLastLocation, setLastLocation,
} from './recentSearches.js'

const KEY = 'fa.recentSearches'
const LOC_KEY = 'fa.lastLocation'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('getRecentSearches', () => {
  it('returns [] when nothing is stored', () => {
    expect(getRecentSearches()).toEqual([])
  })

  it('returns [] for corrupt JSON instead of throwing', () => {
    localStorage.setItem(KEY, '{not valid json!!')
    expect(getRecentSearches()).toEqual([])
  })

  it('returns [] when stored value is not an array', () => {
    localStorage.setItem(KEY, JSON.stringify({ q: 'pizza' }))
    expect(getRecentSearches()).toEqual([])
  })

  it('drops malformed entries inside an otherwise valid array', () => {
    localStorage.setItem(
      KEY,
      JSON.stringify([{ q: 'pizza', location: 'NYC', mode: 'delivery', ts: 1 }, null, { q: 42 }]),
    )
    const out = getRecentSearches()
    expect(out).toHaveLength(1)
    expect(out[0].q).toBe('pizza')
  })

  it('returns [] when localStorage access throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(getRecentSearches()).toEqual([])
  })
})

describe('addRecentSearch', () => {
  it('adds entries newest-first with a ts stamp', () => {
    addRecentSearch({ q: 'pizza', location: 'NYC', mode: 'delivery' })
    addRecentSearch({ q: 'sushi', location: 'NYC', mode: 'pickup' })
    const out = getRecentSearches()
    expect(out.map((e) => e.q)).toEqual(['sushi', 'pizza'])
    expect(out[0]).toMatchObject({ q: 'sushi', location: 'NYC', mode: 'pickup' })
    expect(typeof out[0].ts).toBe('number')
  })

  it('dedupes case-insensitively on q+location and moves the entry to the front', () => {
    addRecentSearch({ q: 'Pizza', location: 'New York', mode: 'delivery' })
    addRecentSearch({ q: 'sushi', location: 'New York', mode: 'delivery' })
    addRecentSearch({ q: 'PIZZA', location: 'new york', mode: 'pickup' })
    const out = getRecentSearches()
    expect(out).toHaveLength(2)
    expect(out[0]).toMatchObject({ q: 'PIZZA', location: 'new york', mode: 'pickup' })
    expect(out[1].q).toBe('sushi')
  })

  it('does not dedupe when only one of q/location matches', () => {
    addRecentSearch({ q: 'pizza', location: 'NYC', mode: 'delivery' })
    addRecentSearch({ q: 'pizza', location: 'LA', mode: 'delivery' })
    expect(getRecentSearches()).toHaveLength(2)
  })

  it('caps the list at 8 entries, dropping the oldest', () => {
    for (let i = 0; i < 10; i++) {
      addRecentSearch({ q: `food${i}`, location: 'NYC', mode: 'delivery' })
    }
    const out = getRecentSearches()
    expect(out).toHaveLength(8)
    expect(out[0].q).toBe('food9')
    expect(out[7].q).toBe('food2')
  })

  it('recovers from corrupt stored JSON', () => {
    localStorage.setItem(KEY, 'garbage')
    expect(() => addRecentSearch({ q: 'pizza', location: 'NYC', mode: 'delivery' })).not.toThrow()
    expect(getRecentSearches()).toHaveLength(1)
  })

  it('does not throw when localStorage writes fail', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })
    expect(() => addRecentSearch({ q: 'pizza', location: 'NYC', mode: 'delivery' })).not.toThrow()
  })
})

describe('lastLocation', () => {
  it('returns "" when nothing is stored', () => {
    expect(getLastLocation()).toBe('')
  })

  it('round-trips a location, trimming whitespace', () => {
    setLastLocation('  Berkeley, CA  ')
    expect(getLastLocation()).toBe('Berkeley, CA')
  })

  it('ignores blank or whitespace-only values', () => {
    setLastLocation('NYC')
    setLastLocation('   ')
    setLastLocation('')
    expect(getLastLocation()).toBe('NYC')
  })

  it('falls back to the newest recent search location when the key is unset', () => {
    addRecentSearch({ q: 'pizza', location: 'Berkeley, CA', mode: 'delivery' })
    expect(localStorage.getItem(LOC_KEY)).toBeNull()
    expect(getLastLocation()).toBe('Berkeley, CA')
  })

  it('prefers the explicit key over the recent-search fallback', () => {
    addRecentSearch({ q: 'pizza', location: 'Berkeley, CA', mode: 'delivery' })
    setLastLocation('Oakland, CA')
    expect(getLastLocation()).toBe('Oakland, CA')
  })

  it('returns "" when reading the last-location key throws', () => {
    // A value is stored, but reading the dedicated key throws. getLastLocation's
    // catch must short-circuit to '' rather than fall through to the recent-search
    // fallback — so scope the throw to LOC_KEY to prove the early return.
    localStorage.setItem(LOC_KEY, 'NYC')
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key) => {
      if (key === LOC_KEY) throw new Error('denied')
      return null
    })
    expect(getLastLocation()).toBe('')
  })

  it('does not throw when localStorage write fails', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })
    expect(() => setLastLocation('NYC')).not.toThrow()
  })
})

describe('clearRecentSearches', () => {
  it('empties the list', () => {
    addRecentSearch({ q: 'pizza', location: 'NYC', mode: 'delivery' })
    clearRecentSearches()
    expect(getRecentSearches()).toEqual([])
    expect(localStorage.getItem(KEY)).toBeNull()
  })

  it('does not throw when localStorage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(() => clearRecentSearches()).not.toThrow()
  })
})
