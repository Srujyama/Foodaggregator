import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { SlidersHorizontal, SearchX, Bike, Car, CheckCircle2, XCircle } from 'lucide-react'
import SearchBar from '../components/SearchBar.jsx'
import RestaurantResult from '../components/RestaurantResult.jsx'
import ErrorBanner from '../components/ErrorBanner.jsx'
import { SkeletonResults } from '../components/LoadingSpinner.jsx'
import { useSearchContext } from '../context/SearchContext.jsx'
import { useSearch } from '../hooks/useSearch.js'
import { cn } from '../lib/utils.js'

export default function Results() {
  const [searchParams] = useSearchParams()
  const urlQuery = searchParams.get('q') || ''
  const urlLocation = searchParams.get('location') || ''
  const urlMode = searchParams.get('mode') || 'delivery'

  const { results, loading, error, mode } = useSearchContext()
  const { search, setQuery, setLocation, setMode } = useSearch()

  useEffect(() => {
    if (!urlQuery || !urlLocation) return
    setQuery(urlQuery)
    setLocation(urlLocation)
    if (urlMode) setMode(urlMode)
    search(urlQuery, urlLocation, urlMode)
  }, [urlQuery, urlLocation]) // eslint-disable-line react-hooks/exhaustive-deps

  const platformStats = useMemo(() => {
    if (!results.length) return null
    const counts = { uber_eats: 0, doordash: 0, grubhub: 0 }
    for (const r of results) {
      for (const p of r.platforms) {
        if (counts[p.platform] !== undefined) counts[p.platform]++
      }
    }
    const multi = results.filter((r) => r.platforms.length > 1).length
    return { counts, multi }
  }, [results])

  const platformLabels = { uber_eats: 'Uber Eats', doordash: 'DoorDash', grubhub: 'Grubhub' }
  const platformColors = {
    uber_eats: { active: 'text-gray-900', bg: 'bg-gray-100' },
    doordash: { active: 'text-red-600', bg: 'bg-red-50' },
    grubhub: { active: 'text-orange-600', bg: 'bg-orange-50' },
  }

  return (
    <main className="max-w-4xl mx-auto px-4 py-8">
      {/* Search bar */}
      <div className="mb-8">
        <SearchBar initialQuery={urlQuery} initialLocation={urlLocation} />
      </div>

      {/* Results header */}
      {!loading && (results.length > 0 || error) && (
        <div className="mb-5">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="font-bold text-xl text-gray-900">
                {results.length > 0
                  ? `${results.length} result${results.length !== 1 ? 's' : ''} for "${urlQuery}"`
                  : 'No results found'}
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
              </div>
            </div>
            {results.length > 1 && (
              <div className="flex items-center gap-1.5 text-sm text-gray-400">
                <SlidersHorizontal className="w-4 h-4" />
                Sorted by best deal
              </div>
            )}
          </div>

          {/* Platform coverage summary */}
          {platformStats && (
            <div className="flex flex-wrap items-center gap-2 mt-3">
              {Object.entries(platformStats.counts).map(([platform, count]) => {
                const colors = platformColors[platform]
                return (
                  <span
                    key={platform}
                    className={cn(
                      'inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full',
                      count > 0 ? colors.bg : 'bg-gray-50',
                      count > 0 ? colors.active : 'text-gray-400',
                    )}
                  >
                    {count > 0 ? (
                      <CheckCircle2 className="w-3 h-3" />
                    ) : (
                      <XCircle className="w-3 h-3" />
                    )}
                    {platformLabels[platform]} ({count})
                  </span>
                )
              })}
              {platformStats.multi > 0 && (
                <span className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-600">
                  {platformStats.multi} cross-platform match{platformStats.multi !== 1 ? 'es' : ''}
                </span>
              )}
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

          <p className="text-center text-xs text-gray-400 pt-4 pb-2">
            Prices, fees, and availability may vary. Always confirm the final total on each platform before ordering.
          </p>
        </div>
      )}
    </main>
  )
}
