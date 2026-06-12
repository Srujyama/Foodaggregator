import { useState, useRef, useEffect } from 'react'
import { Search, MapPin, Loader2, Car, Bike, LocateFixed, History } from 'lucide-react'
import toast from 'react-hot-toast'
import { useSearch } from '../hooks/useSearch.js'
import { useSearchContext } from '../context/SearchContext.jsx'
import { getRecentSearches } from '../lib/recentSearches.js'
import { getCurrentLocationLabel } from '../lib/geolocate.js'
import { cn } from '../lib/utils.js'

export default function SearchBar({ large = false, initialQuery = '', initialLocation = '' }) {
  const { loading, mode } = useSearchContext()
  const { search, setQuery, setLocation, setMode } = useSearch()
  const [localQuery, setLocalQuery] = useState(initialQuery)
  const [localLocation, setLocalLocation] = useState(initialLocation)
  const [locating, setLocating] = useState(false)
  const [recents, setRecents] = useState([])
  const [showRecents, setShowRecents] = useState(false)
  const debounceRef = useRef(null)
  const blurTimeoutRef = useRef(null)
  const recentsRef = useRef(null)

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

  const toggleMode = (newMode) => {
    setMode(newMode)
  }

  const handleUseMyLocation = async () => {
    setLocating(true)
    try {
      const label = await getCurrentLocationLabel()
      setLocalLocation(label)
      setLocation(label)
    } catch {
      toast.error("Couldn't get your location")
    } finally {
      setLocating(false)
    }
  }

  const handleQueryFocus = () => {
    clearTimeout(blurTimeoutRef.current)
    setRecents(getRecentSearches())
    setShowRecents(true)
  }

  const handleQueryBlur = () => {
    blurTimeoutRef.current = setTimeout(() => setShowRecents(false), 120)
  }

  const handleRecentSelect = (recent) => {
    clearTimeout(blurTimeoutRef.current)
    setShowRecents(false)
    setLocalQuery(recent.q)
    setLocalLocation(recent.location)
    setQuery(recent.q)
    setLocation(recent.location)
    search(recent.q, recent.location, recent.mode)
  }

  return (
    <div className="w-full space-y-3">
      {/* Delivery/Pickup Toggle */}
      <div className="flex justify-center">
        <div className="inline-flex bg-gray-100 rounded-full p-1 gap-1">
          <button
            type="button"
            onClick={() => toggleMode('delivery')}
            className={cn(
              'flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-medium transition-all duration-200',
              mode === 'delivery'
                ? 'bg-white text-orange-600 shadow-sm'
                : 'text-gray-500 hover:text-gray-700',
            )}
          >
            <Bike className="w-4 h-4" />
            Delivery
          </button>
          <button
            type="button"
            onClick={() => toggleMode('pickup')}
            className={cn(
              'flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-medium transition-all duration-200',
              mode === 'pickup'
                ? 'bg-white text-orange-600 shadow-sm'
                : 'text-gray-500 hover:text-gray-700',
            )}
          >
            <Car className="w-4 h-4" />
            Pickup
          </button>
        </div>
      </div>

      {/* Search Form */}
      <form onSubmit={handleSubmit} className="relative w-full">
        <div
          className={cn(
            'flex flex-col sm:flex-row border-2 rounded-2xl overflow-hidden bg-white transition-all duration-200',
            large
              ? 'shadow-xl border-white/30 hover:shadow-2xl focus-within:border-orange-400'
              : 'shadow-lg border-gray-200 hover:border-orange-300 focus-within:border-orange-500',
          )}
        >
          {/* Food/Restaurant input */}
          <div className="flex items-center flex-1 gap-3 px-1">
            <Search className={cn('shrink-0 ml-3', large ? 'w-5 h-5 text-orange-400' : 'w-4 h-4 text-gray-400')} />
            <input
              type="text"
              placeholder={large ? 'Search restaurants or dishes...' : 'Restaurant or dish'}
              value={localQuery}
              onChange={(e) => handleQueryChange(e.target.value)}
              onFocus={handleQueryFocus}
              onBlur={handleQueryBlur}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setShowRecents(false)
                if (e.key === 'ArrowDown' && showRecents) {
                  e.preventDefault()
                  recentsRef.current?.querySelector('button')?.focus()
                }
              }}
              className={cn(
                'w-full bg-transparent outline-none text-gray-900 placeholder-gray-400',
                large ? 'text-base py-3.5 px-2' : 'text-sm py-2.5 px-2',
              )}
              required
            />
          </div>

          {/* Divider */}
          <div className="hidden sm:block w-px bg-gray-200 my-2" />
          <div className="sm:hidden h-px bg-gray-200 mx-4" />

          {/* Location input */}
          <div className="flex items-center gap-3 px-1 sm:min-w-52">
            <MapPin className={cn('shrink-0 ml-3', large ? 'w-5 h-5 text-orange-400' : 'w-4 h-4 text-gray-400')} />
            <input
              type="text"
              placeholder="City, ZIP, or address"
              value={localLocation}
              onChange={(e) => handleLocationChange(e.target.value)}
              className={cn(
                'w-full bg-transparent outline-none text-gray-900 placeholder-gray-400',
                large ? 'text-base py-3.5 px-2' : 'text-sm py-2.5 px-2',
              )}
              required
            />
            <button
              type="button"
              onClick={handleUseMyLocation}
              disabled={locating}
              aria-label="Use my location"
              className="shrink-0 mr-2 p-1.5 rounded-lg text-gray-400 hover:text-orange-500 hover:bg-orange-50 transition-colors duration-200"
            >
              {locating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <LocateFixed className="w-4 h-4" />
              )}
            </button>
          </div>

          {/* Submit button */}
          <button
            type="submit"
            disabled={loading}
            className={cn(
              'flex items-center justify-center gap-2 bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-600 hover:to-red-600 disabled:from-orange-300 disabled:to-red-300 text-white font-semibold transition-all duration-200 shrink-0',
              large ? 'px-8 py-3.5 text-base' : 'px-6 py-2.5 text-sm',
            )}
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

        {/* Recent searches dropdown (sibling of the overflow-hidden box so it isn't clipped) */}
        {showRecents && !loading && recents.length > 0 && (
          <div
            ref={recentsRef}
            aria-label="Recent searches"
            className="absolute left-0 right-0 top-full mt-2 bg-white rounded-xl border border-gray-200 shadow-lg z-20 overflow-hidden py-1"
          >
            {recents.slice(0, 5).map((recent) => (
              <button
                key={`${recent.q}|${recent.location}`}
                type="button"
                // preventDefault keeps the input from blurring on mouse press;
                // selection happens on click so keyboard Enter works too.
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => handleRecentSelect(recent)}
                onFocus={() => clearTimeout(blurTimeoutRef.current)}
                onBlur={handleQueryBlur}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setShowRecents(false)
                }}
                className="flex items-center gap-2.5 w-full px-4 py-2.5 text-left text-sm text-gray-700 hover:bg-orange-50 focus:bg-orange-50 transition-colors duration-150"
              >
                <History className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                <span className="truncate">
                  {recent.q} <span className="text-gray-400">· {recent.location}</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </form>
    </div>
  )
}
