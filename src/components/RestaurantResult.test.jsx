import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import RestaurantResult from './RestaurantResult.jsx'
import { SearchProvider } from '../context/SearchContext.jsx'

// InlineMenu fetches when no platform ships menu_items; a never-resolving
// promise pins it in the loading state so toggling is observable.
vi.mock('../lib/api.js', () => ({
  getRestaurant: vi.fn(() => new Promise(() => {})),
}))

const _platform = (overrides = {}) => ({
  platform: 'uber_eats',
  delivery_fee: 0,
  service_fee: 0,
  pickup_fee: 0,
  pickup_service_fee: 0,
  estimated_delivery_minutes: 30,
  estimated_pickup_minutes: 15,
  ...overrides,
})

const _result = (overrides = {}) => ({
  restaurant_name: 'Taco Haven',
  platforms: [
    _platform({ platform: 'uber_eats', delivery_fee: 2.99, service_fee: 1.5 }),
    _platform({ platform: 'doordash', delivery_fee: 5, service_fee: 1 }),
  ],
  ...overrides,
})

function renderResult(result = _result()) {
  return render(
    <MemoryRouter>
      <SearchProvider>
        <RestaurantResult result={result} />
      </SearchProvider>
    </MemoryRouter>,
  )
}

describe('header', () => {
  it('renders name, platform count, and best-deal fee', () => {
    renderResult()
    expect(screen.getByText('Taco Haven')).toBeInTheDocument()
    expect(screen.getByText('2 platforms')).toBeInTheDocument()
    // uber_eats is cheapest: 2.99 + 1.50 = $4.49
    expect(screen.getAllByText('$4.49').length).toBeGreaterThan(0)
    expect(screen.getByText('Delivery fees')).toBeInTheDocument()
  })

  it('uses singular label for a single platform', () => {
    renderResult(_result({ platforms: [_platform({ delivery_fee: 3 })] }))
    expect(screen.getByText('1 platform')).toBeInTheDocument()
  })
})

describe('savings badge', () => {
  it('shows the fee spread when above a cent', () => {
    renderResult() // spread = 6.00 - 4.49 = $1.51
    expect(screen.getByText(/save \$1\.51 in fees/i)).toBeInTheDocument()
  })

  it('is hidden when all platforms cost the same', () => {
    renderResult(_result({
      platforms: [
        _platform({ platform: 'uber_eats', delivery_fee: 3 }),
        _platform({ platform: 'doordash', delivery_fee: 3 }),
      ],
    }))
    expect(screen.queryByText(/in fees/i)).toBeNull()
  })
})

describe('availability badges', () => {
  it('shows "Closed on all platforms" when every platform is closed', () => {
    renderResult(_result({
      platforms: [
        _platform({ platform: 'uber_eats', is_open: false }),
        _platform({ platform: 'doordash', is_open: false }),
      ],
    }))
    expect(screen.getByText(/closed on all platforms/i)).toBeInTheDocument()
  })

  it('shows "Limited availability" instead when only some are closed', () => {
    renderResult(_result({
      platforms: [
        _platform({ platform: 'uber_eats', is_open: false }),
        _platform({ platform: 'doordash', is_open: true }),
      ],
    }))
    expect(screen.queryByText(/closed on all platforms/i)).toBeNull()
    expect(screen.getByText(/limited availability/i)).toBeInTheDocument()
  })
})

describe('View Menu toggle', () => {
  it('expands and collapses the inline menu section', async () => {
    const user = userEvent.setup()
    renderResult()
    expect(screen.queryByText(/loading menu/i)).toBeNull()

    await user.click(screen.getByRole('button', { name: /view menu/i }))
    expect(screen.getByText(/loading menu/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /hide menu/i }))
    expect(screen.queryByText(/loading menu/i)).toBeNull()
    expect(screen.getByRole('button', { name: /view menu/i })).toBeInTheDocument()
  })
})
