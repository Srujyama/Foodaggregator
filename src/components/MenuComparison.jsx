import { useState } from 'react'
import { ArrowDown, Search, TrendingDown, Trophy } from 'lucide-react'
import { formatPrice } from '../lib/utils.js'
import { cn } from '../lib/utils.js'
import PlatformBadge from './PlatformBadge.jsx'

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

export default function MenuComparison({ menuComparison, platforms, avgMarkup }) {
  const [query, setQuery] = useState('')
  const [diffOnly, setDiffOnly] = useState(false)

  if (!menuComparison || menuComparison.length === 0) return null

  const platformNames = platforms.map((p) => p.platform)
  // Items with price differences first, then items available on most platforms
  const sortedItems = [...menuComparison].sort(
    (a, b) => b.price_difference - a.price_difference,
  )
  const itemsWithDiff = sortedItems.filter((item) => item.price_difference > 0)
  const totalSavings = itemsWithDiff.reduce((sum, item) => sum + item.price_difference, 0)

  const q = query.trim().toLowerCase()
  const filteredItems = sortedItems.filter((item) => {
    if (q && !(item.item_name || '').toLowerCase().includes(q)) return false
    if (diffOnly && !(item.price_difference > 0.01)) return false
    return true
  })
  const visibleItems = filteredItems.slice(0, 30)

  const clearFilters = () => {
    setQuery('')
    setDiffOnly(false)
  }

  return (
    <div className="space-y-6">
      {/* Summary banner */}
      {avgMarkup && Object.keys(avgMarkup).length > 1 && (
        <div className="bg-gradient-to-r from-amber-50 to-orange-50 rounded-2xl border border-amber-200 p-5">
          <div className="flex items-center gap-2 mb-3">
            <TrendingDown className="w-4 h-4 text-amber-600" />
            <h3 className="font-semibold text-gray-900">Menu Price Summary</h3>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {platformNames.map((platform) => {
              const markup = avgMarkup[platform]
              const isCheapest =
                markup !== undefined &&
                markup ===
                  Math.min(
                    ...Object.values(avgMarkup).filter((v) => v !== undefined),
                  )

              return (
                <div
                  key={platform}
                  className={cn(
                    'rounded-xl p-3 text-center border',
                    isCheapest
                      ? 'bg-green-50 border-green-200'
                      : 'bg-white border-gray-200',
                  )}
                >
                  <PlatformBadge platform={platform} size="sm" />
                  <div className="mt-2">
                    {markup !== undefined ? (
                      <>
                        <span
                          className={cn(
                            'text-lg font-bold',
                            isCheapest
                              ? 'text-green-600'
                              : markup > 5
                              ? 'text-red-500'
                              : 'text-gray-700',
                          )}
                        >
                          {markup === 0
                            ? 'Cheapest'
                            : `+${markup.toFixed(1)}%`}
                        </span>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {isCheapest ? 'Best menu prices' : 'avg. markup'}
                        </p>
                      </>
                    ) : (
                      <span className="text-sm text-gray-400">No menu data</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          {totalSavings > 0 && (
            <p className="text-xs text-amber-700 mt-3 text-center">
              Up to {formatPrice(totalSavings)} total savings across{' '}
              {itemsWithDiff.length} comparable item
              {itemsWithDiff.length !== 1 ? 's' : ''} by choosing the cheapest
              platform for each.
            </p>
          )}
        </div>
      )}

      {/* Comparison table */}
      <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 bg-gray-50 flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold text-gray-900">
            Menu Price Comparison ({menuComparison.length} item
            {menuComparison.length !== 1 ? 's' : ''})
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            {itemsWithDiff.length > 0 && (
              <span className="text-xs text-gray-400">
                {itemsWithDiff.length} item{itemsWithDiff.length !== 1 ? 's' : ''}{' '}
                with price differences
              </span>
            )}
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter items..."
                className="w-40 sm:w-48 text-xs rounded-lg border border-gray-200 bg-white pl-8 pr-2.5 py-1.5 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-200"
              />
            </div>
            <button
              type="button"
              aria-pressed={diffOnly}
              onClick={() => setDiffOnly((v) => !v)}
              className={cn(
                'text-xs font-medium px-2.5 py-1 rounded-full border',
                diffOnly
                  ? 'bg-amber-400 text-amber-950 border-amber-400'
                  : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50',
              )}
            >
              Differences only
            </button>
          </div>
        </div>

        {/* Table (scrolls horizontally on narrow screens instead of crushing columns) */}
        <div className="overflow-x-auto">
          <div
            className="grid gap-0 divide-y divide-gray-100"
            style={{ minWidth: `${200 + platformNames.length * 96}px` }}
          >
            <div className="grid grid-cols-[1fr_repeat(var(--cols),minmax(80px,1fr))] gap-2 px-5 py-3 bg-gray-50 text-xs font-medium text-gray-500"
              style={{ '--cols': platformNames.length }}
            >
              <div>Item</div>
              {platformNames.map((p) => (
                <div key={p} className="text-center">
                  {PLATFORM_LABELS[p] || p}
                </div>
              ))}
            </div>

            {/* Table rows */}
            {visibleItems.length === 0 && (
              <div className="px-5 py-6 text-center text-sm text-gray-500">
                No items match —{' '}
                <button
                  type="button"
                  onClick={clearFilters}
                  className="font-medium text-amber-600 hover:underline"
                >
                  clear the filter
                </button>
                .
              </div>
            )}
            {visibleItems.map((item, idx) => (
              <div
                key={idx}
                className={cn(
                  'grid gap-2 px-5 py-3 text-sm items-center hover:bg-gray-50',
                  item.price_difference > 0 && 'bg-amber-50/30',
                )}
                style={{
                  gridTemplateColumns: `1fr repeat(${platformNames.length}, minmax(80px, 1fr))`,
                }}
              >
                <div className="min-w-0">
                  <p className="font-medium text-gray-900 truncate">{item.item_name}</p>
                  {item.price_difference > 0.01 && (
                    <p className="text-xs text-green-600 flex items-center gap-1 mt-0.5">
                      <ArrowDown className="w-3 h-3" />
                      Save {formatPrice(item.price_difference)}
                    </p>
                  )}
                </div>
                {platformNames.map((platform) => {
                  const price = item.prices[platform]
                  const isCheapest = platform === item.cheapest_platform && item.price_difference > 0
                  const isAvailable = price != null

                  return (
                    <div key={platform} className="text-center">
                      {isAvailable ? (
                        <span
                          className={cn(
                            'font-medium tabular-nums',
                            isCheapest
                              ? 'text-green-600 font-bold'
                              : 'text-gray-700',
                          )}
                        >
                          {formatPrice(price)}
                          {isCheapest && (
                            <Trophy className="w-3 h-3 text-amber-400 inline ml-1" />
                          )}
                        </span>
                      ) : (
                        <span className="text-gray-300">--</span>
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>

        {filteredItems.length > 0 && (
          <div className="px-5 py-3 border-t border-gray-100 text-center text-xs text-gray-400">
            Showing {visibleItems.length} of {filteredItems.length} comparable item
            {filteredItems.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  )
}
