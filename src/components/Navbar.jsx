import { Link, useNavigate } from 'react-router-dom'
import { Utensils, Search } from 'lucide-react'
import { useState } from 'react'
import { useSearchContext } from '../context/SearchContext.jsx'
import { useSearch } from '../hooks/useSearch.js'

export default function Navbar() {
  const { query, location } = useSearchContext()
  const { search, setQuery, setLocation } = useSearch()
  const [showMiniSearch, setShowMiniSearch] = useState(false)
  const navigate = useNavigate()

  return (
    <nav className="bg-white border-b border-gray-200 sticky top-0 z-50 shadow-sm">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between gap-4">
        {/* Logo */}
        <Link to="/" className="flex items-center gap-2 shrink-0">
          <Utensils className="w-6 h-6 text-orange-500" />
          <span className="font-bold text-lg text-gray-900 hidden sm:block">
            Food<span className="text-orange-500">Finder</span>
          </span>
        </Link>

        {/* Mini search bar (desktop) */}
        <div className="hidden md:flex flex-1 max-w-xl items-center gap-2">
          <div className="flex flex-1 border border-gray-300 rounded-full overflow-hidden bg-gray-50 hover:border-orange-400 transition-colors">
            <input
              type="text"
              placeholder="Restaurant or dish..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && search()}
              className="flex-1 px-4 py-2 bg-transparent text-sm outline-none"
            />
            <div className="w-px bg-gray-300 my-2" />
            <input
              type="text"
              placeholder="Location..."
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && search()}
              className="w-36 px-4 py-2 bg-transparent text-sm outline-none"
            />
            <button
              onClick={() => search()}
              className="px-4 bg-orange-500 hover:bg-orange-600 text-white transition-colors"
            >
              <Search className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Mobile search icon */}
        <button
          className="md:hidden p-2 rounded-full hover:bg-gray-100"
          onClick={() => navigate('/')}
        >
          <Search className="w-5 h-5 text-gray-600" />
        </button>
      </div>
    </nav>
  )
}
