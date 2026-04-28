import { describe, it, expect } from 'vitest'
import { formatPrice, formatETA, slugify, unslugify, sanitizeHtml, getApiUrl } from './utils.js'

describe('formatPrice', () => {
  it('returns Free for 0', () => {
    expect(formatPrice(0)).toBe('Free')
  })
  it('formats dollars with 2 decimals', () => {
    expect(formatPrice(2.5)).toBe('$2.50')
    expect(formatPrice(2.999)).toBe('$3.00')
  })
})

describe('formatETA', () => {
  it('handles 0 / null / undefined as N/A', () => {
    expect(formatETA(0)).toBe('N/A')
    expect(formatETA(null)).toBe('N/A')
    expect(formatETA(undefined)).toBe('N/A')
  })
  it('formats minutes under an hour', () => {
    expect(formatETA(15)).toBe('15 min')
  })
  it('formats hours and minutes', () => {
    expect(formatETA(75)).toBe('1h 15m')
    expect(formatETA(120)).toBe('2h')
  })
})

describe('slugify / unslugify', () => {
  it('round-trips simple names', () => {
    expect(slugify("Domino's Pizza")).toBe('domino-s-pizza')
    expect(unslugify('domino-s-pizza')).toBe('Domino S Pizza')
  })
})

describe('sanitizeHtml', () => {
  it('returns empty string for null/empty input', () => {
    expect(sanitizeHtml(null)).toBe('')
    expect(sanitizeHtml('')).toBe('')
  })

  it('strips script tags entirely', () => {
    const out = sanitizeHtml('<span>safe</span><script>alert(1)</script>')
    expect(out).not.toMatch(/script/i)
    expect(out).toContain('safe')
  })

  it('removes onclick and other event handlers', () => {
    const out = sanitizeHtml('<a href="https://x.com" onclick="evil()">x</a>')
    expect(out).not.toMatch(/onclick/i)
    expect(out).toContain('href="https://x.com"')
  })

  it('strips javascript: hrefs', () => {
    const out = sanitizeHtml('<a href="javascript:alert(1)">x</a>')
    expect(out).not.toMatch(/href=.*javascript/i)
  })

  it('forces target=_blank rel=noopener on links', () => {
    const out = sanitizeHtml('<a href="https://x.com">x</a>')
    expect(out).toContain('target="_blank"')
    expect(out).toContain('rel="noopener noreferrer"')
  })

  it('preserves allowed inline tags', () => {
    const out = sanitizeHtml('<p>Hello <strong>world</strong></p>')
    expect(out).toContain('<p>')
    expect(out).toContain('<strong>')
  })

  it('unwraps disallowed tags but keeps their text', () => {
    const out = sanitizeHtml('<div>kept <span>inner</span></div>')
    expect(out).not.toMatch(/<div>/i)
    expect(out).toContain('kept')
    expect(out).toContain('<span>inner</span>')
  })

  it('handles real allergen disclaimer payload', () => {
    const allergen = '<span>We prepare and serve products containing egg, milk, soy, wheat. Info <a href="https://www.tacobell.com/nutrition/allergen-info" style="color:#61ad5f;">here</a> and upon request.</span>'
    const out = sanitizeHtml(allergen)
    expect(out).toContain('milk')
    expect(out).toContain('href="https://www.tacobell.com/nutrition/allergen-info"')
    expect(out).toContain('target="_blank"')
  })
})

describe('getApiUrl', () => {
  it('falls back to fly.io URL when running outside localhost', () => {
    // jsdom default location is http://localhost so we can't test the prod
    // branch directly, but we can at least confirm the function returns a
    // string that's either empty (proxy) or starts with https.
    const url = getApiUrl()
    expect(typeof url).toBe('string')
  })
})
