import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { searchRestaurants } from '../lib/api.js'
import { useSearchContext } from '../context/SearchContext.jsx'

export function useSearch() {
  const navigate = useNavigate()
  const { query, location, setResults, setLoading, setError, setQuery, setLocation } =
    useSearchContext()

  const search = useCallback(
    async (q, loc) => {
      const searchQuery = q ?? query
      const searchLocation = loc ?? location

      if (!searchQuery.trim() || !searchLocation.trim()) {
        toast.error('Please enter both a food/restaurant and a location.')
        return
      }

      setLoading(true)
      setError(null)

      try {
        const data = await searchRestaurants(searchQuery, searchLocation)
        setResults(data.results || [])
        navigate(`/results?q=${encodeURIComponent(searchQuery)}&location=${encodeURIComponent(searchLocation)}`)
      } catch (err) {
        const msg = err.message || 'Search failed. Please try again.'
        setError(msg)
        toast.error(msg)
      } finally {
        setLoading(false)
      }
    },
    [query, location, navigate, setResults, setLoading, setError],
  )

  return { search, setQuery, setLocation }
}
