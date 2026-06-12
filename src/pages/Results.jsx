import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { SearchX, Bike, Car, FilterX, Lightbulb, AlertTriangle } from 'lucide-react'
import SearchBar from '../components/SearchBar.jsx'
import RestaurantResult from '../components/RestaurantResult.jsx'
import ResultsControls from '../components/ResultsControls.jsx'
import ErrorBanner from '../components/ErrorBanner.jsx'
import { SkeletonResults } from '../components/LoadingSpinner.jsx'
import { useSearchContext } from '../context/SearchContext.jsx'
import { useSearch } from '../hooks/useSearch.js'
import {
  sortResults, filterResults, hasActiveFilters, EMPTY_FILTERS,
} from '../utils/sorting.js'
import { parseQueryState, applyQueryState } from '../utils/queryState.js'
import { cn } from '../lib/utils.js'

const SEARCH_SUGGESTIONS = ['Pizza', 'Tacos', 'Sushi', 'Burgers', 'Thai', 'Wings']

const PLATFORM_DISPLAY_NAMES = {
  uber_eats: 'Uber Eats', doordash: 'DoorDash', grubhub: 'Grubhub',
  postmates: 'Postmates', seamless: 'Seamless', caviar: 'Caviar',
  gopuff: 'gopuff', eatstreet: 'EatStreet',
}

const listNames = (names) =>
  names.length > 1
    ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
    : names[0]

export default function Results() {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlQuery = searchParams.get('q') || ''
  const urlLocation = searchParams.get('location') || ''
  const urlMode = searchParams.get('mode') || 'delivery'

  const { results, loading, error, mode, platformStatus } = useSearchContext()
  const { search, setQuery, setLocation, setMode } = useSearch()

  // The URL is the single source of truth for sort/filter state. New searches
  // navigate with only q/location/mode, so stale filters can't carry over.
  const { sortKey, filters } = useMemo(() => parseQueryState(searchParams), [searchParams])

  const setQueryState = (nextSortKey, nextFilters) =>
    setSearchParams(applyQueryState(searchParams, nextSortKey, nextFilters), { replace: true })

  useEffect(() => {
    if (!urlQuery || !urlLocation) return
    setQuery(urlQuery)
    setLocation(urlLocation)
    if (urlMode) setMode(urlMode)
    search(urlQuery, urlLocation, urlMode)
  }, [urlQuery, urlLocation]) // eslint-disable-line react-hooks/exhaustive-deps

  const platformCounts = useMemo(() => {
    const counts = {}
    for (const r of results) {
      for (const p of r.platforms) {
        counts[p.platform] = (counts[p.platform] || 0) + 1
      }
    }
    return counts
  }, [results])

  const visible = useMemo(
    () => sortResults(filterResults(results, filters), sortKey, mode),
    [results, filters, sortKey, mode],
  )

  const filtersActive = hasActiveFilters(filters)
  const multiCount = useMemo(
    () => results.filter((r) => r.platforms.length > 1).length,
    [results],
  )

  // "empty" is a legitimate zero — only timeouts/errors warrant a notice.
  const failedPlatformNames = useMemo(
    () => Object.entries(platformStatus || {})
      .filter(([, status]) => status === 'timeout' || status === 'error')
      .map(([id]) => PLATFORM_DISPLAY_NAMES[id] || id),
    [platformStatus],
  )

  return (
    <main className="max-w-4xl mx-auto px-4 py-8">
      {/* Search bar */}
      <div className="mb-8">
        <SearchBar initialQuery={urlQuery} initialLocation={urlLocation} />
      </div>

      {/* Results header + controls */}
      {!loading && results.length > 0 && (
        <div className="mb-5 space-y-4">
          <div>
            <h1 className="font-bold text-xl text-gray-900">
              {filtersActive
                ? `${visible.length} of ${results.length} results for "${urlQuery}"`
                : `${results.length} result${results.length !== 1 ? 's' : ''} for "${urlQuery}"`}
            </h1>
            <div className="flex items-center gap-3 mt-1">
              {urlLocation && (
                <p className="text-sm text-gray-400">{urlLocation}</p>
              )}
              <span className={cn(
                'inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full',
                mode === 'pickup' ? 'bg-violet-50 text-violet-600' : 'bg-orange-50 text-orange-600',
              )}>
                {mode === 'pickup' ? <Car className="w-3 h-3" /> : <Bike className="w-3 h-3" />}
                {mode === 'pickup' ? 'Pickup' : 'Delivery'}
              </span>
              {multiCount > 0 && (
                <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600">
                  {multiCount} cross-platform match{multiCount !== 1 ? 'es' : ''}
                </span>
              )}
            </div>
          </div>

          <ResultsControls
            sortKey={sortKey}
            onSortChange={(key) => setQueryState(key, filters)}
            filters={filters}
            onFiltersChange={(next) => setQueryState(sortKey, next)}
            platformCounts={platformCounts}
          />
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

      {/* Platform status notice: some scrapers timed out or errored */}
      {!loading && !error && failedPlatformNames.length > 0 && (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 mb-5">
          <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-800">
            <span className="font-semibold">{listNames(failedPlatformNames)}</span>
            {' '}didn't respond — fee comparisons may be incomplete.
          </p>
        </div>
      )}

      {/* Empty state: the search itself returned nothing */}
      {!loading && !error && results.length === 0 && urlQuery && (
        <div className="flex flex-col items-center py-16 text-center gap-5">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-orange-100 to-red-100 flex items-center justify-center">
            <SearchX className="w-8 h-8 text-orange-400" />
          </div>
          <div>
            <p className="font-bold text-lg text-gray-800">No results for "{urlQuery}"</p>
            <p className="text-sm text-gray-400 mt-1 max-w-sm">
              We couldn't find that near {urlLocation || 'your location'}. Platforms
              only show restaurants that deliver to the searched address.
            </p>
          </div>
          <div className="flex flex-col items-center gap-2.5">
            <span className="flex items-center gap-1.5 text-xs text-gray-400 font-medium">
              <Lightbulb className="w-3.5 h-3.5" /> Try one of these instead
            </span>
            <div className="flex flex-wrap justify-center gap-2">
              {SEARCH_SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => search(s, urlLocation, mode)}
                  className="px-3.5 py-1.5 rounded-full text-sm font-medium bg-white border border-gray-200 text-gray-600 hover:border-orange-300 hover:text-orange-600 hover:shadow-sm transition-all duration-200"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Empty state: filters removed everything */}
      {!loading && !error && results.length > 0 && visible.length === 0 && (
        <div className="flex flex-col items-center py-16 text-center gap-4">
          <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center">
            <FilterX className="w-8 h-8 text-gray-400" />
          </div>
          <div>
            <p className="font-bold text-lg text-gray-800">No results match your filters</p>
            <p className="text-sm text-gray-400 mt-1">
              {results.length} result{results.length !== 1 ? 's are' : ' is'} hidden by the active filters.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setQueryState(sortKey, EMPTY_FILTERS)}
            className="px-4 py-2 rounded-xl text-sm font-semibold bg-gradient-to-r from-orange-500 to-red-500 text-white shadow-sm hover:shadow-md transition-all duration-200"
          >
            Clear all filters
          </button>
        </div>
      )}

      {/* Results list */}
      {!loading && !error && visible.length > 0 && (
        <div className="space-y-4">
          {visible.map((result, i) => (
            <div
              // Two distinct groups can share a display name (e.g. two
              // locations of one chain), so anchor the key on a platform id.
              key={result.platforms[0]?.restaurant_id || `${result.restaurant_name}-${i}`}
              className="animate-rise"
              style={{ animationDelay: `${Math.min(i, 8) * 45}ms` }}
            >
              <RestaurantResult result={result} />
            </div>
          ))}

          <p className="text-center text-xs text-gray-400 pt-4 pb-2">
            Prices, fees, and availability may vary. Always confirm the final total on each platform before ordering.
          </p>
        </div>
      )}
    </main>
  )
}
