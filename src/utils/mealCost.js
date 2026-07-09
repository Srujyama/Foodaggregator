// JS mirror of backend/app/services/pricing.py's meal-cost estimator.
//
// Parity is pinned by src/utils/mealCost.test.js, which runs the SAME shared
// vectors as backend/tests/test_pricing.py
// (backend/tests/fixtures/meal_cost_vectors.json). If you change rounding or
// clamping here, change the backend and the vectors together.
//
// All money values are float dollars; any schedule field may be null.

// Python-round(x, 2)-compatible money rounding, applied at the same points
// the backend rounds (subtotal, each fee, tax, total).
//
// Naive Math.round(x*100)/100 breaks parity: for 30 * 9.25% the exact double
// is 2.7749999999999999111..., which Python rounds to 2.77, but in JS
// 2.775 * 100 evaluates to exactly 277.5 (FP re-rounding), yielding 2.78.
// So we round the double's EXACT decimal expansion (via toFixed(18), which is
// spec-guaranteed correct) and break true binary ties half-to-even, exactly
// like CPython's float round.
function roundMoney(x) {
  if (!Number.isFinite(x)) return x
  const negative = x < 0
  const s = Math.abs(x).toFixed(18)
  const dot = s.indexOf('.')
  const frac = s.slice(dot + 1)
  let cents = parseInt(s.slice(0, dot) + frac.slice(0, 2), 10)
  const rest = frac.slice(2).replace(/0+$/, '')
  if (rest === '5') {
    // Exact representable tie (e.g. 0.125): round half to even.
    if (cents % 2 === 1) cents += 1
  } else if (rest && rest[0] >= '5') {
    cents += 1
  }
  const rounded = cents / 100
  return negative ? -rounded : rounded
}

/**
 * Service fee for a given item subtotal, or null when unknowable.
 * pct-based -> subtotal * pct / 100, clamped to
 * [service_fee_min ?? service_fee_flat, service_fee_max]; else flat; else null.
 */
export function computeServiceFee(schedule, subtotal) {
  if (!schedule) return null
  if (schedule.service_fee_pct != null) {
    let fee = (subtotal * schedule.service_fee_pct) / 100
    let floor = schedule.service_fee_min
    if (floor == null && schedule.service_fee_flat != null) {
      floor = schedule.service_fee_flat
    }
    if (floor != null) fee = Math.max(fee, floor)
    if (schedule.service_fee_max != null) fee = Math.min(fee, schedule.service_fee_max)
    return roundMoney(fee)
  }
  if (schedule.service_fee_flat != null) return roundMoney(schedule.service_fee_flat)
  return null
}

/** Small-order fee when the subtotal is under the threshold (both known), else 0. */
export function computeSmallOrderFee(schedule, subtotal) {
  if (
    schedule &&
    schedule.small_order_fee != null &&
    schedule.small_order_threshold != null &&
    subtotal < schedule.small_order_threshold
  ) {
    return roundMoney(schedule.small_order_fee)
  }
  return 0
}

/**
 * Full cost breakdown for a basket subtotal on one platform.
 *
 * Returns {subtotal, delivery_fee, service_fee, small_order_fee, tax_rate_pct,
 * tax, total, below_minimum, minimum_order, estimated_fields}.
 *
 * - Pickup mode zeroes the delivery/service/small-order fees (they are
 *   delivery-basket fees).
 * - A null service fee counts 0 toward the total; the UI labels it unknown.
 * - Tax uses the platform-exposed rate when present, else
 *   fallbackTaxRatePct (recording 'tax_rate_pct' in estimated_fields); with
 *   neither, tax is 0 and tax_rate_pct is null so callers can say "before tax".
 */
export function estimateMealCost(schedule, subtotal, mode = 'delivery', fallbackTaxRatePct = null) {
  const s = schedule || {}
  const roundedSubtotal = roundMoney(Math.max(Number(subtotal) || 0, 0))

  let deliveryFee
  let serviceFee
  let smallOrderFee
  if (mode === 'delivery') {
    deliveryFee = roundMoney(s.delivery_fee || 0)
    serviceFee = computeServiceFee(s, roundedSubtotal)
    smallOrderFee = computeSmallOrderFee(s, roundedSubtotal)
  } else {
    deliveryFee = 0
    serviceFee = 0
    smallOrderFee = 0
  }

  const estimated = [...(s.estimated_fields || [])]
  let taxRate = s.tax_rate_pct != null ? s.tax_rate_pct : null
  if (taxRate == null && fallbackTaxRatePct != null) {
    taxRate = fallbackTaxRatePct
    estimated.push('tax_rate_pct')
  }
  const tax = taxRate != null ? roundMoney((roundedSubtotal * taxRate) / 100) : 0

  const total = roundMoney(
    roundedSubtotal + deliveryFee + (serviceFee ?? 0) + smallOrderFee + tax,
  )

  const minimumOrder = s.minimum_order != null ? s.minimum_order : null
  const belowMinimum = minimumOrder != null && roundedSubtotal < minimumOrder

  return {
    subtotal: roundedSubtotal,
    delivery_fee: deliveryFee,
    service_fee: serviceFee,
    small_order_fee: smallOrderFee,
    tax_rate_pct: taxRate,
    tax,
    total,
    below_minimum: belowMinimum,
    minimum_order: minimumOrder,
    estimated_fields: estimated,
  }
}

// ---------------------------------------------------------------------------
// Best-effort US prepared-food tax-rate lookup from a free-text location.
//
// HONESTY NOTE: these are ESTIMATED average combined state+local sales-tax
// rates for restaurant/prepared food, at STATE granularity only (city meal
// taxes are folded into the state average, not resolved per city). Last
// reviewed 2026. They exist so the meal builder can show "est. tax" instead
// of silently pretending tax is $0 — always labeled as an estimate in the UI.
// ---------------------------------------------------------------------------

const TAX_RATE_PCT_BY_STATE = {
  AL: 9.25,
  AK: 1.8, // no state sales tax; some localities tax
  AZ: 8.4,
  AR: 9.45,
  CA: 8.75,
  CO: 7.8,
  CT: 7.35, // statewide 7.35% meals rate
  DC: 10.0, // 10% prepared-food rate
  DE: 0,
  FL: 7.0,
  GA: 7.4,
  HI: 4.5,
  ID: 6.0,
  IL: 8.85,
  IN: 7.0,
  IA: 6.95,
  KS: 8.7,
  KY: 6.0,
  LA: 9.55,
  ME: 8.0, // 8% prepared-food rate
  MD: 6.0,
  MA: 7.0, // 6.25% meals + common 0.75% local option
  MI: 6.0,
  MN: 7.5,
  MS: 7.05,
  MO: 8.3,
  MT: 0,
  NE: 6.95,
  NV: 8.25,
  NH: 0, // no general sales tax (NH's separate meals levy not modeled)
  NJ: 6.6,
  NM: 7.7,
  NY: 8.5,
  NC: 7.0,
  ND: 7.0,
  OH: 7.25,
  OK: 9.0,
  OR: 0,
  PA: 6.35,
  PR: 11.5,
  RI: 8.0, // 7% + 1% local meals tax
  SC: 7.5,
  SD: 6.4,
  TN: 9.55,
  TX: 8.2,
  UT: 7.2,
  VT: 9.0, // 9% meals rate
  VA: 5.75,
  WA: 9.2,
  WV: 6.55,
  WI: 5.45,
  WY: 5.4,
}

const STATE_NAME_TO_CODE = {
  alabama: 'AL',
  alaska: 'AK',
  arizona: 'AZ',
  arkansas: 'AR',
  california: 'CA',
  colorado: 'CO',
  connecticut: 'CT',
  delaware: 'DE',
  'district of columbia': 'DC',
  'washington dc': 'DC',
  'washington d c': 'DC',
  florida: 'FL',
  georgia: 'GA',
  hawaii: 'HI',
  idaho: 'ID',
  illinois: 'IL',
  indiana: 'IN',
  iowa: 'IA',
  kansas: 'KS',
  kentucky: 'KY',
  louisiana: 'LA',
  maine: 'ME',
  maryland: 'MD',
  massachusetts: 'MA',
  michigan: 'MI',
  minnesota: 'MN',
  mississippi: 'MS',
  missouri: 'MO',
  montana: 'MT',
  nebraska: 'NE',
  nevada: 'NV',
  'new hampshire': 'NH',
  'new jersey': 'NJ',
  'new mexico': 'NM',
  'new york': 'NY',
  'north carolina': 'NC',
  'north dakota': 'ND',
  ohio: 'OH',
  oklahoma: 'OK',
  oregon: 'OR',
  pennsylvania: 'PA',
  'puerto rico': 'PR',
  'rhode island': 'RI',
  'south carolina': 'SC',
  'south dakota': 'SD',
  tennessee: 'TN',
  texas: 'TX',
  utah: 'UT',
  vermont: 'VT',
  virginia: 'VA',
  washington: 'WA',
  'west virginia': 'WV',
  wisconsin: 'WI',
  wyoming: 'WY',
}

// Longest names first so "west virginia" beats "virginia" and
// "washington dc" beats "washington".
const STATE_NAMES_BY_LENGTH = Object.keys(STATE_NAME_TO_CODE).sort(
  (a, b) => b.length - a.length,
)

const STATE_CODES = new Set([
  ...Object.values(STATE_NAME_TO_CODE),
  'VI',
  'GU',
])

// Standard USPS ZIP3 prefix ranges -> state: [loPrefix, hiPrefix, state].
// First matching range wins; single-prefix exceptions (005 NY, 201 VA,
// 733/885 TX) are their own rows. Military (090-098, 340, 962-966) and a few
// unused prefixes are intentionally absent -> null.
const ZIP3_TO_STATE = [
  [5, 5, 'NY'],
  [6, 7, 'PR'],
  [8, 8, 'VI'],
  [9, 9, 'PR'],
  [10, 27, 'MA'],
  [28, 29, 'RI'],
  [30, 38, 'NH'],
  [39, 49, 'ME'],
  [50, 59, 'VT'],
  [60, 69, 'CT'],
  [70, 89, 'NJ'],
  [100, 149, 'NY'],
  [150, 196, 'PA'],
  [197, 199, 'DE'],
  [200, 200, 'DC'],
  [201, 201, 'VA'],
  [202, 205, 'DC'],
  [206, 219, 'MD'],
  [220, 246, 'VA'],
  [247, 268, 'WV'],
  [270, 289, 'NC'],
  [290, 299, 'SC'],
  [300, 319, 'GA'],
  [320, 349, 'FL'],
  [350, 369, 'AL'],
  [370, 385, 'TN'],
  [386, 397, 'MS'],
  [398, 399, 'GA'],
  [400, 427, 'KY'],
  [430, 459, 'OH'],
  [460, 479, 'IN'],
  [480, 499, 'MI'],
  [500, 528, 'IA'],
  [530, 549, 'WI'],
  [550, 567, 'MN'],
  [570, 577, 'SD'],
  [580, 588, 'ND'],
  [590, 599, 'MT'],
  [600, 629, 'IL'],
  [630, 658, 'MO'],
  [660, 679, 'KS'],
  [680, 693, 'NE'],
  [700, 714, 'LA'],
  [716, 729, 'AR'],
  [730, 732, 'OK'],
  [733, 733, 'TX'],
  [734, 749, 'OK'],
  [750, 799, 'TX'],
  [800, 816, 'CO'],
  [820, 831, 'WY'],
  [832, 838, 'ID'],
  [840, 847, 'UT'],
  [850, 865, 'AZ'],
  [870, 884, 'NM'],
  [885, 885, 'TX'],
  [889, 898, 'NV'],
  [900, 961, 'CA'],
  [967, 968, 'HI'],
  [969, 969, 'GU'],
  [970, 979, 'OR'],
  [980, 994, 'WA'],
  [995, 999, 'AK'],
]

function stateFromZip(zip5) {
  const prefix = parseInt(zip5.slice(0, 3), 10)
  for (const [lo, hi, state] of ZIP3_TO_STATE) {
    if (prefix >= lo && prefix <= hi) return state
  }
  return null
}

/**
 * Best-effort {statecode, ratePct} for a free-text US location, or null when
 * unparseable (or when we parsed a territory we have no rate for).
 *
 * Parses, in order of confidence: a full state name ("Austin Texas"), a
 * 5-digit ZIP via the USPS ZIP3 prefix table, then a 2-letter state
 * abbreviation — accepted only in credible positions (final token, after a
 * comma, or uppercase in the raw input) so city particles like "la jolla"
 * or "de pere" don't resolve to a state.
 */
export function taxRateForLocation(locationString) {
  if (!locationString || typeof locationString !== 'string') return null

  const normalized = locationString
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
  if (!normalized) return null

  let statecode = null

  // 1) Full state name.
  for (const name of STATE_NAMES_BY_LENGTH) {
    if (new RegExp(`\\b${name}\\b`).test(normalized)) {
      statecode = STATE_NAME_TO_CODE[name]
      break
    }
  }

  // 2) Five-digit ZIP — unambiguous, so it outranks 2-letter tokens
  //    ("in-n-out 94103" must not parse as Indiana). Last one wins since
  //    addresses end with the ZIP.
  if (!statecode) {
    const zips = [...locationString.matchAll(/\b(\d{5})(?:-\d{4})?\b/g)]
    if (zips.length > 0) {
      statecode = stateFromZip(zips[zips.length - 1][1])
    }
  }

  // 3) Two-letter abbreviation — inherently ambiguous ("la jolla", "de
  //    pere" contain state codes), so only positionally credible tokens
  //    count: the final token of the string, a token right after a comma,
  //    or an UPPERCASE token in the raw input.
  if (!statecode) {
    const tokens = normalized.split(' ')
    const candidates = []
    const lastToken = tokens[tokens.length - 1]
    if (lastToken && lastToken.length === 2) candidates.push(lastToken.toUpperCase())
    for (const m of locationString.matchAll(/,\s*([A-Za-z]{2})(?=$|[\s,.])/g)) {
      candidates.push(m[1].toUpperCase())
    }
    for (const m of locationString.matchAll(/(?:^|[\s,])([A-Z]{2})(?=$|[\s,.])/g)) {
      candidates.push(m[1])
    }
    for (const c of candidates) {
      if (STATE_CODES.has(c)) {
        statecode = c
        break
      }
    }
  }

  if (!statecode) return null
  const ratePct = TAX_RATE_PCT_BY_STATE[statecode]
  if (ratePct == null) return null // parsed a territory we have no rate for
  return { statecode, ratePct }
}
