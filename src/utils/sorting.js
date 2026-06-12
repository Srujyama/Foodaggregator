export function computeTotalCost(platform) {
  return (platform.delivery_fee || 0) + (platform.service_fee || 0)
}

export function computePickupCost(platform) {
  return (platform.pickup_fee || 0) + (platform.pickup_service_fee || 0)
}

export function computeCost(platform, mode = 'delivery') {
  if (mode === 'pickup') return computePickupCost(platform)
  return computeTotalCost(platform)
}

export function rankByBestDeal(aggregatedResult, mode = 'delivery') {
  return [...aggregatedResult.platforms].sort(
    (a, b) => computeCost(a, mode) - computeCost(b, mode),
  )
}

export function getBestDealPlatform(aggregatedResult, mode = 'delivery') {
  if (!aggregatedResult.platforms?.length) return null
  return rankByBestDeal(aggregatedResult, mode)[0]
}

export function getSavings(aggregatedResult, mode = 'delivery') {
  const ranked = rankByBestDeal(aggregatedResult, mode)
  if (ranked.length < 2) return 0
  return computeCost(ranked[ranked.length - 1], mode) - computeCost(ranked[0], mode)
}

export function getMenuSavings(aggregatedResult) {
  if (!aggregatedResult.menu_comparison?.length) return 0
  return aggregatedResult.menu_comparison.reduce(
    (sum, item) => sum + (item.price_difference || 0),
    0,
  )
}

export function getBestRating(aggregatedResult) {
  const ratings = (aggregatedResult.platforms || [])
    .map((p) => p.rating)
    .filter((r) => typeof r === 'number' && r > 0)
  return ratings.length ? Math.max(...ratings) : 0
}

export function getFastestEta(aggregatedResult, mode = 'delivery') {
  const key = mode === 'pickup' ? 'estimated_pickup_minutes' : 'estimated_delivery_minutes'
  const etas = (aggregatedResult.platforms || [])
    .map((p) => p[key])
    .filter((e) => typeof e === 'number' && e > 0)
  return etas.length ? Math.min(...etas) : Infinity
}

export function hasPromo(aggregatedResult) {
  return (aggregatedResult.platforms || []).some((p) => p.promo_text)
}

export function isPlatformOpen(platform) {
  // Unknown status (nulls) counts as open — scrapers often omit the flags,
  // and hiding a restaurant on missing data is worse than showing it.
  return platform.is_open !== false && platform.accepting_orders !== false
}

export function isOpenNow(aggregatedResult) {
  return (aggregatedResult.platforms || []).some(isPlatformOpen)
}

export const SORT_OPTIONS = [
  { key: 'best', label: 'Best match' },
  { key: 'fees', label: 'Lowest fees' },
  { key: 'savings', label: 'Biggest savings' },
  { key: 'rating', label: 'Top rated' },
  { key: 'eta', label: 'Fastest' },
  { key: 'platforms', label: 'Most apps' },
]

export function sortResults(results, sortKey, mode = 'delivery') {
  if (!results?.length || sortKey === 'best') return results || []

  const indexed = results.map((r, i) => [r, i])
  const compare = {
    fees: (a, b) => {
      const ba = getBestDealPlatform(a, mode)
      const bb = getBestDealPlatform(b, mode)
      return (ba ? computeCost(ba, mode) : Infinity) - (bb ? computeCost(bb, mode) : Infinity)
    },
    savings: (a, b) =>
      getSavings(b, mode) + getMenuSavings(b) - (getSavings(a, mode) + getMenuSavings(a)),
    rating: (a, b) => getBestRating(b) - getBestRating(a),
    eta: (a, b) => getFastestEta(a, mode) - getFastestEta(b, mode),
    platforms: (a, b) => (b.platforms?.length || 0) - (a.platforms?.length || 0),
  }[sortKey]

  if (!compare) return results
  indexed.sort(([a, ai], [b, bi]) => compare(a, b) || ai - bi)
  return indexed.map(([r]) => r)
}

export const EMPTY_FILTERS = {
  platforms: [], // empty = all platforms
  openNow: false,
  promoOnly: false,
  multiOnly: false,
}

export function hasActiveFilters(filters) {
  return (
    filters.platforms.length > 0 ||
    filters.openNow ||
    filters.promoOnly ||
    filters.multiOnly
  )
}

export function filterResults(results, filters) {
  if (!results?.length || !hasActiveFilters(filters)) return results || []
  return results.filter((r) => {
    if (
      filters.platforms.length > 0 &&
      !r.platforms?.some((p) => filters.platforms.includes(p.platform))
    ) {
      return false
    }
    if (filters.openNow && !isOpenNow(r)) return false
    if (filters.promoOnly && !hasPromo(r)) return false
    if (filters.multiOnly && (r.platforms?.length || 0) < 2) return false
    return true
  })
}

export function getCheapestMenuPlatform(aggregatedResult) {
  const markup = aggregatedResult.avg_menu_markup_by_platform
  if (!markup || Object.keys(markup).length === 0) return null

  let cheapest = null
  let minMarkup = Infinity
  for (const [platform, pct] of Object.entries(markup)) {
    if (pct < minMarkup) {
      minMarkup = pct
      cheapest = platform
    }
  }
  return cheapest
}
