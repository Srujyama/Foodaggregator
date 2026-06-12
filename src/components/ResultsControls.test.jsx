import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ResultsControls from './ResultsControls.jsx'
import { SORT_OPTIONS, EMPTY_FILTERS } from '../utils/sorting.js'

const COUNTS = { uber_eats: 3, doordash: 2, grubhub: 0 }

function renderControls(overrides = {}) {
  const props = {
    sortKey: 'best',
    onSortChange: vi.fn(),
    filters: EMPTY_FILTERS,
    onFiltersChange: vi.fn(),
    platformCounts: COUNTS,
    ...overrides,
  }
  render(<ResultsControls {...props} />)
  return props
}

describe('sort pills', () => {
  it('renders all 6 options with the active one aria-pressed', () => {
    // Sort pills are plain toggle buttons (aria-pressed), not ARIA radios —
    // radios would require the roving-tabindex arrow-key pattern.
    renderControls({ sortKey: 'rating' })
    for (const { label } of SORT_OPTIONS) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'Top rated' }))
      .toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Best match' }))
      .toHaveAttribute('aria-pressed', 'false')
  })

  it('clicking a pill calls onSortChange with its key', async () => {
    const user = userEvent.setup()
    const { onSortChange } = renderControls({ sortKey: 'best' })
    await user.click(screen.getByRole('button', { name: 'Fastest' }))
    expect(onSortChange).toHaveBeenCalledWith('eta')
  })
})

describe('platform chips', () => {
  it('shows a zero-count chip when that platform is active in the URL filter', () => {
    // A shared link like ?fplat=grubhub must keep the grubhub chip visible
    // (count 0) so the filter can be seen and toggled off chip-by-chip.
    renderControls({ filters: { ...EMPTY_FILTERS, platforms: ['grubhub'] } })
    const chip = screen.getByRole('button', { name: /grubhub/i })
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    expect(within(chip).getByText('0')).toBeInTheDocument()
  })

  it('renders only platforms with count > 0, showing counts', () => {
    renderControls()
    const uber = screen.getByRole('button', { name: /uber eats/i })
    const dd = screen.getByRole('button', { name: /doordash/i })
    expect(within(uber).getByText('3')).toBeInTheDocument()
    expect(within(dd).getByText('2')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /grubhub/i })).toBeNull()
  })

  it('clicking an inactive chip adds the platform to filters', async () => {
    const user = userEvent.setup()
    const { onFiltersChange } = renderControls()
    await user.click(screen.getByRole('button', { name: /doordash/i }))
    expect(onFiltersChange).toHaveBeenCalledWith({
      ...EMPTY_FILTERS, platforms: ['doordash'],
    })
  })

  it('clicking an active chip removes the platform', async () => {
    const user = userEvent.setup()
    const filters = { ...EMPTY_FILTERS, platforms: ['doordash'] }
    const { onFiltersChange } = renderControls({ filters })
    const dd = screen.getByRole('button', { name: /doordash/i })
    expect(dd).toHaveAttribute('aria-pressed', 'true')
    await user.click(dd)
    expect(onFiltersChange).toHaveBeenCalledWith({
      ...EMPTY_FILTERS, platforms: [],
    })
  })
})

describe('boolean filter chips', () => {
  it.each([
    [/open now/i, 'openNow'],
    [/has promo/i, 'promoOnly'],
    [/on 2\+ apps/i, 'multiOnly'],
  ])('%s toggles %s on', async (name, key) => {
    const user = userEvent.setup()
    const { onFiltersChange } = renderControls()
    await user.click(screen.getByRole('button', { name }))
    expect(onFiltersChange).toHaveBeenCalledWith({ ...EMPTY_FILTERS, [key]: true })
  })

  it('toggles an active flag back off', async () => {
    const user = userEvent.setup()
    const filters = { ...EMPTY_FILTERS, openNow: true }
    const { onFiltersChange } = renderControls({ filters })
    const chip = screen.getByRole('button', { name: /open now/i })
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    await user.click(chip)
    expect(onFiltersChange).toHaveBeenCalledWith({ ...EMPTY_FILTERS, openNow: false })
  })
})

describe('Clear button', () => {
  it('is absent when no filters are active', () => {
    renderControls({ filters: EMPTY_FILTERS })
    expect(screen.queryByRole('button', { name: /clear/i })).toBeNull()
  })

  it('appears when any filter is active and resets everything', async () => {
    const user = userEvent.setup()
    const filters = {
      platforms: ['uber_eats'], openNow: true, promoOnly: true, multiOnly: false,
    }
    const { onFiltersChange } = renderControls({ filters })
    await user.click(screen.getByRole('button', { name: /clear/i }))
    expect(onFiltersChange).toHaveBeenCalledWith({
      platforms: [], openNow: false, promoOnly: false, multiOnly: false,
    })
  })
})
