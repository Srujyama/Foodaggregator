import { Trophy, TrendingDown, Bike, Car } from 'lucide-react'
import { rankByBestDeal, computeTotalCost, computePickupCost, getSavings } from '../utils/sorting.js'
import { formatPrice, formatETA } from '../lib/utils.js'
import PlatformBadge from './PlatformBadge.jsx'
import { cn } from '../lib/utils.js'

export default function DealRanking({ aggregatedResult }) {
  const deliveryRanked = rankByBestDeal(aggregatedResult, 'delivery')
  const pickupRanked = rankByBestDeal(aggregatedResult, 'pickup')
  const deliverySavings = getSavings(aggregatedResult, 'delivery')
  const pickupSavings = getSavings(aggregatedResult, 'pickup')

  if (deliveryRanked.length === 0) return null

  return (
    <div className="space-y-4">
      {/* Delivery Ranking */}
      <RankingTable
        title="Delivery"
        icon={Bike}
        iconColor="text-orange-500"
        ranked={deliveryRanked}
        savings={deliverySavings}
        costFn={computeTotalCost}
        etaKey="estimated_delivery_minutes"
        accentColor="amber"
      />

      {/* Pickup Ranking */}
      <RankingTable
        title="Pickup"
        icon={Car}
        iconColor="text-violet-500"
        ranked={pickupRanked}
        savings={pickupSavings}
        costFn={computePickupCost}
        etaKey="estimated_pickup_minutes"
        accentColor="violet"
      />
    </div>
  )
}

function RankingTable({ title, icon: Icon, iconColor, ranked, savings, costFn, etaKey, accentColor }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon className={cn('w-4 h-4', iconColor)} />
          <h3 className="font-semibold text-gray-900">{title} Price Comparison</h3>
        </div>
        {savings > 0.01 && (
          <div className={cn(
            'flex items-center gap-1 text-xs border rounded-full px-3 py-1',
            accentColor === 'amber'
              ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
              : 'text-violet-700 bg-violet-50 border-violet-200',
          )}>
            <TrendingDown className="w-3 h-3" />
            Save up to {formatPrice(savings)}
          </div>
        )}
      </div>

      <div className="divide-y divide-gray-100">
        {ranked.map((platform, index) => {
          const totalFees = costFn(platform)
          const isBest = index === 0
          const isWorst = index === ranked.length - 1 && ranked.length > 1
          const diff = isBest ? null : totalFees - costFn(ranked[0])

          return (
            <div
              key={platform.platform}
              className={cn(
                'flex items-center gap-4 px-5 py-4 transition-colors',
                isBest && (accentColor === 'amber' ? 'bg-amber-50' : 'bg-violet-50'),
              )}
            >
              {/* Rank */}
              <div
                className={cn(
                  'w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold shrink-0',
                  isBest
                    ? (accentColor === 'amber' ? 'bg-amber-400 text-amber-900' : 'bg-violet-400 text-white')
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
                  <p className="text-xs text-emerald-600 mt-1 truncate">{platform.promo_text}</p>
                )}
              </div>

              {/* ETA */}
              <div className="text-xs text-gray-400 hidden sm:block shrink-0">
                {formatETA(platform[etaKey])}
              </div>

              {/* Total fees */}
              <div className="text-right shrink-0">
                <div
                  className={cn(
                    'font-bold text-sm tabular-nums',
                    isBest
                      ? (accentColor === 'amber' ? 'text-amber-600' : 'text-violet-600')
                      : isWorst ? 'text-red-500' : 'text-gray-700',
                  )}
                >
                  {formatPrice(totalFees)}
                </div>
                {diff != null && diff > 0 && (
                  <div className="text-xs text-red-400 tabular-nums">+{formatPrice(diff)} more</div>
                )}
                {isBest && (
                  <div className={cn(
                    'text-xs font-medium',
                    accentColor === 'amber' ? 'text-amber-600' : 'text-violet-600',
                  )}>
                    Best Deal
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
