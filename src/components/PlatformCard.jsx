import { Clock, Star, ExternalLink, Trophy, Bike, Car, MapPin, Phone, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import { formatPrice, formatETA } from '../lib/utils.js'
import { computeTotalCost, computePickupCost } from '../utils/sorting.js'
import PlatformBadge from './PlatformBadge.jsx'
import { cn } from '../lib/utils.js'

export default function PlatformCard({ platform, isBestDeal = false }) {
  const deliveryFees = computeTotalCost(platform)
  const pickupFees = computePickupCost(platform)
  const status = derivePlatformStatus(platform)

  return (
    <div
      className={cn(
        'relative rounded-2xl border-2 p-5 bg-white transition-all duration-300 hover:shadow-lg',
        isBestDeal
          ? 'border-amber-400 shadow-md shadow-amber-100'
          : 'border-gray-200 hover:border-orange-200',
        status?.tone === 'unavailable' && 'opacity-70',
      )}
    >
      {/* Best Deal badge */}
      {isBestDeal && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 flex items-center gap-1 bg-gradient-to-r from-amber-400 to-orange-400 text-amber-900 text-xs font-bold px-3 py-1 rounded-full shadow-sm">
          <Trophy className="w-3 h-3" />
          Best Deal
        </div>
      )}

      {/* Platform + rating */}
      <div className="flex items-center justify-between mb-3">
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

      {/* Status pill */}
      {status && (
        <div
          className={cn(
            'inline-flex items-center gap-1.5 text-[11px] font-semibold rounded-full px-2.5 py-1 mb-2 border',
            STATUS_TONE[status.tone],
          )}
        >
          {status.tone === 'available' && <CheckCircle2 className="w-3 h-3" />}
          {status.tone === 'warning' && <AlertTriangle className="w-3 h-3" />}
          {status.tone === 'unavailable' && <XCircle className="w-3 h-3" />}
          {status.label}
        </div>
      )}

      {/* Promo */}
      {platform.promo_text && (
        <div className="mb-3 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-1.5 font-medium line-clamp-3">
          {platform.promo_text}
        </div>
      )}

      {/* Delivery section */}
      <div className="rounded-xl bg-gray-50 p-3 mb-3">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-700 mb-2">
          <Bike className="w-3.5 h-3.5 text-orange-500" />
          Delivery
        </div>
        <div className="space-y-1.5">
          <FeeRow label="Delivery Fee" value={platform.delivery_fee} highlight={platform.delivery_fee === 0} />
          <FeeRow label="Service Fee" value={platform.service_fee} />
          {platform.minimum_order != null && (
            <FeeRow label="Min Order" value={platform.minimum_order} />
          )}
          <div className="pt-1.5 border-t border-gray-200">
            <div className="flex justify-between font-bold text-gray-900 text-sm">
              <span>Total Fees</span>
              <span className={cn(isBestDeal && 'text-amber-600')}>
                {formatPrice(deliveryFees)}
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400 mt-2">
          <span className="inline-flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {formatEtaRange(platform.estimated_delivery_minutes, platform.estimated_delivery_minutes_max)}
          </span>
          {platform.distance_text && (
            <span className="inline-flex items-center gap-1">
              <MapPin className="w-3 h-3" />
              {platform.distance_text}
            </span>
          )}
        </div>
      </div>

      {/* Pickup section */}
      {platform.pickup_available && (
        <div className="rounded-xl bg-violet-50/50 p-3 mb-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-700 mb-2">
            <Car className="w-3.5 h-3.5 text-violet-500" />
            Pickup
          </div>
          <div className="space-y-1.5">
            <FeeRow label="Pickup Fee" value={platform.pickup_fee} highlight={platform.pickup_fee === 0} />
            <FeeRow label="Service Fee" value={platform.pickup_service_fee} />
            <div className="pt-1.5 border-t border-violet-200/50">
              <div className="flex justify-between font-bold text-gray-900 text-sm">
                <span>Total Fees</span>
                <span className="text-violet-600">{formatPrice(pickupFees)}</span>
              </div>
            </div>
          </div>
          {platform.estimated_pickup_minutes && (
            <div className="flex items-center gap-1 text-xs text-gray-400 mt-2">
              <Clock className="w-3 h-3" />
              {formatETA(platform.estimated_pickup_minutes)} ready
            </div>
          )}
        </div>
      )}

      {/* Restaurant info */}
      {(platform.address || platform.phone || platform.hours_today_text) && (
        <div className="text-xs text-gray-500 space-y-1 mb-3">
          {platform.address && (
            <div className="flex items-start gap-1.5">
              <MapPin className="w-3 h-3 mt-0.5 shrink-0 text-gray-400" />
              <span className="leading-snug">{platform.address}</span>
            </div>
          )}
          {platform.phone && (
            <div className="flex items-center gap-1.5">
              <Phone className="w-3 h-3 shrink-0 text-gray-400" />
              <a href={`tel:${platform.phone}`} className="hover:text-orange-600">
                {platform.phone}
              </a>
            </div>
          )}
          {platform.hours_today_text && (
            <div className={cn(
              'flex items-center gap-1.5',
              platform.closing_soon && 'text-amber-600 font-medium',
            )}>
              <Clock className="w-3 h-3 shrink-0 text-gray-400" />
              {platform.hours_today_text}
              {platform.closing_soon && <span>· closing soon</span>}
            </div>
          )}
        </div>
      )}

      {/* Taxes disclaimer */}
      <p className="text-[10px] text-gray-400 italic mb-3">
        Taxes & tip not included.
      </p>

      {/* Last updated */}
      {platform.fetched_at && (
        <p className="text-[10px] text-gray-300 mb-2">
          Updated {formatRelativeTime(platform.fetched_at)}
        </p>
      )}

      {/* Link */}
      {platform.restaurant_url && (
        <a
          href={platform.restaurant_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl border-2 border-gray-200 text-sm font-medium text-gray-700 hover:border-orange-400 hover:text-orange-600 transition-all duration-200"
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
  postmates: 'Postmates',
  seamless: 'Seamless',
  caviar: 'Caviar',
  gopuff: 'gopuff',
  eatstreet: 'EatStreet',
}

const STATUS_TONE = {
  available: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  unavailable: 'bg-rose-50 text-rose-700 border-rose-200',
}

export function derivePlatformStatus(platform) {
  if (platform.is_within_delivery_range === false) {
    return { tone: 'unavailable', label: 'Outside delivery range' }
  }
  if (platform.accepting_orders === false || platform.is_open === false) {
    return {
      tone: 'unavailable',
      label: platform.status_text || 'Not accepting orders',
    }
  }
  if (platform.status_text) {
    return { tone: 'warning', label: platform.status_text }
  }
  if (platform.closing_soon) {
    return { tone: 'warning', label: 'Closing soon' }
  }
  if (platform.is_open === true || platform.accepting_orders === true) {
    return { tone: 'available', label: 'Open now' }
  }
  return null
}

function formatEtaRange(min, max) {
  if (!min) return formatETA(min)
  if (max && max !== min) return `${min}–${max} min`
  return formatETA(min)
}

function formatRelativeTime(iso) {
  try {
    const t = new Date(iso).getTime()
    if (!Number.isFinite(t)) return ''
    const diff = Math.max(0, Math.floor((Date.now() - t) / 1000))
    if (diff < 60) return `${diff}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return new Date(iso).toLocaleDateString()
  } catch {
    return ''
  }
}

function FeeRow({ label, value, highlight = false }) {
  return (
    <div className="flex justify-between text-xs">
      <span className="text-gray-500">{label}</span>
      <span className={cn('font-medium tabular-nums', highlight ? 'text-emerald-600' : 'text-gray-700')}>
        {formatPrice(value)}
      </span>
    </div>
  )
}
