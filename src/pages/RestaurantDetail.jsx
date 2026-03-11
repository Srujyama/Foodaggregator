import { useSearchParams, useParams, Link } from 'react-router-dom'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import PlatformCard from '../components/PlatformCard.jsx'
import DealRanking from '../components/DealRanking.jsx'
import ErrorBanner from '../components/ErrorBanner.jsx'
import LoadingSpinner from '../components/LoadingSpinner.jsx'
import { useRestaurant } from '../hooks/useRestaurant.js'
import { rankByBestDeal } from '../utils/sorting.js'

export default function RestaurantDetail() {
  const { slug } = useParams()
  const [searchParams] = useSearchParams()
  const location = searchParams.get('location') || ''
  const restaurantName = searchParams.get('name') || slug?.replace(/-/g, ' ')

  const { data, loading, error } = useRestaurant(restaurantName, location)

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
            <h1 className="text-3xl font-extrabold text-gray-900 mb-1">
              {data.restaurant_name}
            </h1>
            {location && <p className="text-gray-400 text-sm">{location}</p>}
          </div>

          {/* Deal ranking table */}
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

          {/* Menu items */}
          {data.platforms.some((p) => p.menu_items?.length > 0) && (
            <div>
              <h2 className="font-bold text-gray-800 text-lg mb-4">Menu Items</h2>
              <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
                {data.platforms
                  .filter((p) => p.menu_items?.length > 0)
                  .slice(0, 1)
                  .flatMap((p) => p.menu_items)
                  .slice(0, 20)
                  .map((item, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between px-5 py-3.5 border-b last:border-b-0 border-gray-100 hover:bg-gray-50"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-gray-900 truncate">{item.name}</p>
                        {item.description && (
                          <p className="text-sm text-gray-400 truncate">{item.description}</p>
                        )}
                      </div>
                      <span className="font-semibold text-gray-800 ml-4 shrink-0">
                        ${Number(item.price).toFixed(2)}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Disclaimer */}
          <p className="text-center text-xs text-gray-400 mt-8">
            Prices and fees may vary. Always confirm the final total on each platform before ordering.
          </p>
        </>
      )}
    </main>
  )
}
