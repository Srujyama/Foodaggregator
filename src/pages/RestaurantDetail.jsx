import { useSearchParams, useParams, Link } from 'react-router-dom'
import { ArrowLeft, AlertTriangle, Star, MapPin, Clock, UtensilsCrossed, SearchX } from 'lucide-react'
import PlatformCard from '../components/PlatformCard.jsx'
import DealRanking from '../components/DealRanking.jsx'
import MenuComparison from '../components/MenuComparison.jsx'
import ErrorBanner from '../components/ErrorBanner.jsx'
import { SkeletonDetail } from '../components/LoadingSpinner.jsx'
import PlatformBadge from '../components/PlatformBadge.jsx'
import { useRestaurant } from '../hooks/useRestaurant.js'
import { rankByBestDeal, getBestRating, isPlatformOpen } from '../utils/sorting.js'
import { formatPrice, sanitizeHtml } from '../lib/utils.js'

function pickRichest(platforms, key) {
  for (const p of platforms || []) {
    const v = p?.[key]
    if (v && (Array.isArray(v) ? v.length : true)) return v
  }
  return null
}

export default function RestaurantDetail() {
  const { slug } = useParams()
  const [searchParams] = useSearchParams()
  const location = searchParams.get('location') || ''
  const restaurantName = searchParams.get('name') || slug?.replace(/-/g, ' ')

  const { data, loading, error } = useRestaurant(restaurantName, location)

  const hasMenuItems = data?.platforms?.some((p) => p.menu_items?.length > 0)
  const hasMenuComparison = data?.menu_comparison?.length > 0
  const allergenHtml = data?.platforms?.find((p) => p.allergen_disclaimer_html)?.allergen_disclaimer_html
  const sanitizedAllergen = allergenHtml ? sanitizeHtml(allergenHtml) : ''

  const bestRating = data ? getBestRating(data) : 0
  const categories = [...new Set(pickRichest(data?.platforms, 'categories') || [])]
  const priceBucket = pickRichest(data?.platforms, 'price_bucket')
  const address = pickRichest(data?.platforms, 'address')
  const hoursToday = pickRichest(data?.platforms, 'hours_today_text')
  const allClosed =
    data?.platforms?.length > 0 && !data.platforms.some(isPlatformOpen)

  return (
    <main className="max-w-4xl mx-auto px-4 py-8">
      {/* Back button */}
      <Link
        to={`/results?q=${encodeURIComponent(restaurantName)}&location=${encodeURIComponent(location)}`}
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-orange-500 transition-colors mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to results
      </Link>

      {loading && <SkeletonDetail />}
      {!loading && error && <ErrorBanner message={error} />}

      {/* Restaurant found but with nothing to show */}
      {!loading && !error && data && !data.platforms?.length && (
        <div className="flex flex-col items-center py-16 text-center gap-4">
          <div className="w-16 h-16 rounded-2xl bg-gray-100 flex items-center justify-center">
            <SearchX className="w-8 h-8 text-gray-400" />
          </div>
          <div>
            <p className="font-bold text-lg text-gray-800">
              "{data.restaurant_name}" isn't available right now
            </p>
            <p className="text-sm text-gray-400 mt-1 max-w-sm">
              None of the platforms we track list this restaurant near{' '}
              {location || 'your location'} at the moment.
            </p>
          </div>
        </div>
      )}

      {!loading && data && data.platforms?.length > 0 && (
        <>
          {/* Header */}
          <div className="mb-8 animate-rise">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h1 className="text-3xl font-black text-gray-900">
                {data.restaurant_name}
              </h1>
              {bestRating > 0 && (
                <span className="flex items-center gap-1 text-sm font-semibold text-gray-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-1">
                  <Star className="w-3.5 h-3.5 text-amber-400 fill-amber-400" />
                  {bestRating.toFixed(1)}
                </span>
              )}
              {priceBucket && (
                <span className="text-sm font-semibold text-gray-600 bg-gray-100 border border-gray-200 rounded-full px-2.5 py-1">
                  {priceBucket}
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-sm text-gray-500">
              {categories.length > 0 && (
                <span>{categories.slice(0, 4).join(' · ')}</span>
              )}
              {address && (
                <span className="inline-flex items-center gap-1 text-gray-400">
                  <MapPin className="w-3.5 h-3.5" /> {address}
                </span>
              )}
              {hoursToday && (
                <span className="inline-flex items-center gap-1 text-gray-400">
                  <Clock className="w-3.5 h-3.5" /> {hoursToday}
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2 mt-3">
              {data.platforms.map((p) => (
                <PlatformBadge key={p.platform} platform={p.platform} />
              ))}
              {hasMenuComparison && (
                <span className="text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-1">
                  {data.menu_comparison.length} menu item{data.menu_comparison.length !== 1 ? 's' : ''} compared
                </span>
              )}
            </div>
          </div>

          {/* Everything-closed banner */}
          {allClosed && (
            <div className="mb-6 rounded-2xl border border-rose-200 bg-rose-50 p-4 flex items-start gap-3 animate-rise">
              <AlertTriangle className="w-4 h-4 text-rose-600 mt-0.5 shrink-0" />
              <div className="text-sm text-rose-800">
                <p className="font-semibold">Closed on every platform right now</p>
                <p className="text-rose-600 text-xs mt-0.5">
                  Fees and menus below are the latest we have — check back during opening hours to order.
                </p>
              </div>
            </div>
          )}

          {/* Fee comparison ranking (shows both delivery & pickup) */}
          <div className="mb-8 animate-rise" style={{ animationDelay: '60ms' }}>
            <DealRanking aggregatedResult={data} />
          </div>

          {/* Platform cards */}
          <h2 className="font-bold text-gray-800 text-lg mb-4">Full breakdown by platform</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            {rankByBestDeal(data).map((platform, index) => (
              <div key={platform.platform} className="animate-rise" style={{ animationDelay: `${120 + index * 50}ms` }}>
                <PlatformCard platform={platform} isBestDeal={index === 0} />
              </div>
            ))}
          </div>

          {/* Cross-platform menu price comparison */}
          {hasMenuComparison && (
            <div className="mb-8">
              <h2 className="font-bold text-gray-800 text-lg mb-4">
                Menu Price Comparison
              </h2>
              <MenuComparison
                menuComparison={data.menu_comparison}
                platforms={data.platforms}
                avgMarkup={data.avg_menu_markup_by_platform}
              />
            </div>
          )}

          {/* Per-platform full menus */}
          {hasMenuItems ? (
            <div className="mb-8">
              <h2 className="font-bold text-gray-800 text-lg mb-4">Full Menus by Platform</h2>
              <div className="space-y-6">
                {data.platforms
                  .filter((p) => p.menu_items?.length > 0)
                  .map((platform) => (
                    <div key={platform.platform}>
                      <div className="flex items-center gap-3 mb-3">
                        <PlatformBadge platform={platform.platform} size="md" />
                        <span className="text-sm text-gray-400">
                          {platform.menu_items.length} item{platform.menu_items.length !== 1 ? 's' : ''}
                        </span>
                      </div>
                      <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
                        {platform.menu_items.slice(0, 30).map((item, i) => (
                          <div
                            key={i}
                            className="flex items-center justify-between px-5 py-3.5 border-b last:border-b-0 border-gray-100 hover:bg-gray-50 transition-colors"
                          >
                            <div className="flex-1 min-w-0">
                              <p className="font-medium text-gray-900 truncate">
                                {item.name}
                              </p>
                              {item.description && (
                                <p className="text-sm text-gray-400 truncate">
                                  {item.description}
                                </p>
                              )}
                            </div>
                            <span className="font-semibold text-gray-800 ml-4 shrink-0 tabular-nums">
                              {formatPrice(item.price)}
                            </span>
                          </div>
                        ))}
                        {platform.menu_items.length > 30 && (
                          <div className="px-5 py-3 text-center text-xs text-gray-400 bg-gray-50">
                            +{platform.menu_items.length - 30} more items
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          ) : (
            <div className="mb-8 rounded-2xl border border-dashed border-gray-200 bg-white px-6 py-10 flex flex-col items-center text-center gap-2">
              <UtensilsCrossed className="w-8 h-8 text-gray-300" />
              <p className="font-semibold text-gray-600">Menus unavailable</p>
              <p className="text-xs text-gray-400 max-w-xs">
                We couldn't load menu items from any platform this time — fee
                comparisons above are still accurate. Use the order links to
                browse the menu directly.
              </p>
            </div>
          )}

          {/* Allergen / dietary disclaimer */}
          {sanitizedAllergen && (
            <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 p-4 flex items-start gap-3">
              <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
              <div className="text-xs text-amber-900 leading-relaxed allergen-disclaimer">
                <p className="font-semibold mb-1">Allergen & dietary info</p>
                <div dangerouslySetInnerHTML={{ __html: sanitizedAllergen }} />
              </div>
            </div>
          )}

          {/* Disclaimer */}
          <p className="text-center text-xs text-gray-400 mt-8">
            Prices, fees, taxes, and tips may vary. Always confirm the final total on each platform before ordering.
          </p>
        </>
      )}
    </main>
  )
}
