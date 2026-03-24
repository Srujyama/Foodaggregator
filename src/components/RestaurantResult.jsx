import { Link } from 'react-router-dom'
import { ChevronRight, Trophy, UtensilsCrossed } from 'lucide-react'
import { rankByBestDeal, computeTotalCost, getSavings, getMenuSavings } from '../utils/sorting.js'
import { formatPrice, formatETA, slugify } from '../lib/utils.js'
import PlatformBadge from './PlatformBadge.jsx'
import { useSearchContext } from '../context/SearchContext.jsx'

export default function RestaurantResult({ result }) {
  const { location } = useSearchContext()
  const ranked = rankByBestDeal(result)
  const bestPlatform = ranked[0]
  const savings = getSavings(result)
  const menuSavings = getMenuSavings(result)

  return (
    <div className="bg-white rounded-2xl border border-gray-200 hover:border-orange-200 hover:shadow-md transition-all overflow-hidden">
      {/* Header */}
      <div className="px-5 pt-5 pb-3 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-bold text-gray-900 text-lg leading-tight truncate">
            {result.restaurant_name}
          </h3>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className="text-xs text-gray-400">
              Available on {result.platforms.length} platform{result.platforms.length !== 1 ? 's' : ''}
            </span>
            {savings > 0.01 && (
              <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5">
                <Trophy className="w-3 h-3 text-amber-400" />
                Save up to {formatPrice(savings)} in fees
              </span>
            )}
            {menuSavings > 0.01 && (
              <span className="inline-flex items-center gap-1 text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded-full px-2 py-0.5">
                <UtensilsCrossed className="w-3 h-3 text-blue-400" />
                Save up to {formatPrice(menuSavings)} on menu items
              </span>
            )}
          </div>
        </div>

        {/* Best deal summary */}
        {bestPlatform && (
          <div className="text-right shrink-0">
            <div className="text-xs text-gray-400 mb-0.5">Best fees</div>
            <div className="font-bold text-amber-600 text-lg">
              {formatPrice(computeTotalCost(bestPlatform))}
            </div>
            <div className="text-xs text-gray-400">
              {formatETA(bestPlatform.estimated_delivery_minutes)}
            </div>
          </div>
        )}
      </div>

      {/* Platform row */}
      <div className="px-5 pb-4">
        <div className="flex flex-wrap gap-2 mb-4">
          {ranked.map((p, i) => (
            <div key={p.platform} className="flex items-center gap-2 text-sm">
              <PlatformBadge platform={p.platform} />
              <span className={i === 0 ? 'text-amber-600 font-semibold' : 'text-gray-500'}>
                {formatPrice(computeTotalCost(p))}
              </span>
            </div>
          ))}
        </div>

        <Link
          to={`/restaurant/${slugify(result.restaurant_name)}?location=${encodeURIComponent(location)}&name=${encodeURIComponent(result.restaurant_name)}`}
          className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl bg-orange-50 border border-orange-200 text-sm font-semibold text-orange-600 hover:bg-orange-100 transition-colors"
        >
          Compare in detail
          <ChevronRight className="w-4 h-4" />
        </Link>
      </div>
    </div>
  )
}
