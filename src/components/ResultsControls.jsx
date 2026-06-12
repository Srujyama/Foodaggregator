import {
  Sparkles, CircleDollarSign, TrendingDown, Star, Timer, Layers,
  DoorOpen, BadgePercent, X,
} from 'lucide-react'
import { SORT_OPTIONS, hasActiveFilters } from '../utils/sorting.js'
import { cn } from '../lib/utils.js'

const SORT_ICONS = {
  best: Sparkles,
  fees: CircleDollarSign,
  savings: TrendingDown,
  rating: Star,
  eta: Timer,
  platforms: Layers,
}

const PLATFORM_LABELS = {
  uber_eats: 'Uber Eats', doordash: 'DoorDash', grubhub: 'Grubhub',
  postmates: 'Postmates', seamless: 'Seamless', caviar: 'Caviar',
  gopuff: 'gopuff', eatstreet: 'EatStreet',
}

// Active shades are the darkest of each brand family that keeps 12px white
// text at >= 4.5:1 (WCAG AA) — orange-500/sky-500/teal-600/emerald-600 fail.
const PLATFORM_STYLES = {
  uber_eats: { active: 'bg-gray-900 text-white border-gray-900', idle: 'bg-white text-gray-700 border-gray-200 hover:border-gray-400' },
  doordash: { active: 'bg-red-600 text-white border-red-600', idle: 'bg-white text-red-700 border-red-100 hover:border-red-300' },
  grubhub: { active: 'bg-orange-700 text-white border-orange-700', idle: 'bg-white text-orange-700 border-orange-100 hover:border-orange-300' },
  postmates: { active: 'bg-gray-800 text-white border-gray-800', idle: 'bg-white text-gray-700 border-gray-200 hover:border-gray-400' },
  seamless: { active: 'bg-blue-600 text-white border-blue-600', idle: 'bg-white text-blue-700 border-blue-100 hover:border-blue-300' },
  caviar: { active: 'bg-purple-700 text-white border-purple-700', idle: 'bg-white text-purple-700 border-purple-100 hover:border-purple-300' },
  gopuff: { active: 'bg-sky-700 text-white border-sky-700', idle: 'bg-white text-sky-700 border-sky-100 hover:border-sky-300' },
  eatstreet: { active: 'bg-teal-700 text-white border-teal-700', idle: 'bg-white text-teal-700 border-teal-100 hover:border-teal-300' },
}

function ToggleChip({ active, onClick, icon: Icon, children, activeClass }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full border transition-all duration-200 select-none',
        active
          ? activeClass
          : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400',
      )}
    >
      <Icon className="w-3.5 h-3.5" />
      {children}
    </button>
  )
}

export default function ResultsControls({
  sortKey, onSortChange, filters, onFiltersChange, platformCounts,
}) {
  const filtersActive = hasActiveFilters(filters)

  const togglePlatform = (platform) => {
    const next = filters.platforms.includes(platform)
      ? filters.platforms.filter((p) => p !== platform)
      : [...filters.platforms, platform]
    onFiltersChange({ ...filters, platforms: next })
  }

  const toggle = (key) => onFiltersChange({ ...filters, [key]: !filters[key] })

  const clearAll = () =>
    onFiltersChange({ platforms: [], openNow: false, promoOnly: false, multiOnly: false })

  // Offer chips for platforms with results, plus any platform that's active
  // in the URL filter even at zero results — otherwise a shared/back-button
  // URL like ?fplat=doordash leaves an invisible filter the user can't clear
  // chip-by-chip.
  const availablePlatforms = Object.keys(PLATFORM_LABELS)
    .filter((p) => (platformCounts?.[p] || 0) > 0 || filters.platforms.includes(p))
    .map((p) => [p, platformCounts?.[p] || 0])

  return (
    <div className="space-y-3">
      {/* Sort pills: plain toggles, not ARIA radios — radios would owe the
          roving-tabindex arrow-key pattern, and buttons are honest here. */}
      <div
        aria-label="Sort results"
        className="flex items-center gap-1.5 overflow-x-auto pb-1 -mb-1 scrollbar-none"
      >
        <span className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold shrink-0 mr-1">
          Sort
        </span>
        {SORT_OPTIONS.map(({ key, label }) => {
          const Icon = SORT_ICONS[key]
          const active = sortKey === key
          return (
            <button
              key={key}
              type="button"
              aria-pressed={active}
              onClick={() => onSortChange(key)}
              className={cn(
                'inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full border whitespace-nowrap transition-all duration-200 select-none shrink-0',
                active
                  ? 'bg-gradient-to-r from-orange-500 to-red-500 text-white border-transparent shadow-sm'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-orange-300 hover:text-orange-600',
              )}
            >
              <Icon className={cn('w-3.5 h-3.5', active && key === 'rating' && 'fill-white')} />
              {label}
            </button>
          )
        })}
      </div>

      {/* Filter chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold mr-1">
          Filter
        </span>
        {availablePlatforms.map(([platform, count]) => {
          const active = filters.platforms.includes(platform)
          const styles = PLATFORM_STYLES[platform] || PLATFORM_STYLES.uber_eats
          return (
            <button
              key={platform}
              type="button"
              aria-pressed={active}
              onClick={() => togglePlatform(platform)}
              className={cn(
                'inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1.5 rounded-full border transition-all duration-200 select-none',
                active ? styles.active : styles.idle,
              )}
            >
              {PLATFORM_LABELS[platform] || platform}
              <span className={cn('tabular-nums', active ? 'opacity-80' : 'text-gray-400')}>
                {count}
              </span>
            </button>
          )
        })}

        <span className="w-px h-4 bg-gray-200 mx-1" aria-hidden="true" />

        <ToggleChip
          active={filters.openNow}
          onClick={() => toggle('openNow')}
          icon={DoorOpen}
          activeClass="bg-emerald-700 text-white border-emerald-700"
        >
          Open now
        </ToggleChip>
        <ToggleChip
          active={filters.promoOnly}
          onClick={() => toggle('promoOnly')}
          icon={BadgePercent}
          activeClass="bg-pink-600 text-white border-pink-600"
        >
          Has promo
        </ToggleChip>
        <ToggleChip
          active={filters.multiOnly}
          onClick={() => toggle('multiOnly')}
          icon={Layers}
          activeClass="bg-indigo-600 text-white border-indigo-600"
        >
          On 2+ apps
        </ToggleChip>

        {filtersActive && (
          <button
            type="button"
            onClick={clearAll}
            className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1.5 rounded-full text-rose-600 hover:bg-rose-50 transition-colors duration-200"
          >
            <X className="w-3.5 h-3.5" />
            Clear
          </button>
        )}
      </div>
    </div>
  )
}
