import { getApiUrl } from './utils.js'

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function fetchWithRetry(url, options = {}) {
  const { retries = 2, retryDelay = 800, timeout = 15000, ...fetchOpts } = options

  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, { ...fetchOpts, signal: controller.signal })
      clearTimeout(timeoutId)

      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new ApiError(text || res.statusText, res.status)
      }
      return await res.json()
    } catch (err) {
      if (err.name === 'AbortError') throw new ApiError('Request timed out', 504)
      if (err instanceof ApiError) throw err
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, retryDelay * (attempt + 1)))
        continue
      }
      throw err
    }
  }
}

export async function searchRestaurants(query, location, params = {}) {
  const url = new URL(`${getApiUrl()}/api/search`)
  url.searchParams.set('q', query)
  url.searchParams.set('location', location)
  if (params.limit) url.searchParams.set('limit', params.limit)
  if (params.platforms) url.searchParams.set('platforms', params.platforms)
  return fetchWithRetry(url.toString())
}

export async function getRestaurant(name, location) {
  const url = new URL(`${getApiUrl()}/api/restaurant/${encodeURIComponent(name)}`)
  url.searchParams.set('location', location)
  return fetchWithRetry(url.toString())
}

export async function getDeals(location, limit = 10) {
  const url = new URL(`${getApiUrl()}/api/deals`)
  url.searchParams.set('location', location)
  url.searchParams.set('limit', limit)
  return fetchWithRetry(url.toString())
}

export async function getHealth() {
  return fetchWithRetry(`${getApiUrl()}/health`)
}
