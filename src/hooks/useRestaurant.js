import { useState, useEffect } from 'react'
import { getRestaurant } from '../lib/api.js'

export function useRestaurant(name, location) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!name || !location) return

    let cancelled = false
    setLoading(true)
    setError(null)

    getRestaurant(name, location)
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load restaurant data.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [name, location])

  return { data, loading, error }
}
