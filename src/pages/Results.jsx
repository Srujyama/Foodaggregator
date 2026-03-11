import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { SlidersHorizontal, SearchX } from 'lucide-react'
import SearchBar from '../components/SearchBar.jsx'
import RestaurantResult from '../components/RestaurantResult.jsx'
import ErrorBanner from '../components/ErrorBanner.jsx'
import { SkeletonResults } from '../components/LoadingSpinner.jsx'
import { useSearchContext } from '../context/SearchContext.jsx'
import { useSearch } from '../hooks/useSearch.js'

export default function Results() {
  const [searchParams] = useSearchParams()
  const urlQuery = searchParams.get('q') || ''
  const urlLocation = searchParams.get('location') || ''

  const { results, loading, error } = useSearchContext()
  const { search, setQuery, setLocation } = useSearch()

  // On mount, if URL has params and no results yet, trigger a search
  useEffect(() => {
    if (urlQuery && urlLocation && results.length === 0 && !loading) {
      setQuery(urlQuery)
      setLocation(urlLocation)
      search(urlQuery, urlLocation)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <main className="max-w-4xl mx-auto px-4 py-8">
      {/* Search bar */}
      <div className="mb-8">
        <SearchBar initialQuery={urlQuery} initialLocation={urlLocation} />
      </div>

      {/* Results header */}
      {!loading && (results.length > 0 || error) && (
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="font-bold text-xl text-gray-900">
              {results.length > 0
                ? `${results.length} result${results.length !== 1 ? 's' : ''} for "${urlQuery}"`
                : 'No results found'}
            </h1>
            {urlLocation && (
              <p className="text-sm text-gray-400 mt-0.5">{urlLocation}</p>
            )}
          </div>
          {results.length > 1 && (
            <div className="flex items-center gap-1.5 text-sm text-gray-400">
              <SlidersHorizontal className="w-4 h-4" />
              Sorted by best deal
            </div>
          )}
        </div>
      )}

      {/* Loading */}
      {loading && <SkeletonResults />}

      {/* Error */}
      {!loading && error && (
        <ErrorBanner
          message={error}
          onRetry={() => search(urlQuery, urlLocation)}
        />
      )}

      {/* Empty state */}
      {!loading && !error && results.length === 0 && urlQuery && (
        <div className="flex flex-col items-center py-20 text-center gap-4">
          <SearchX className="w-12 h-12 text-gray-300" />
          <div>
            <p className="font-semibold text-gray-600">No results for "{urlQuery}"</p>
            <p className="text-sm text-gray-400 mt-1">
              Try a different search term or location.
            </p>
          </div>
        </div>
      )}

      {/* Results list */}
      {!loading && !error && results.length > 0 && (
        <div className="space-y-4">
          {results.map((result) => (
            <RestaurantResult key={result.restaurant_name} result={result} />
          ))}

          {/* Footer note */}
          <p className="text-center text-xs text-gray-400 pt-4 pb-2">
            Prices, fees, and availability may vary. Always confirm the final total on each platform before ordering.
          </p>
        </div>
      )}
    </main>
  )
}
