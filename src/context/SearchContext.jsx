import { createContext, useContext, useState } from 'react'

const SearchContext = createContext({})

export function SearchProvider({ children }) {
  const [query, setQuery] = useState('')
  const [location, setLocation] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState('delivery') // 'delivery' or 'pickup'

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
  }

  return <SearchContext.Provider value={value}>{children}</SearchContext.Provider>
}

export const useSearchContext = () => useContext(SearchContext)
