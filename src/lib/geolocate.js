const GEO_TIMEOUT_MS = 8000

function getPosition() {
  return new Promise((resolve, reject) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      reject(new Error('Geolocation is not supported by this browser'))
      return
    }
    navigator.geolocation.getCurrentPosition(
      resolve,
      (err) => reject(new Error(err?.message || 'Location access denied')),
      { enableHighAccuracy: false, timeout: GEO_TIMEOUT_MS },
    )
  })
}

export async function getCurrentLocationLabel() {
  const pos = await getPosition()
  const { latitude: lat, longitude: lng } = pos.coords
  const coordsLabel = `${lat.toFixed(3)},${lng.toFixed(3)}`

  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`,
      { headers: { 'Accept-Language': 'en' } },
    )
    if (!res.ok) return coordsLabel
    const data = await res.json()
    const addr = data?.address || {}

    if (addr.postcode) return addr.postcode

    const city = addr.city || addr.town || addr.village
    if (city) {
      // Nominatim puts the state ISO code in e.g. "ISO3166-2-lvl4": "US-CA"
      const iso = addr['ISO3166-2-lvl4']
      const abbrev = typeof iso === 'string' && iso.includes('-') ? iso.split('-').pop() : null
      const state = abbrev || addr.state
      return state ? `${city}, ${state}` : city
    }

    return coordsLabel
  } catch {
    return coordsLabel
  }
}
