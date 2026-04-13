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
