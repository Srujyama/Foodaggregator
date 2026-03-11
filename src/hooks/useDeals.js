import { useState, useEffect } from 'react'
import { getDeals } from '../lib/api.js'

export function useDeals(location) {
  const [deals, setDeals] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!location) return

    let cancelled = false
    setLoading(true)
    setError(null)

    getDeals(location)
      .then((data) => {
        if (!cancelled) setDeals(data.results || [])
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load deals.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [location])

  return { deals, loading, error }
}
