import { useEffect, useState } from 'react'
import { TrendingUp, Zap, DollarSign, Clock } from 'lucide-react'
import SearchBar from '../components/SearchBar.jsx'
import { getPopularSearches } from '../lib/firebase/firestore.js'
import { useSearch } from '../hooks/useSearch.js'

const POPULAR_FALLBACK = [
  { id: '1', term: 'Pizza', location: '' },
  { id: '2', term: 'Sushi', location: '' },
  { id: '3', term: 'Burgers', location: '' },
  { id: '4', term: 'Chipotle', location: '' },
  { id: '5', term: 'Tacos', location: '' },
  { id: '6', term: 'Panda Express', location: '' },
  { id: '7', term: 'Thai Food', location: '' },
  { id: '8', term: 'McDonald\'s', location: '' },
]

const FEATURES = [
  {
    icon: DollarSign,
    title: 'Compare Prices',
    desc: 'See delivery fees, service fees, and total costs side-by-side across all platforms.',
    color: 'text-green-500',
    bg: 'bg-green-50',
  },
  {
    icon: Zap,
    title: 'Instant Results',
    desc: 'Real-time data from Uber Eats, DoorDash, and Grubhub in one search.',
    color: 'text-blue-500',
    bg: 'bg-blue-50',
  },
  {
    icon: TrendingUp,
    title: 'Best Deal Ranked',
    desc: 'We automatically highlight the cheapest option so you never overpay.',
    color: 'text-amber-500',
    bg: 'bg-amber-50',
  },
  {
    icon: Clock,
    title: 'Delivery ETA',
    desc: 'Compare estimated delivery times to choose the fastest or cheapest option.',
    color: 'text-purple-500',
    bg: 'bg-purple-50',
  },
]

export default function Home() {
  const [popular, setPopular] = useState(POPULAR_FALLBACK)
  const { search, setQuery, setLocation } = useSearch()

  useEffect(() => {
    getPopularSearches(8).then((data) => {
      if (data.length > 0) setPopular(data)
    })
  }, [])

  const handlePopularClick = (term) => {
    setQuery(term)
  }

  return (
    <main className="flex flex-col items-center">
      {/* Hero */}
      <section className="w-full bg-gradient-to-br from-orange-500 via-orange-600 to-red-500 py-20 px-4">
        <div className="max-w-3xl mx-auto text-center">
          <h1 className="text-4xl sm:text-5xl font-extrabold text-white mb-4 leading-tight">
            Find the{' '}
            <span className="text-yellow-300 underline decoration-wavy decoration-yellow-200/60">
              Best Deal
            </span>{' '}
            on Food Delivery
          </h1>
          <p className="text-orange-100 text-lg sm:text-xl mb-10 max-w-xl mx-auto">
            Compare prices across Uber Eats, DoorDash, and Grubhub in one search. Stop overpaying on delivery fees.
          </p>

          <SearchBar large />

          {/* Popular searches */}
          <div className="mt-8 flex flex-wrap justify-center gap-2">
            <span className="text-orange-200 text-sm mr-1">Popular:</span>
            {popular.slice(0, 7).map((item) => (
              <button
                key={item.id}
                onClick={() => handlePopularClick(item.term || item.id)}
                className="px-3 py-1.5 rounded-full bg-white/20 hover:bg-white/30 text-white text-sm font-medium transition-colors"
              >
                {item.term || item.id}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Platform logos */}
      <section className="w-full bg-white border-b border-gray-100 py-6 px-4">
        <div className="max-w-3xl mx-auto flex flex-wrap items-center justify-center gap-8 text-sm font-semibold text-gray-400">
          <span>Comparing prices from:</span>
          <span className="px-4 py-1.5 rounded-full bg-black text-white text-xs">Uber Eats</span>
          <span className="px-4 py-1.5 rounded-full bg-red-600 text-white text-xs">DoorDash</span>
          <span className="px-4 py-1.5 rounded-full bg-orange-500 text-white text-xs">Grubhub</span>
        </div>
      </section>

      {/* Features */}
      <section className="w-full py-16 px-4">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-2xl font-bold text-gray-900 text-center mb-10">
            Why use FoodFinder?
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {FEATURES.map((f) => (
              <div key={f.title} className="rounded-2xl border border-gray-200 bg-white p-5 text-center hover:shadow-md transition-shadow">
                <div className={`w-12 h-12 rounded-xl ${f.bg} flex items-center justify-center mx-auto mb-3`}>
                  <f.icon className={`w-6 h-6 ${f.color}`} />
                </div>
                <h3 className="font-semibold text-gray-900 mb-1.5">{f.title}</h3>
                <p className="text-sm text-gray-500">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="w-full pb-20 px-4">
        <div className="max-w-2xl mx-auto text-center bg-orange-50 border border-orange-200 rounded-3xl px-8 py-10">
          <h2 className="text-2xl font-bold text-gray-900 mb-2">Ready to save on delivery?</h2>
          <p className="text-gray-500 mb-6">Search any restaurant or dish and see all prices instantly.</p>
          <SearchBar />
        </div>
      </section>
    </main>
  )
}
