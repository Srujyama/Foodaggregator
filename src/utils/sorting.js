export function computeTotalCost(platform) {
  return (platform.delivery_fee || 0) + (platform.service_fee || 0)
}

export function rankByBestDeal(aggregatedResult) {
  return [...aggregatedResult.platforms].sort(
    (a, b) => computeTotalCost(a) - computeTotalCost(b),
  )
}

export function getBestDealPlatform(aggregatedResult) {
  if (!aggregatedResult.platforms?.length) return null
  return rankByBestDeal(aggregatedResult)[0]
}

export function getSavings(aggregatedResult) {
  const ranked = rankByBestDeal(aggregatedResult)
  if (ranked.length < 2) return 0
  return computeTotalCost(ranked[ranked.length - 1]) - computeTotalCost(ranked[0])
}

/**
 * Compute the total potential savings from menu price differences.
 * This sums the price_difference for all compared menu items.
 */
export function getMenuSavings(aggregatedResult) {
  if (!aggregatedResult.menu_comparison?.length) return 0
  return aggregatedResult.menu_comparison.reduce(
    (sum, item) => sum + (item.price_difference || 0),
    0,
  )
}

/**
 * Get the platform with the cheapest menu prices on average.
 * Returns the platform name or null.
 */
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
