import { createRef } from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MealBuilder from './MealBuilder.jsx'

// Hand-built schedules so the totals below are pinned exactly.
// uber_eats: exact 10% service fee (no est. markers), $2.49 delivery.
// doordash: estimated 15% (floor $3) + $2.50 small-order under $10, $15 min.
const uberSchedule = {
  delivery_fee: 2.49,
  service_fee_pct: 10,
  service_fee_flat: null,
  service_fee_min: null,
  service_fee_max: null,
  small_order_fee: null,
  small_order_threshold: null,
  minimum_order: null,
  tax_rate_pct: null,
  estimated_fields: [],
  notes: [],
}

const doordashSchedule = {
  delivery_fee: 1.99,
  service_fee_pct: 15,
  service_fee_flat: null,
  service_fee_min: 3,
  service_fee_max: null,
  small_order_fee: 2.5,
  small_order_threshold: 10,
  minimum_order: 15,
  tax_rate_pct: null,
  estimated_fields: [
    'service_fee_pct',
    'service_fee_min',
    'small_order_fee',
    'small_order_threshold',
  ],
  notes: [],
}

const platforms = [
  {
    platform: 'uber_eats',
    fee_schedule: uberSchedule,
    menu_items: [
      { name: 'Carne Asada Burrito', price: 10, section: 'Burritos' },
      { name: 'Chips', price: 4, section: 'Sides' },
    ],
  },
  {
    platform: 'doordash',
    fee_schedule: doordashSchedule,
    // Case/whitespace variant: name matching must be case-insensitive+trimmed.
    menu_items: [{ name: '  carne asada BURRITO ', price: 12, section: 'Burritos' }],
  },
]

const menuComparison = [
  {
    item_name: 'Carne Asada Burrito',
    prices: { uber_eats: 10, doordash: 12 },
    cheapest_platform: 'uber_eats',
    price_difference: 2,
  },
]

// Berkeley, CA -> 8.75% estimated tax in the mealCost table.
function setup(props = {}) {
  const ref = createRef()
  render(
    <MealBuilder
      ref={ref}
      platforms={platforms}
      menuComparison={menuComparison}
      location="Berkeley, CA"
      mode="delivery"
      {...props}
    />,
  )
  return { ref, user: userEvent.setup() }
}

const addBurritoChip = () =>
  screen.getByRole('button', { name: /add carne asada burrito to meal/i })

describe('rendering', () => {
  it('shows the empty state, quick-add chips, and the standing disclaimer', () => {
    setup()
    expect(screen.getByText(/your meal is empty/i)).toBeInTheDocument()
    expect(addBurritoChip()).toBeInTheDocument()
    expect(screen.getByText(/not a cart or checkout/i)).toBeInTheDocument()
  })
})

describe('adding items', () => {
  it('adds from a comparison row (quick-add) with prices straight from row.prices', async () => {
    const { user } = setup()
    await user.click(addBurritoChip())

    expect(screen.queryByText(/your meal is empty/i)).not.toBeInTheDocument()
    // Entry row rendered with its price provenance line.
    expect(screen.getByText(/from \$10\.00 · priced on 2 of 2 platforms/i)).toBeInTheDocument()
    // Priced on both platforms -> no "x of y priced" note anywhere.
    expect(screen.queryByText(/items priced here/i)).not.toBeInTheDocument()

    // Pinned totals: uber 10 + 2.49 + 1.00 + 0.88 tax = 14.37
    //                doordash 12 + 1.99 + 3.00 + 1.05 tax = 18.04
    expect(screen.getByText('$14.37')).toBeInTheDocument()
    expect(screen.getByText('$18.04')).toBeInTheDocument()
  })

  it('adds from a platform menu, matching other platforms by trimmed case-insensitive name', async () => {
    const { ref } = setup()
    act(() => {
      ref.current.addFromMenuItem('uber_eats', { name: 'Carne Asada Burrito', price: 10 })
    })
    // doordash's "  carne asada BURRITO " matched at $12 -> same pinned totals.
    expect(screen.getByText('$14.37')).toBeInTheDocument()
    expect(screen.getByText('$18.04')).toBeInTheDocument()
    expect(screen.queryByText(/items priced here/i)).not.toBeInTheDocument()
  })

  it('re-adding the same item bumps quantity instead of duplicating the row', async () => {
    const { user } = setup()
    await user.click(addBurritoChip())
    await user.click(addBurritoChip())

    // One entry row (one provenance line), not two.
    expect(screen.getAllByText(/priced on 2 of 2 platforms/i)).toHaveLength(1)
    expect(screen.getByText('2')).toBeInTheDocument()
    // uber qty 2: 20 + 2.49 + 2.00 + 1.75 tax = 26.24
    expect(screen.getByText('$26.24')).toBeInTheDocument()
  })
})

describe('quantity and removal', () => {
  it('steppers change per-platform totals; minus clamps at 1', async () => {
    const { user } = setup()
    await user.click(addBurritoChip())
    await user.click(screen.getByRole('button', { name: /increase carne asada burrito/i }))
    expect(screen.getByText('$26.24')).toBeInTheDocument()

    const minus = screen.getByRole('button', { name: /decrease carne asada burrito/i })
    await user.click(minus)
    expect(screen.getByText('$14.37')).toBeInTheDocument()
    expect(minus).toBeDisabled()
  })

  it('remove and Clear meal return to the empty state', async () => {
    const { user } = setup()
    await user.click(addBurritoChip())
    await user.click(screen.getByRole('button', { name: /remove carne asada burrito/i }))
    expect(screen.getByText(/your meal is empty/i)).toBeInTheDocument()

    await user.click(addBurritoChip())
    await user.click(screen.getByRole('button', { name: /clear meal/i }))
    expect(screen.getByText(/your meal is empty/i)).toBeInTheDocument()
  })
})

describe('per-platform panels', () => {
  it('crowns the cheapest complete platform and shows the gap on the other', async () => {
    const { user } = setup()
    await user.click(addBurritoChip())

    expect(screen.getByText('Best Total')).toBeInTheDocument()
    expect(screen.getByText('+$3.67 vs best')).toBeInTheDocument() // 18.04 - 14.37
  })

  it('warns when the subtotal is below the platform minimum', async () => {
    const { user } = setup()
    await user.click(addBurritoChip())
    // doordash subtotal $12 < $15 minimum; uber has no minimum.
    expect(screen.getByText(/below \$15\.00 minimum/i)).toBeInTheDocument()
  })

  it('marks unmatched items as unpriced and keeps the platform uncrowned', async () => {
    const { ref } = setup()
    act(() => {
      ref.current.addFromMenuItem('uber_eats', { name: 'Chips', price: 4 })
    })
    // Chips exists only on uber_eats -> doordash panel is incomplete.
    expect(screen.getByText('0 of 1 items priced here')).toBeInTheDocument()
    // Only the complete platform competes for Best Total.
    expect(screen.getByText('Best Total')).toBeInTheDocument()
    expect(screen.queryByText(/vs best/i)).not.toBeInTheDocument()
  })

  it('labels estimated service fees with ~ and est., exact ones plainly', async () => {
    const { user } = setup()
    await user.click(addBurritoChip())

    // doordash 15% is backfilled -> "~$3.00" + est. chip; uber 10% is exact -> "$1.00".
    expect(screen.getByText('~$3.00')).toBeInTheDocument()
    expect(screen.getByText('$1.00')).toBeInTheDocument()
    // est. chips: doordash service fee + both panels' location-derived tax.
    expect(screen.getAllByText('est.')).toHaveLength(3)
    expect(screen.getAllByText('Tax (8.75% CA)')).toHaveLength(2)
  })

  it('shows "unknown" when a platform exposes no service fee structure', () => {
    const ref = createRef()
    render(
      <MealBuilder
        ref={ref}
        platforms={[
          {
            platform: 'eatstreet',
            fee_schedule: { delivery_fee: 3.49, estimated_fields: [], notes: [] },
            menu_items: [{ name: 'Wrap', price: 8 }],
          },
        ]}
        menuComparison={[]}
        location=""
        mode="delivery"
      />,
    )
    act(() => {
      ref.current.addFromMenuItem('eatstreet', { name: 'Wrap', price: 8 })
    })
    expect(screen.getByText('unknown')).toBeInTheDocument()
    // No tax rate at all -> total is labeled before tax: 8 + 3.49.
    expect(screen.getByText('(before tax)')).toBeInTheDocument()
    expect(screen.getByText('$11.49')).toBeInTheDocument()
  })
})

describe('pickup mode', () => {
  it('drops delivery-basket fees and taxes the bare subtotal', async () => {
    const { user } = setup({ mode: 'pickup' })
    await user.click(addBurritoChip())

    expect(screen.getAllByText(/fees waived/i)).toHaveLength(2)
    expect(screen.queryByText(/delivery fee/i)).not.toBeInTheDocument()
    // uber pickup: 10 + 0.88 tax = 10.88; doordash: 12 + 1.05 = 13.05.
    expect(screen.getByText('$10.88')).toBeInTheDocument()
    expect(screen.getByText('$13.05')).toBeInTheDocument()
  })

  it('suppresses the delivery-minimum warning (minimums are delivery-only)', async () => {
    const { user } = setup({ mode: 'pickup' })
    await user.click(addBurritoChip()) // doordash subtotal 12 < its 15 minimum
    expect(screen.queryByText(/below .* minimum/i)).not.toBeInTheDocument()
  })
})

describe('zero-price "price varies" placeholders', () => {
  // Real scenario: DoorDash ships customization-priced items (fountain
  // drinks, build-your-own) at $0 while the same item has a real price on
  // another platform. The $0 must count as UNPRICED on the origin platform,
  // not as free food that wins Best Total.
  const platformsWithZeroDD = [
    platforms[0], // uber_eats: Carne Asada Burrito $10
    {
      platform: 'doordash',
      fee_schedule: doordashSchedule,
      menu_items: [{ name: 'Carne Asada Burrito', price: 0, section: 'Burritos' }],
    },
  ]

  it('treats a $0 origin price as unpriced when the item is priced elsewhere', () => {
    const { ref } = setup({ platforms: platformsWithZeroDD })
    act(() => {
      ref.current.addFromMenuItem('doordash', { name: 'Carne Asada Burrito', price: 0 })
    })
    // uber matched at $10 (priced); doordash's own $0 became null, so its
    // panel is incomplete and cannot claim Best Total on fabricated $0 food.
    expect(screen.getByText(/0 of 1 items priced here/i)).toBeInTheDocument()
    expect(screen.getByText('$14.37')).toBeInTheDocument() // uber total
    const bestPanels = screen.getAllByText(/best total/i)
    expect(bestPanels.length).toBe(1)
  })

  it('keeps a genuine freebie ($0 everywhere) as a $0 line', () => {
    const { ref } = setup()
    act(() => {
      ref.current.addFromMenuItem('uber_eats', { name: 'Mild Sauce Packet', price: 0 })
    })
    // No platform prices it positively -> stays $0 on uber (complete there),
    // unmatched on doordash -> "0 of 1 items priced here" for doordash.
    expect(screen.getByText(/0 of 1 items priced here/i)).toBeInTheDocument()
    // uber: 0 subtotal + 2.49 delivery + 0 service + 0 tax = 2.49 total;
    // the delivery-fee row shows the same figure, so expect two matches.
    expect(screen.getAllByText('$2.49').length).toBeGreaterThanOrEqual(2)
  })

  it('lets a later positive price replace a stored $0 on re-add', async () => {
    const { ref, user } = setup()
    act(() => {
      // First add claims doordash $0 for the burrito (placeholder).
      ref.current.addFromComparisonRow({
        item_name: 'Carne Asada Burrito',
        prices: { uber_eats: 10, doordash: 0 },
      })
    })
    // Re-add from the comparison chip carrying doordash's real $12.
    await user.click(addBurritoChip())
    // qty 2 now, and doordash must use $12, not the stale $0:
    // doordash: 24 + 1.99 + 3.60 + 2.10 tax = 31.69
    expect(screen.getByText('$31.69')).toBeInTheDocument()
  })
})
