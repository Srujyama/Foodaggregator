import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, ChevronDown, Trophy, UtensilsCrossed, Bike, Car, Star, Menu, ExternalLink, MapPin, AlertTriangle } from 'lucide-react'
import { rankByBestDeal, computeCost, getSavings, getMenuSavings, computeTotalCost, computePickupCost } from '../utils/sorting.js'
import { formatPrice, formatETA, slugify } from '../lib/utils.js'
import PlatformBadge from './PlatformBadge.jsx'
import InlineMenu from './InlineMenu.jsx'
import { useSearchContext } from '../context/SearchContext.jsx'
import { cn } from '../lib/utils.js'

function pickRichest(platforms, key) {
  for (const p of platforms) {
    const v = p?.[key]
    if (v && (Array.isArray(v) ? v.length : true)) return v
  }
  return null
}

function formatEtaRange(min, max) {
  if (!min) return formatETA(min)
  if (max && max !== min) return `${min}–${max} min`
  return formatETA(min)
}

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

  // Cross-platform consumer info (any platform that has it wins).
  const categories = pickRichest(result.platforms, 'categories') || []
  const priceBucket = pickRichest(result.platforms, 'price_bucket')
  const distance = pickRichest(result.platforms, 'distance_text')
  const address = pickRichest(result.platforms, 'address')

  const anyClosed = result.platforms.some(
    (p) => p.accepting_orders === false || p.is_open === false || p.is_within_delivery_range === false,
  )
  const anyOpen = result.platforms.some(
    (p) => p.accepting_orders === true || p.is_open === true,
  )
  const allClosed = anyClosed && !anyOpen
  const someClosed = anyClosed && anyOpen

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
            {priceBucket && (
              <span className="inline-flex items-center text-xs text-gray-600 bg-gray-100 border border-gray-200 rounded-full px-2 py-0.5 font-semibold">
                {priceBucket}
              </span>
            )}
            {distance && (
              <span className="inline-flex items-center gap-1 text-xs text-gray-500 bg-white border border-gray-200 rounded-full px-2 py-0.5">
                <MapPin className="w-3 h-3 text-gray-400" /> {distance}
              </span>
            )}
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
            {allClosed && (
              <span className="inline-flex items-center gap-1 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-full px-2 py-0.5 font-medium">
                <AlertTriangle className="w-3 h-3" />
                Closed on all platforms
              </span>
            )}
            {someClosed && !allClosed && (
              <span className="inline-flex items-center gap-1 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5 font-medium">
                <AlertTriangle className="w-3 h-3" />
                Limited availability
              </span>
            )}
          </div>
          {(categories.length > 0 || address) && (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1.5 text-xs text-gray-500">
              {categories.slice(0, 4).map((c) => (
                <span key={c} className="text-gray-400">
                  · {c}
                </span>
              ))}
              {address && (
                <span className="text-gray-400 truncate max-w-[260px]">
                  · {address}
                </span>
              )}
            </div>
          )}
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
                : formatEtaRange(bestPlatform.estimated_delivery_minutes, bestPlatform.estimated_delivery_minutes_max)}
            </div>
            <div className="text-[10px] text-gray-300 italic mt-0.5">
              + taxes & tip
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
            const unavailable =
              p.accepting_orders === false ||
              p.is_open === false ||
              p.is_within_delivery_range === false

            return (
              <div
                key={p.platform}
                className={cn(
                  'rounded-xl p-3 border transition-all duration-200',
                  unavailable
                    ? 'bg-rose-50/40 border-rose-100 opacity-75'
                    : isBest
                    ? 'bg-amber-50 border-amber-200'
                    : 'bg-gray-50 border-gray-100',
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <PlatformBadge platform={p.platform} />
                  {isBest && !unavailable && (
                    <span className="text-[10px] font-bold text-amber-600 uppercase tracking-wider">Best</span>
                  )}
                  {unavailable && (
                    <span className="text-[10px] font-bold text-rose-600 uppercase tracking-wider">
                      {p.is_within_delivery_range === false ? 'Out of range' : 'Closed'}
                    </span>
                  )}
                </div>

                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="flex items-center gap-1 text-gray-400">
                    <Bike className="w-3 h-3" /> Delivery
                  </span>
                  <span className={cn(
                    'font-semibold tabular-nums',
                    !isPickup && isBest && !unavailable ? 'text-amber-600' : 'text-gray-600',
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
                    isPickup && isBest && !unavailable ? 'text-amber-600' : 'text-gray-600',
                  )}>
                    {p.pickup_available ? formatPrice(pickupCost) : 'N/A'}
                  </span>
                </div>

                <div className="text-[10px] text-gray-400 mt-1.5 text-center">
                  {isPickup
                    ? `${formatETA(p.estimated_pickup_minutes)} pickup`
                    : `${formatEtaRange(p.estimated_delivery_minutes, p.estimated_delivery_minutes_max)} delivery`}
                  {p.distance_text && (
                    <span className="text-gray-300"> · {p.distance_text}</span>
                  )}
                </div>

                {p.restaurant_url && (
                  <a
                    href={p.restaurant_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-1 mt-2 py-1.5 rounded-lg text-[10px] font-semibold text-gray-500 hover:text-orange-600 hover:bg-orange-50 transition-all duration-200"
                  >
                    Order <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                )}
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
