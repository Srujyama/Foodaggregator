import { SORT_OPTIONS, EMPTY_FILTERS } from './sorting.js'

export const SORT_PARAM = 'sort'
export const PLATFORMS_PARAM = 'fplat'
export const OPEN_PARAM = 'open'
export const PROMO_PARAM = 'promo'
export const MULTI_PARAM = 'multi'

export const DEFAULT_SORT = 'best'

export const KNOWN_PLATFORM_IDS = [
  'uber_eats', 'doordash', 'grubhub', 'postmates',
  'seamless', 'caviar', 'gopuff', 'eatstreet',
]

const VALID_SORT_KEYS = new Set(SORT_OPTIONS.map((o) => o.key))
const VALID_PLATFORMS = new Set(KNOWN_PLATFORM_IDS)

// Unknown/invalid params fall back to defaults silently — URLs are user input.
export function parseQueryState(searchParams) {
  const rawSort = searchParams.get(SORT_PARAM)
  const sortKey = VALID_SORT_KEYS.has(rawSort) ? rawSort : DEFAULT_SORT

  const rawPlatforms = (searchParams.get(PLATFORMS_PARAM) || '')
    .split(',')
    .map((p) => p.trim())
    .filter((p) => VALID_PLATFORMS.has(p))

  return {
    sortKey,
    filters: {
      ...EMPTY_FILTERS,
      platforms: [...new Set(rawPlatforms)],
      openNow: searchParams.get(OPEN_PARAM) === '1',
      promoOnly: searchParams.get(PROMO_PARAM) === '1',
      multiOnly: searchParams.get(MULTI_PARAM) === '1',
    },
  }
}

// Returns a copy with sort/filter params applied; params at their default
// values are omitted so URLs stay clean. Unrelated params (q, location,
// mode, ...) pass through untouched.
export function applyQueryState(searchParams, sortKey, filters) {
  const next = new URLSearchParams(searchParams)

  const setOrOmit = (name, value) => {
    if (value) next.set(name, value)
    else next.delete(name)
  }

  setOrOmit(SORT_PARAM, sortKey !== DEFAULT_SORT ? sortKey : '')
  setOrOmit(PLATFORMS_PARAM, (filters.platforms || []).join(','))
  setOrOmit(OPEN_PARAM, filters.openNow ? '1' : '')
  setOrOmit(PROMO_PARAM, filters.promoOnly ? '1' : '')
  setOrOmit(MULTI_PARAM, filters.multiOnly ? '1' : '')

  return next
}
