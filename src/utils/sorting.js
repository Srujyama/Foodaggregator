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
