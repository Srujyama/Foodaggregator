import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { searchRestaurants } from '../lib/api.js'
import { useSearchContext } from '../context/SearchContext.jsx'

export function useSearch() {
  const navigate = useNavigate()
  const { query, location, mode, setResults, setLoading, setError, setQuery, setLocation, setMode } =
    useSearchContext()

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
        navigate(`/results?q=${encodeURIComponent(searchQuery)}&location=${encodeURIComponent(searchLocation)}&mode=${searchMode}`)
      } catch (err) {
        const msg = err.message || 'Search failed. Please try again.'
        setError(msg)
        toast.error(msg)
      } finally {
        setLoading(false)
      }
    },
    [query, location, mode, navigate, setResults, setLoading, setError],
  )

  return { search, setQuery, setLocation, setMode }
}
