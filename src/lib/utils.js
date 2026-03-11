import { clsx } from 'clsx'

export function cn(...inputs) {
  return clsx(inputs)
}

export function getApiUrl() {
  return import.meta.env.VITE_API_URL || 'http://localhost:8000'
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
