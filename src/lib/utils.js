import { clsx } from 'clsx'

export function cn(...inputs) {
  return clsx(inputs)
}

export function getApiUrl() {
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL
  // In production (Vercel), use the Fly.io backend
  if (typeof window !== 'undefined' && window.location.hostname !== 'localhost') {
    return 'https://foodaggregator-api.fly.dev'
  }
  // Local dev uses the Vite proxy
  return ''
}

export function formatPrice(dollars) {
  if (dollars === 0) return 'Free'
  return `$${Number(dollars).toFixed(2)}`
}

export function formatETA(minutes) {
  if (!minutes) return 'N/A'
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

export function slugify(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
}

export function unslugify(slug) {
  return slug.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// Minimal HTML sanitizer for backend-supplied allergen disclaimers.
// Allows only a small set of inline tags; strips script/style and any
// on*= event-handler attributes; rewrites links to open in a new tab.
const ALLOWED_TAGS = new Set(['span', 'b', 'i', 'em', 'strong', 'br', 'p', 'a', 'ul', 'ol', 'li'])

export function sanitizeHtml(input) {
  if (!input || typeof input !== 'string') return ''
  if (typeof window === 'undefined' || !window.DOMParser) {
    // SSR fallback: strip tags entirely.
    return input.replace(/<[^>]+>/g, '')
  }
  const doc = new DOMParser().parseFromString(`<div>${input}</div>`, 'text/html')
  const root = doc.body.firstElementChild
  if (!root) return ''
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_ELEMENT)
  const toUnwrap = []
  let n = walker.nextNode()
  while (n) {
    if (!ALLOWED_TAGS.has(n.tagName.toLowerCase())) {
      toUnwrap.push(n)
    } else {
      // Strip event handlers + javascript: hrefs.
      for (const attr of [...n.attributes]) {
        const name = attr.name.toLowerCase()
        if (name.startsWith('on') || (name === 'href' && /^\s*javascript:/i.test(attr.value))) {
          n.removeAttribute(attr.name)
        }
      }
      if (n.tagName.toLowerCase() === 'a') {
        n.setAttribute('target', '_blank')
        n.setAttribute('rel', 'noopener noreferrer')
      }
    }
    n = walker.nextNode()
  }
  for (const el of toUnwrap) {
    while (el.firstChild) el.parentNode.insertBefore(el.firstChild, el)
    el.remove()
  }
  return root.innerHTML
}
