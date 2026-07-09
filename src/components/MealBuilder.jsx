import { forwardRef, useImperativeHandle, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ChefHat,
  Crown,
  Minus,
  Plus,
  Trash2,
  X,
} from 'lucide-react'
import { cn, formatPrice } from '../lib/utils.js'
import { estimateMealCost, taxRateForLocation } from '../utils/mealCost.js'
import PlatformBadge from './PlatformBadge.jsx'

// "Build your meal" cost calculator: users assemble a basket from the
// comparison table / full menus, and each platform panel shows the estimated
// real total (items + delivery + service + small-order fee + est. tax).
//
// This is a comparison/estimation tool, NOT a cart — nothing is persisted or
// sent anywhere; state is local useState only. Items are added from outside
// (MenuComparison rows and Full Menu rows on RestaurantDetail) through the
// imperative ref handle {addFromComparisonRow, addFromMenuItem}, plus the
// built-in quick-add chips sourced from menuComparison.

const normalizeKey = (name) => (name || '').trim().toLowerCase()

function formatPct(pct) {
  return `${Number(pct.toFixed(2))}%`
}

function mergePrices(existing, incoming) {
  // Existing prices win, EXCEPT that a positive incoming price replaces a
  // stored $0 — a $0 is at best a freebie and at worst a "price varies"
  // placeholder, so real evidence from a later add must not be blocked.
  const merged = { ...incoming }
  for (const [platform, price] of Object.entries(existing)) {
    if (price != null && !(price === 0 && merged[platform] > 0)) {
      merged[platform] = price
    }
  }
  return merged
}

// Mirror of the backend's ensure_fee_schedule() flat-field fallback, for old
// cached payloads that predate fee_schedule. No platform defaults here — the
// backend owns that table; a schedule this thin just yields "unknown" fees.
function scheduleFor(platform) {
  if (platform.fee_schedule) return platform.fee_schedule
  return {
    delivery_fee: platform.delivery_fee ?? null,
    service_fee_flat: platform.service_fee > 0 ? platform.service_fee : null,
    minimum_order: platform.minimum_order ?? null,
    estimated_fields: [],
  }
}

const MealBuilder = forwardRef(function MealBuilder(
  { platforms = [], menuComparison = [], location = '', mode = 'delivery' },
  ref,
) {
  const [entries, setEntries] = useState([])
  const isPickup = mode === 'pickup'

  // platform -> (normalized item name -> price), for matching menu items
  // across platforms by name. A $0 match is a "price varies" placeholder,
  // not a price — counting it would make that platform's total look
  // artificially cheap, so only positive prices enter the index. (Adding a
  // genuine $0 freebie from its own menu still works via addFromMenuItem.)
  const menuIndex = useMemo(() => {
    const index = new Map()
    for (const p of platforms) {
      const byName = new Map()
      for (const item of p.menu_items || []) {
        const key = normalizeKey(item.name)
        if (key && item.price > 0 && !byName.has(key)) byName.set(key, item.price)
      }
      index.set(p.platform, byName)
    }
    return index
  }, [platforms])

  const addEntry = (entry) => {
    if (!entry.key) return
    setEntries((prev) => {
      const i = prev.findIndex((e) => e.key === entry.key)
      if (i === -1) return [...prev, { ...entry, qty: 1 }]
      return prev.map((e, j) =>
        j === i
          ? { ...e, qty: e.qty + 1, prices: mergePrices(e.prices, entry.prices) }
          : e,
      )
    })
  }

  const addFromComparisonRow = (row) => {
    addEntry({
      key: normalizeKey(row.item_name),
      name: row.item_name,
      prices: { ...(row.prices || {}) },
    })
  }

  const addFromMenuItem = (platformName, item) => {
    const key = normalizeKey(item.name)
    const prices = {}
    for (const p of platforms) {
      if (p.platform === platformName) {
        prices[p.platform] = item.price ?? null
      } else {
        prices[p.platform] = menuIndex.get(p.platform)?.get(key) ?? null
      }
    }
    // A $0 origin price is trustworthy only when NO platform prices the
    // item positively (genuine freebie, e.g. sauce packets). If another
    // platform has a real price for the same item, the $0 is a "price
    // varies" placeholder and must count as unpriced there — otherwise the
    // origin platform gets crowned Best Total on fabricated $0 food.
    if (prices[platformName] === 0) {
      const pricedElsewhere = Object.values(prices).some((v) => v > 0)
      if (pricedElsewhere) prices[platformName] = null
    }
    addEntry({ key, name: item.name, prices })
  }

  useImperativeHandle(ref, () => ({ addFromComparisonRow, addFromMenuItem }))

  const setQty = (key, delta) => {
    setEntries((prev) =>
      prev.map((e) =>
        e.key === key ? { ...e, qty: Math.max(1, e.qty + delta) } : e,
      ),
    )
  }
  const removeEntry = (key) => setEntries((prev) => prev.filter((e) => e.key !== key))

  const taxInfo = useMemo(() => taxRateForLocation(location), [location])

  const quickAdds = useMemo(
    () =>
      [...menuComparison]
        .sort((a, b) => (b.price_difference || 0) - (a.price_difference || 0))
        .slice(0, 4),
    [menuComparison],
  )

  // One estimate panel per platform.
  const panels = platforms.map((p) => {
    const priced = entries.filter((e) => e.prices[p.platform] != null)
    const subtotal = priced.reduce(
      (sum, e) => sum + e.prices[p.platform] * e.qty,
      0,
    )
    const est = estimateMealCost(
      scheduleFor(p),
      subtotal,
      mode,
      taxInfo?.ratePct ?? null,
    )
    return {
      platform: p.platform,
      pricedCount: priced.length,
      complete: entries.length > 0 && priced.length === entries.length,
      est,
    }
  })

  const completePanels = panels.filter((panel) => panel.complete)
  const bestTotal = completePanels.length
    ? Math.min(...completePanels.map((panel) => panel.est.total))
    : null
  const bestPlatform = completePanels.find((panel) => panel.est.total === bestTotal)
    ?.platform

  const totalQty = entries.reduce((sum, e) => sum + e.qty, 0)

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2">
          <ChefHat className="w-4 h-4 text-orange-500" />
          <h3 className="font-semibold text-gray-900">Build your meal</h3>
          {totalQty > 0 && (
            <span className="text-xs font-semibold text-orange-700 bg-orange-50 border border-orange-200 rounded-full px-2 py-0.5 tabular-nums">
              {totalQty} item{totalQty !== 1 ? 's' : ''}
            </span>
          )}
        </div>
        {entries.length > 0 && (
          <button
            type="button"
            onClick={() => setEntries([])}
            className="inline-flex items-center gap-1 text-xs font-medium text-gray-400 hover:text-rose-500 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Clear meal
          </button>
        )}
      </div>
      <p className="text-xs text-gray-400 mb-4">
        Pick items to see the estimated {isPickup ? 'pickup' : 'delivered'} total
        on each platform — fees, small-order charges, and tax included.
      </p>

      {/* Quick add from the comparison table */}
      {quickAdds.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mb-4">
          <span className="text-xs text-gray-400 mr-0.5">Quick add:</span>
          {quickAdds.map((row) => (
            <button
              key={row.item_name}
              type="button"
              onClick={() => addFromComparisonRow(row)}
              aria-label={`Add ${row.item_name} to meal`}
              className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full border border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors"
            >
              <Plus className="w-3 h-3" />
              <span className="max-w-40 truncate">{row.item_name}</span>
            </button>
          ))}
        </div>
      )}

      {entries.length === 0 ? (
        /* Empty state */
        <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/50 px-6 py-8 flex flex-col items-center text-center gap-2">
          <ChefHat className="w-7 h-7 text-gray-300" />
          <p className="font-semibold text-gray-600 text-sm">
            Your meal is empty
          </p>
          <p className="text-xs text-gray-400 max-w-sm">
            Use the <span className="font-semibold">Add</span> buttons on the
            price comparison and full menus to build a meal, then compare what
            it would really cost on each platform.
          </p>
        </div>
      ) : (
        <>
          {/* Entry list */}
          <div className="divide-y divide-gray-100 border-y border-gray-100 mb-4">
            {entries.map((e) => {
              const known = Object.values(e.prices).filter((v) => v != null)
              const from = known.length ? Math.min(...known) : null
              return (
                <div key={e.key} className="flex items-center gap-3 py-2.5">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {e.name}
                    </p>
                    <p className="text-xs text-gray-400 tabular-nums">
                      {from != null
                        ? `from ${formatPrice(from)} · priced on ${known.length} of ${platforms.length} platform${platforms.length !== 1 ? 's' : ''}`
                        : 'no price found on any platform'}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      type="button"
                      onClick={() => setQty(e.key, -1)}
                      disabled={e.qty <= 1}
                      aria-label={`Decrease ${e.name} quantity`}
                      className="w-6 h-6 rounded-full border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40 flex items-center justify-center text-gray-600 transition-colors"
                    >
                      <Minus className="w-3.5 h-3.5" />
                    </button>
                    <span className="w-6 text-center text-sm font-semibold text-gray-800 tabular-nums">
                      {e.qty}
                    </span>
                    <button
                      type="button"
                      onClick={() => setQty(e.key, 1)}
                      aria-label={`Increase ${e.name} quantity`}
                      className="w-6 h-6 rounded-full border border-gray-200 bg-white hover:bg-gray-50 flex items-center justify-center text-gray-600 transition-colors"
                    >
                      <Plus className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeEntry(e.key)}
                    aria-label={`Remove ${e.name}`}
                    className="shrink-0 text-gray-300 hover:text-rose-500 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              )
            })}
          </div>

          {/* Per-platform totals */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 pt-2">
            {panels.map((panel) => (
              <PlatformPanel
                key={panel.platform}
                panel={panel}
                entryCount={entries.length}
                isBest={panel.platform === bestPlatform}
                bestTotal={bestTotal}
                isPickup={isPickup}
                taxInfo={taxInfo}
              />
            ))}
          </div>
        </>
      )}

      {/* Standing disclaimer */}
      <p className="text-[11px] text-gray-400 mt-4">
        Estimates for comparison only — this is not a cart or checkout. Fees,
        taxes, promos, and item availability change at checkout; always confirm
        the final total on each platform before ordering.
      </p>
    </div>
  )
})

export default MealBuilder

function EstChip() {
  return (
    <span className="text-[9px] font-semibold uppercase tracking-wide text-gray-400 bg-gray-100 border border-gray-200 rounded px-1 py-px">
      est.
    </span>
  )
}

function PanelRow({ label, children }) {
  return (
    <div className="flex justify-between items-center gap-2 text-xs">
      <span className="text-gray-500">{label}</span>
      {children}
    </div>
  )
}

function PlatformPanel({ panel, entryCount, isBest, bestTotal, isPickup, taxInfo }) {
  const { est, pricedCount, complete } = panel
  const estimatedFields = est.estimated_fields || []
  const serviceEstimated = estimatedFields.includes('service_fee_pct')
  const taxEstimated = estimatedFields.includes('tax_rate_pct')
  const delta = complete && !isBest && bestTotal != null ? est.total - bestTotal : 0

  return (
    <div
      className={cn(
        'relative rounded-2xl border-2 p-4 pt-5',
        isBest
          ? 'border-amber-400 bg-amber-50/40 shadow-md shadow-amber-100'
          : 'border-gray-200 bg-white',
      )}
    >
      {isBest && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 flex items-center gap-1 bg-gradient-to-r from-amber-400 to-orange-400 text-amber-900 text-[11px] font-bold px-3 py-0.5 rounded-full shadow-sm whitespace-nowrap">
          <Crown className="w-3 h-3" />
          Best Total
        </div>
      )}

      <div className="flex items-center justify-between gap-2 mb-3">
        <PlatformBadge platform={panel.platform} />
        {delta > 0.005 && (
          <span className="text-[11px] font-semibold text-gray-400 tabular-nums whitespace-nowrap">
            +{formatPrice(delta)} vs best
          </span>
        )}
      </div>

      <div className="space-y-1.5">
        <PanelRow label="Items">
          <span className="font-medium text-gray-700 tabular-nums">
            {est.subtotal === 0 ? '$0.00' : formatPrice(est.subtotal)}
          </span>
        </PanelRow>
        {pricedCount < entryCount && (
          <p className="text-[11px] text-amber-600 font-medium">
            {pricedCount} of {entryCount} items priced here
          </p>
        )}

        {isPickup ? (
          <p className="text-[11px] text-violet-600 font-medium">
            Pickup — delivery, service & small-order fees waived
          </p>
        ) : (
          <>
            <PanelRow label="Delivery fee">
              <span
                className={cn(
                  'font-medium tabular-nums',
                  est.delivery_fee === 0 ? 'text-emerald-600' : 'text-gray-700',
                )}
              >
                {formatPrice(est.delivery_fee)}
              </span>
            </PanelRow>
            <PanelRow label="Service fee">
              {est.service_fee == null ? (
                <span className="font-medium text-gray-400">unknown</span>
              ) : (
                <span className="inline-flex items-center gap-1">
                  {serviceEstimated && <EstChip />}
                  <span className="font-medium text-gray-700 tabular-nums">
                    {serviceEstimated ? '~' : ''}
                    {est.service_fee === 0 ? '$0.00' : formatPrice(est.service_fee)}
                  </span>
                </span>
              )}
            </PanelRow>
            {est.small_order_fee > 0 && (
              <PanelRow label="Small-order fee">
                <span className="inline-flex items-center gap-1">
                  {estimatedFields.includes('small_order_fee') && <EstChip />}
                  <span className="font-medium text-gray-700 tabular-nums">
                    {formatPrice(est.small_order_fee)}
                  </span>
                </span>
              </PanelRow>
            )}
          </>
        )}

        {est.tax_rate_pct != null && (
          <PanelRow label={`Tax (${formatPct(est.tax_rate_pct)}${taxEstimated && taxInfo ? ` ${taxInfo.statecode}` : ''})`}>
            <span className="inline-flex items-center gap-1">
              {taxEstimated && <EstChip />}
              <span className="font-medium text-gray-700 tabular-nums">
                {est.tax === 0 ? '$0.00' : formatPrice(est.tax)}
              </span>
            </span>
          </PanelRow>
        )}

        <div className="pt-1.5 border-t border-gray-200">
          <div className="flex justify-between items-baseline font-bold text-gray-900 text-sm">
            <span>
              Total
              {est.tax_rate_pct == null && (
                <span className="font-normal text-[10px] text-gray-400"> (before tax)</span>
              )}
            </span>
            <span
              className={cn(
                'tabular-nums',
                isBest ? 'text-amber-600' : isPickup ? 'text-violet-600' : 'text-gray-900',
              )}
            >
              {est.total === 0 ? '$0.00' : formatPrice(est.total)}
            </span>
          </div>
        </div>

        {est.below_minimum && !isPickup && (
          <div className="inline-flex items-center gap-1 text-[11px] font-semibold rounded-full px-2 py-0.5 border bg-amber-50 text-amber-700 border-amber-200">
            <AlertTriangle className="w-3 h-3" />
            Below {formatPrice(est.minimum_order)} minimum
          </div>
        )}
      </div>
    </div>
  )
}
