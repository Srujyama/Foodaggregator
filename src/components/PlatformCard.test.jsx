import { describe, it, expect } from 'vitest'
import { derivePlatformStatus } from './PlatformCard.jsx'

describe('derivePlatformStatus', () => {
  it('returns null when there is no signal', () => {
    expect(derivePlatformStatus({})).toBeNull()
  })

  it('flags out-of-range first', () => {
    const s = derivePlatformStatus({
      is_within_delivery_range: false,
      is_open: true,
      accepting_orders: true,
    })
    expect(s.tone).toBe('unavailable')
    expect(s.label).toMatch(/range/i)
  })

  it('flags closed when accepting_orders=false', () => {
    const s = derivePlatformStatus({ accepting_orders: false })
    expect(s.tone).toBe('unavailable')
  })

  it('uses status_text when present and accepting=false', () => {
    const s = derivePlatformStatus({
      accepting_orders: false,
      status_text: 'No couriers nearby',
    })
    expect(s.label).toBe('No couriers nearby')
  })

  it('shows status_text as warning when otherwise open', () => {
    const s = derivePlatformStatus({
      is_open: true,
      accepting_orders: true,
      status_text: 'Limited availability',
    })
    expect(s.tone).toBe('warning')
  })

  it('shows closing soon as warning', () => {
    const s = derivePlatformStatus({ closing_soon: true })
    expect(s.tone).toBe('warning')
  })

  it('returns Open now when fully available', () => {
    const s = derivePlatformStatus({ is_open: true, accepting_orders: true })
    expect(s.tone).toBe('available')
    expect(s.label).toMatch(/open/i)
  })
})
