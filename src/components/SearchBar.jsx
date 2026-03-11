import { useState, useRef, useEffect } from 'react'
import { Search, MapPin, Loader2 } from 'lucide-react'
import { useSearch } from '../hooks/useSearch.js'
import { useSearchContext } from '../context/SearchContext.jsx'

export default function SearchBar({ large = false, initialQuery = '', initialLocation = '' }) {
  const { loading } = useSearchContext()
  const { search, setQuery, setLocation } = useSearch()
  const [localQuery, setLocalQuery] = useState(initialQuery)
  const [localLocation, setLocalLocation] = useState(initialLocation)
  const debounceRef = useRef(null)

  useEffect(() => {
    setLocalQuery(initialQuery)
    setLocalLocation(initialLocation)
  }, [initialQuery, initialLocation])

  const handleQueryChange = (val) => {
    setLocalQuery(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setQuery(val), 300)
  }

  const handleLocationChange = (val) => {
    setLocalLocation(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setLocation(val), 300)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    setQuery(localQuery)
    setLocation(localLocation)
    search(localQuery, localLocation)
  }

  const inputBase =
    'w-full bg-transparent outline-none text-gray-900 placeholder-gray-400'
  const sizeClass = large ? 'text-base py-3.5 px-5' : 'text-sm py-2.5 px-4'

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div
        className={`flex flex-col sm:flex-row border-2 border-gray-200 rounded-2xl overflow-hidden bg-white shadow-lg hover:border-orange-300 focus-within:border-orange-500 transition-colors ${large ? 'shadow-xl' : ''}`}
      >
        {/* Food/Restaurant input */}
        <div className="flex items-center flex-1 gap-3 px-1">
          <Search className={`shrink-0 text-orange-400 ml-3 ${large ? 'w-5 h-5' : 'w-4 h-4'}`} />
          <input
            type="text"
            placeholder={large ? 'Search restaurants or dishes...' : 'Restaurant or dish'}
            value={localQuery}
            onChange={(e) => handleQueryChange(e.target.value)}
            className={`${inputBase} ${sizeClass}`}
            required
          />
        </div>

        {/* Divider */}
        <div className="hidden sm:block w-px bg-gray-200 my-2" />
        <div className="sm:hidden h-px bg-gray-200 mx-4" />

        {/* Location input */}
        <div className="flex items-center gap-3 px-1 sm:min-w-52">
          <MapPin className={`shrink-0 text-orange-400 ml-3 ${large ? 'w-5 h-5' : 'w-4 h-4'}`} />
          <input
            type="text"
            placeholder="City, ZIP, or address"
            value={localLocation}
            onChange={(e) => handleLocationChange(e.target.value)}
            className={`${inputBase} ${sizeClass}`}
            required
          />
        </div>

        {/* Submit button */}
        <button
          type="submit"
          disabled={loading}
          className={`flex items-center justify-center gap-2 bg-orange-500 hover:bg-orange-600 disabled:bg-orange-300 text-white font-semibold transition-colors shrink-0 ${
            large ? 'px-8 py-3.5 text-base' : 'px-6 py-2.5 text-sm'
          }`}
        >
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <>
              <Search className="w-4 h-4" />
              {large && <span>Search</span>}
            </>
          )}
        </button>
      </div>
    </form>
  )
}
