import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MenuComparison from './MenuComparison.jsx'

const platforms = [{ platform: 'uber_eats' }, { platform: 'doordash' }]

const menuComparison = [
  {
    item_name: 'Cheeseburger',
    prices: { uber_eats: 10.99, doordash: 12.49 },
    cheapest_platform: 'uber_eats',
    price_difference: 1.5,
  },
  {
    item_name: 'Chicken Burrito',
    prices: { uber_eats: 9.99, doordash: 9.99 },
    cheapest_platform: 'uber_eats',
    price_difference: 0,
  },
  {
    item_name: 'French Fries',
    prices: { uber_eats: 3.99, doordash: 4.49 },
    cheapest_platform: 'uber_eats',
    price_difference: 0.5,
  },
  {
    item_name: 'Garden Salad',
    prices: { uber_eats: 7.99, doordash: 7.99 },
    cheapest_platform: 'uber_eats',
    price_difference: 0,
  },
]

const ALL_NAMES = menuComparison.map((i) => i.item_name)

function setup() {
  render(
    <MenuComparison
      menuComparison={menuComparison}
      platforms={platforms}
      avgMarkup={null}
    />,
  )
  return userEvent.setup()
}

describe('MenuComparison filtering', () => {
  it('narrows visible item names when typing in the filter', async () => {
    const user = setup()
    for (const name of ALL_NAMES) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }

    await user.type(screen.getByPlaceholderText(/filter items/i), 'burger')

    expect(screen.getByText('Cheeseburger')).toBeInTheDocument()
    expect(screen.queryByText('Chicken Burrito')).not.toBeInTheDocument()
    expect(screen.queryByText('French Fries')).not.toBeInTheDocument()
    expect(screen.queryByText('Garden Salad')).not.toBeInTheDocument()
  })

  it('hides zero-diff rows when "Differences only" is toggled', async () => {
    const user = setup()
    const toggle = screen.getByRole('button', { name: /differences only/i })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('Cheeseburger')).toBeInTheDocument()
    expect(screen.getByText('French Fries')).toBeInTheDocument()
    expect(screen.queryByText('Chicken Burrito')).not.toBeInTheDocument()
    expect(screen.queryByText('Garden Salad')).not.toBeInTheDocument()
  })

  it('renders the zero-match state and clears both controls via the button', async () => {
    const user = setup()
    const input = screen.getByPlaceholderText(/filter items/i)
    await user.click(screen.getByRole('button', { name: /differences only/i }))
    await user.type(input, 'zzz no such item')

    expect(screen.getByText(/no items match/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /clear the filter/i }))

    expect(screen.queryByText(/no items match/i)).not.toBeInTheDocument()
    expect(input).toHaveValue('')
    expect(
      screen.getByRole('button', { name: /differences only/i }),
    ).toHaveAttribute('aria-pressed', 'false')
    for (const name of ALL_NAMES) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
  })

  it('renders no Add buttons when onAdd is absent (backward compatible)', () => {
    setup()
    expect(screen.queryByRole('button', { name: /add .* to meal/i })).toBeNull()
  })

  it('calls onAdd with the full row when a row Add button is clicked', async () => {
    const onAdd = vi.fn()
    render(
      <MenuComparison
        menuComparison={menuComparison}
        platforms={platforms}
        avgMarkup={null}
        onAdd={onAdd}
      />,
    )
    const user = userEvent.setup()
    await user.click(
      screen.getByRole('button', { name: /add cheeseburger to meal/i }),
    )
    expect(onAdd).toHaveBeenCalledTimes(1)
    expect(onAdd).toHaveBeenCalledWith(menuComparison[0])
  })

  it('updates the footer count to reflect the filtered rows', async () => {
    const user = setup()
    expect(screen.getByText(/showing 4 of 4 comparable items/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /differences only/i }))
    expect(screen.getByText(/showing 2 of 2 comparable items/i)).toBeInTheDocument()

    await user.type(screen.getByPlaceholderText(/filter items/i), 'fries')
    expect(screen.getByText(/showing 1 of 1 comparable item/i)).toBeInTheDocument()
  })
})
