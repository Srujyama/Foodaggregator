import { describe, it, expect, vi, afterEach } from 'vitest'
import { getCurrentLocationLabel } from './geolocate.js'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubGeolocation(coords) {
  vi.stubGlobal('navigator', {
    geolocation: {
      getCurrentPosition: (success) => success({ coords }),
    },
  })
}

function stubFetchAddress(address) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ address }),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('getCurrentLocationLabel', () => {
  it('returns the postcode when present', async () => {
    stubGeolocation({ latitude: 40.7128, longitude: -74.006 })
    const fetchMock = stubFetchAddress({ postcode: '10001', city: 'New York', state: 'New York' })

    await expect(getCurrentLocationLabel()).resolves.toBe('10001')

    const url = fetchMock.mock.calls[0][0]
    expect(url).toContain('nominatim.openstreetmap.org/reverse')
    expect(url).toContain('lat=40.7128')
    expect(url).toContain('lon=-74.006')
    expect(url).toContain('format=json')
  })

  it('falls back to "City, ST" when there is no postcode', async () => {
    stubGeolocation({ latitude: 37.8716, longitude: -122.2728 })
    stubFetchAddress({ city: 'Berkeley', state: 'California', 'ISO3166-2-lvl4': 'US-CA' })

    await expect(getCurrentLocationLabel()).resolves.toBe('Berkeley, CA')
  })

  it('uses town/village and the full state name when no ISO abbreviation exists', async () => {
    stubGeolocation({ latitude: 44.0, longitude: -72.0 })
    stubFetchAddress({ town: 'Stowe', state: 'Vermont' })

    await expect(getCurrentLocationLabel()).resolves.toBe('Stowe, Vermont')
  })

  it('falls back to rounded coordinates when reverse geocoding fails', async () => {
    stubGeolocation({ latitude: 40.712776, longitude: -74.005974 })
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))

    await expect(getCurrentLocationLabel()).resolves.toBe('40.713,-74.006')
  })

  it('rejects when the user denies the permission prompt', async () => {
    vi.stubGlobal('navigator', {
      geolocation: {
        getCurrentPosition: (success, error) =>
          error({ code: 1, message: 'User denied Geolocation' }),
      },
    })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await expect(getCurrentLocationLabel()).rejects.toThrow('User denied Geolocation')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects when geolocation is unsupported', async () => {
    vi.stubGlobal('navigator', {})

    await expect(getCurrentLocationLabel()).rejects.toThrow(/not supported/i)
  })
})
