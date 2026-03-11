import { Clock, Star, ExternalLink, Trophy } from 'lucide-react'
import { formatPrice, formatETA } from '../lib/utils.js'
import { computeTotalCost } from '../utils/sorting.js'
import PlatformBadge from './PlatformBadge.jsx'
import { cn } from '../lib/utils.js'

export default function PlatformCard({ platform, isBestDeal = false }) {
  const totalFees = computeTotalCost(platform)

  return (
    <div
      className={cn(
        'relative rounded-2xl border-2 p-5 bg-white transition-all hover:shadow-md',
        isBestDeal
          ? 'border-amber-400 shadow-amber-100 shadow-md'
          : 'border-gray-200 hover:border-orange-200',
      )}
    >
      {/* Best Deal badge */}
      {isBestDeal && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 flex items-center gap-1 bg-amber-400 text-amber-900 text-xs font-bold px-3 py-1 rounded-full shadow">
          <Trophy className="w-3 h-3" />
          Best Deal
        </div>
      )}

      {/* Platform + rating */}
      <div className="flex items-center justify-between mb-4">
        <PlatformBadge platform={platform.platform} size="md" />
        {platform.rating != null && (
          <div className="flex items-center gap-1 text-sm text-gray-500">
            <Star className="w-3.5 h-3.5 text-amber-400 fill-amber-400" />
            <span className="font-medium text-gray-700">{platform.rating.toFixed(1)}</span>
            {platform.rating_count && (
              <span className="text-xs">({platform.rating_count.toLocaleString()})</span>
            )}
          </div>
        )}
      </div>

      {/* Promo */}
      {platform.promo_text && (
        <div className="mb-3 text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-1.5 font-medium">
          {platform.promo_text}
        </div>
      )}

      {/* Fee breakdown */}
      <div className="space-y-2 mb-4">
        <FeeRow label="Delivery Fee" value={platform.delivery_fee} highlight={platform.delivery_fee === 0} />
        <FeeRow label="Service Fee" value={platform.service_fee} />
        {platform.minimum_order != null && (
          <FeeRow label="Minimum Order" value={platform.minimum_order} />
        )}
        <div className="pt-2 border-t border-gray-100">
          <div className="flex justify-between font-bold text-gray-900">
            <span>Total Fees</span>
            <span className={cn(isBestDeal && 'text-amber-600')}>
              {formatPrice(totalFees)}
            </span>
          </div>
        </div>
      </div>

      {/* ETA */}
      <div className="flex items-center gap-1.5 text-sm text-gray-500 mb-4">
        <Clock className="w-4 h-4" />
        <span>{formatETA(platform.estimated_delivery_minutes)} estimated</span>
      </div>

      {/* Link */}
      {platform.restaurant_url && (
        <a
          href={platform.restaurant_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl border-2 border-gray-200 text-sm font-medium text-gray-700 hover:border-orange-400 hover:text-orange-600 transition-colors"
        >
          Order on {PLATFORM_LABELS[platform.platform] || platform.platform}
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      )}
    </div>
  )
}

const PLATFORM_LABELS = {
  uber_eats: 'Uber Eats',
  doordash: 'DoorDash',
  grubhub: 'Grubhub',
}

function FeeRow({ label, value, highlight = false }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-gray-500">{label}</span>
      <span className={cn('font-medium', highlight ? 'text-green-600' : 'text-gray-800')}>
        {formatPrice(value)}
      </span>
    </div>
  )
}
