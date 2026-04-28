import { useSearchParams, useParams, Link } from 'react-router-dom'
import { ArrowLeft, AlertTriangle } from 'lucide-react'
import PlatformCard from '../components/PlatformCard.jsx'
import DealRanking from '../components/DealRanking.jsx'
import MenuComparison from '../components/MenuComparison.jsx'
import ErrorBanner from '../components/ErrorBanner.jsx'
import LoadingSpinner from '../components/LoadingSpinner.jsx'
import PlatformBadge from '../components/PlatformBadge.jsx'
import { useRestaurant } from '../hooks/useRestaurant.js'
import { rankByBestDeal } from '../utils/sorting.js'
import { formatPrice, sanitizeHtml } from '../lib/utils.js'

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

      {loading && <LoadingSpinner />}
      {!loading && error && <ErrorBanner message={error} />}

      {!loading && data && (
        <>
          {/* Header */}
          <div className="mb-8">
            <h1 className="text-3xl font-black text-gray-900 mb-1">
              {data.restaurant_name}
            </h1>
            {location && <p className="text-gray-400 text-sm">{location}</p>}
            {data.platforms?.length > 0 && (
              <p className="text-sm text-gray-500 mt-2">
                Available on {data.platforms.length} platform{data.platforms.length !== 1 ? 's' : ''}
                {hasMenuComparison && (
                  <span className="text-amber-600 ml-2 font-medium">
                    -- {data.menu_comparison.length} menu item{data.menu_comparison.length !== 1 ? 's' : ''} compared
                  </span>
                )}
              </p>
            )}
          </div>

          {/* Fee comparison ranking (shows both delivery & pickup) */}
          <div className="mb-8">
            <DealRanking aggregatedResult={data} />
          </div>

          {/* Platform cards */}
          <h2 className="font-bold text-gray-800 text-lg mb-4">Full breakdown by platform</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            {rankByBestDeal(data).map((platform, index) => (
              <PlatformCard
                key={platform.platform}
                platform={platform}
                isBestDeal={index === 0}
              />
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
          {hasMenuItems && (
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
