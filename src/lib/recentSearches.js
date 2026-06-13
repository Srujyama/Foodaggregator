const STORAGE_KEY = 'fa.recentSearches'
const LAST_LOCATION_KEY = 'fa.lastLocation'
const MAX_RECENTS = 8

// The location the user last searched with, persisted across sessions. Lets
// the home page's trending chips and the navbar run a search without making
// the user re-type where they are. Best-effort: storage may be unavailable.
// Falls back to the newest recent search's location so returning users get a
// working location even before the dedicated key was ever written.
export function getLastLocation() {
  try {
    const explicit = localStorage.getItem(LAST_LOCATION_KEY)
    if (explicit) return explicit
  } catch {
    return ''
  }
  return getRecentSearches()[0]?.location || ''
}

export function setLastLocation(location) {
  try {
    if (location && location.trim()) {
      localStorage.setItem(LAST_LOCATION_KEY, location.trim())
    }
  } catch {
    // ignore — last-location memory is best-effort
  }
}

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
