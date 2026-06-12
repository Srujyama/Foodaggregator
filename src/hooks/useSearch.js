import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { searchRestaurants } from '../lib/api.js'
import { addRecentSearch } from '../lib/recentSearches.js'
import { useSearchContext } from '../context/SearchContext.jsx'

export function useSearch() {
  const navigate = useNavigate()
  const {
    query, location, mode, setResults, setLoading, setError,
    setQuery, setLocation, setMode, setPlatformStatus,
  } = useSearchContext()

  const search = useCallback(
    async (q, loc, m) => {
      const searchQuery = q ?? query
      const searchLocation = loc ?? location
      const searchMode = m ?? mode

      if (!searchQuery.trim() || !searchLocation.trim()) {
        toast.error('Please enter both a food/restaurant and a location.')
        return
      }

      setLoading(true)
      setError(null)

      try {
        const data = await searchRestaurants(searchQuery, searchLocation, { mode: searchMode })
        setResults(data.results || [])
        addRecentSearch({ q: searchQuery, location: searchLocation, mode: searchMode })
        setPlatformStatus(data.platform_status || {})
        // Only navigate when the search target actually changed. The Results
        // page re-runs search() on mount, and unconditionally rebuilding the
        // URL here wiped sort/filter params (?sort=…&fplat=…) from deep links.
        const current = new URLSearchParams(window.location.search)
        const alreadyThere =
          window.location.pathname === '/results' &&
          current.get('q') === searchQuery &&
          current.get('location') === searchLocation &&
          (current.get('mode') || 'delivery') === searchMode
        if (!alreadyThere) {
          navigate(`/results?q=${encodeURIComponent(searchQuery)}&location=${encodeURIComponent(searchLocation)}&mode=${searchMode}`)
        }
      } catch (err) {
        const msg = err.message || 'Search failed. Please try again.'
        setError(msg)
        toast.error(msg)
      } finally {
        setLoading(false)
      }
    },
    [query, location, mode, navigate, setResults, setLoading, setError, setPlatformStatus],
  )

  return { search, setQuery, setLocation, setMode }
}
