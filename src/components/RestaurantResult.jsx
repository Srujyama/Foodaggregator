import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, ChevronDown, Trophy, UtensilsCrossed, Bike, Car, Star, Menu } from 'lucide-react'
import { rankByBestDeal, computeCost, getSavings, getMenuSavings, computeTotalCost, computePickupCost } from '../utils/sorting.js'
import { formatPrice, formatETA, slugify } from '../lib/utils.js'
import PlatformBadge from './PlatformBadge.jsx'
import InlineMenu from './InlineMenu.jsx'
import { useSearchContext } from '../context/SearchContext.jsx'
import { cn } from '../lib/utils.js'

export default function RestaurantResult({ result }) {
  const { location, mode } = useSearchContext()
  const [showMenu, setShowMenu] = useState(false)
  const ranked = rankByBestDeal(result, mode)
  const bestPlatform = ranked[0]
  const savings = getSavings(result, mode)
  const menuSavings = getMenuSavings(result)
  const isPickup = mode === 'pickup'

  const bestRating = Math.max(
    ...result.platforms.map((p) => p.rating || 0).filter(Boolean),
  )

  return (
    <div className="bg-white rounded-2xl border border-gray-200 hover:border-orange-200 hover:shadow-lg transition-all duration-300 overflow-hidden group">
      {/* Header */}
      <div className="px-5 pt-5 pb-3 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-bold text-gray-900 text-lg leading-tight truncate">
              {result.restaurant_name}
            </h3>
            {bestRating > 0 && (
              <span className="flex items-center gap-0.5 text-xs text-gray-500 shrink-0">
                <Star className="w-3.5 h-3.5 text-amber-400 fill-amber-400" />
                {bestRating.toFixed(1)}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className="text-xs text-gray-400">
              {result.platforms.length} platform{result.platforms.length !== 1 ? 's' : ''}
            </span>
            {savings > 0.01 && (
              <span className="inline-flex items-center gap-1 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5 font-medium">
                <Trophy className="w-3 h-3 text-amber-400" />
                Save {formatPrice(savings)} in fees
              </span>
            )}
            {menuSavings > 0.01 && (
              <span className="inline-flex items-center gap-1 text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded-full px-2 py-0.5 font-medium">
                <UtensilsCrossed className="w-3 h-3 text-blue-400" />
                Save {formatPrice(menuSavings)} on menu
              </span>
            )}
          </div>
        </div>

        {bestPlatform && (
          <div className="text-right shrink-0">
            <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5 font-medium">
              {isPickup ? 'Pickup' : 'Delivery'} fees
            </div>
            <div className="font-black text-amber-600 text-xl tabular-nums">
              {formatPrice(computeCost(bestPlatform, mode))}
            </div>
            <div className="text-xs text-gray-400">
              {isPickup
                ? formatETA(bestPlatform.estimated_pickup_minutes)
                : formatETA(bestPlatform.estimated_delivery_minutes)}
            </div>
          </div>
        )}
      </div>

      {/* Platform comparison row */}
      <div className="px-5 pb-4">
        <div className="grid gap-2 mb-4" style={{ gridTemplateColumns: `repeat(${Math.min(ranked.length, 3)}, 1fr)` }}>
          {ranked.map((p, i) => {
            const deliveryCost = computeTotalCost(p)
            const pickupCost = computePickupCost(p)
            const isBest = i === 0

            return (
              <div
                key={p.platform}
                className={cn(
                  'rounded-xl p-3 border transition-all duration-200',
                  isBest
                    ? 'bg-amber-50 border-amber-200'
                    : 'bg-gray-50 border-gray-100',
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <PlatformBadge platform={p.platform} />
                  {isBest && (
                    <span className="text-[10px] font-bold text-amber-600 uppercase tracking-wider">Best</span>
                  )}
                </div>

                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="flex items-center gap-1 text-gray-400">
                    <Bike className="w-3 h-3" /> Delivery
                  </span>
                  <span className={cn(
                    'font-semibold tabular-nums',
                    !isPickup && isBest ? 'text-amber-600' : 'text-gray-600',
                  )}>
                    {formatPrice(deliveryCost)}
                  </span>
                </div>

                <div className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1 text-gray-400">
                    <Car className="w-3 h-3" /> Pickup
                  </span>
                  <span className={cn(
                    'font-semibold tabular-nums',
                    isPickup && isBest ? 'text-amber-600' : 'text-gray-600',
                  )}>
                    {p.pickup_available ? formatPrice(pickupCost) : 'N/A'}
                  </span>
                </div>

                <div className="text-[10px] text-gray-400 mt-1.5 text-center">
                  {isPickup
                    ? `${formatETA(p.estimated_pickup_minutes)} pickup`
                    : `${formatETA(p.estimated_delivery_minutes)} delivery`}
                </div>
              </div>
            )
          })}
        </div>

        {/* Action buttons */}
        <div className="flex gap-2">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="flex items-center justify-center gap-2 flex-1 py-2.5 rounded-xl bg-gray-100 border border-gray-200 text-sm font-semibold text-gray-700 hover:bg-gray-200 transition-all duration-200"
          >
            <Menu className="w-4 h-4" />
            {showMenu ? 'Hide Menu' : 'View Menu'}
            <ChevronDown className={cn('w-4 h-4 transition-transform', showMenu && 'rotate-180')} />
          </button>
          <Link
            to={`/restaurant/${slugify(result.restaurant_name)}?location=${encodeURIComponent(location)}&name=${encodeURIComponent(result.restaurant_name)}`}
            className="flex items-center justify-center gap-2 flex-1 py-2.5 rounded-xl bg-gradient-to-r from-orange-50 to-red-50 border border-orange-200 text-sm font-semibold text-orange-600 hover:from-orange-100 hover:to-red-100 transition-all duration-200"
          >
            Full Details
            <ChevronRight className="w-4 h-4" />
          </Link>
        </div>
      </div>

      {/* Expandable menu section */}
      {showMenu && (
        <InlineMenu
          restaurantName={result.restaurant_name}
          location={location}
          platforms={result.platforms}
        />
      )}
    </div>
  )
}
