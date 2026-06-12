const STORAGE_KEY = 'fa.recentSearches'
const MAX_RECENTS = 8

export function getRecentSearches() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((e) => e && typeof e.q === 'string' && typeof e.location === 'string')
  } catch {
    return []
  }
}

export function addRecentSearch({ q, location, mode }) {
  try {
    const key = `${q}`.toLowerCase() + '|' + `${location}`.toLowerCase()
    const rest = getRecentSearches().filter(
      (e) => `${e.q}`.toLowerCase() + '|' + `${e.location}`.toLowerCase() !== key,
    )
    const next = [{ q, location, mode, ts: Date.now() }, ...rest].slice(0, MAX_RECENTS)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // storage unavailable or quota exceeded — recents are best-effort
  }
}

export function clearRecentSearches() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore — nothing to clean up if storage is unavailable
  }
}
