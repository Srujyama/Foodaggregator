import { Trophy, TrendingDown } from 'lucide-react'
import { rankByBestDeal, computeTotalCost, getSavings } from '../utils/sorting.js'
import { formatPrice, formatETA } from '../lib/utils.js'
import PlatformBadge from './PlatformBadge.jsx'
import { cn } from '../lib/utils.js'

export default function DealRanking({ aggregatedResult }) {
  const ranked = rankByBestDeal(aggregatedResult)
  const savings = getSavings(aggregatedResult)

  if (ranked.length === 0) return null

  return (
    <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Trophy className="w-4 h-4 text-amber-500" />
          <h3 className="font-semibold text-gray-900">Price Comparison</h3>
        </div>
        {savings > 0.01 && (
          <div className="flex items-center gap-1 text-xs text-green-700 bg-green-50 border border-green-200 rounded-full px-3 py-1">
            <TrendingDown className="w-3 h-3" />
            Save up to {formatPrice(savings)} in fees
          </div>
        )}
      </div>

      <div className="divide-y divide-gray-100">
        {ranked.map((platform, index) => {
          const totalFees = computeTotalCost(platform)
          const isBest = index === 0
          const isWorst = index === ranked.length - 1 && ranked.length > 1
          const diff = isBest ? null : totalFees - computeTotalCost(ranked[0])

          return (
            <div
              key={platform.platform}
              className={cn(
                'flex items-center gap-4 px-5 py-4',
                isBest && 'bg-amber-50',
              )}
            >
              {/* Rank */}
              <div
                className={cn(
                  'w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold shrink-0',
                  isBest
                    ? 'bg-amber-400 text-amber-900'
                    : isWorst
                    ? 'bg-gray-200 text-gray-500'
                    : 'bg-gray-100 text-gray-600',
                )}
              >
                {index + 1}
              </div>

              {/* Platform */}
              <div className="flex-1 min-w-0">
                <PlatformBadge platform={platform.platform} />
                {platform.promo_text && (
                  <p className="text-xs text-green-600 mt-1 truncate">{platform.promo_text}</p>
                )}
              </div>

              {/* ETA */}
              <div className="text-xs text-gray-400 hidden sm:block shrink-0">
                {formatETA(platform.estimated_delivery_minutes)}
              </div>

              {/* Total fees */}
              <div className="text-right shrink-0">
                <div
                  className={cn(
                    'font-bold text-sm',
                    isBest ? 'text-amber-600' : isWorst ? 'text-red-500' : 'text-gray-700',
                  )}
                >
                  {formatPrice(totalFees)}
                </div>
                {diff != null && diff > 0 && (
                  <div className="text-xs text-red-400">+{formatPrice(diff)} more</div>
                )}
                {isBest && (
                  <div className="text-xs text-amber-600 font-medium">Best Deal</div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
