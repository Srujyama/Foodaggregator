import { createContext, useContext, useState } from 'react'
import { getLastLocation } from '../lib/recentSearches.js'

const SearchContext = createContext({})

export function SearchProvider({ children }) {
  const [query, setQuery] = useState('')
  // Seed from the last-used location so trending chips / the navbar can search
  // without re-prompting for where the user is.
  const [location, setLocation] = useState(() => getLastLocation())
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState('delivery') // 'delivery' or 'pickup'
  // {platform_id: 'ok'|'empty'|'timeout'|'error'} from the last search
  const [platformStatus, setPlatformStatus] = useState({})

  const value = {
    query,
    setQuery,
    location,
    setLocation,
    results,
    setResults,
    loading,
    setLoading,
    error,
    setError,
    mode,
    setMode,
    platformStatus,
    setPlatformStatus,
  }

  return <SearchContext.Provider value={value}>{children}</SearchContext.Provider>
}

export const useSearchContext = () => useContext(SearchContext)
