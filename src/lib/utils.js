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
