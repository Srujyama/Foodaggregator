import { useEffect, useState } from 'react'
import { TrendingUp, Zap, DollarSign, Clock, ArrowRight, ShieldCheck, Car, Tag, ExternalLink } from 'lucide-react'
import SearchBar from '../components/SearchBar.jsx'
import { getPopularSearches } from '../lib/firebase/firestore.js'
import { getDeals } from '../lib/api.js'
import { useSearch } from '../hooks/useSearch.js'
import { formatPrice, formatETA } from '../lib/utils.js'
import PlatformBadge from '../components/PlatformBadge.jsx'

const POPULAR_FALLBACK = [
  { id: '1', term: 'Pizza', location: '' },
  { id: '2', term: 'Sushi', location: '' },
  { id: '3', term: 'Burgers', location: '' },
  { id: '4', term: 'Chipotle', location: '' },
  { id: '5', term: 'Tacos', location: '' },
  { id: '6', term: 'Panda Express', location: '' },
  { id: '7', term: 'Thai Food', location: '' },
  { id: '8', term: "McDonald's", location: '' },
]

const FEATURES = [
  {
    icon: DollarSign,
    title: 'Compare Delivery Fees',
    desc: 'See delivery fees, service fees, and total costs side-by-side across all platforms.',
    color: 'text-emerald-600',
    bg: 'bg-emerald-50',
    border: 'border-emerald-100',
  },
  {
    icon: Car,
    title: 'Pickup Prices Too',
    desc: 'Toggle between delivery and pickup to see which saves you the most money.',
    color: 'text-violet-600',
    bg: 'bg-violet-50',
    border: 'border-violet-100',
  },
  {
    icon: Zap,
    title: 'Instant Results',
    desc: 'Real-time data from Uber Eats, DoorDash, and Grubhub in one search.',
    color: 'text-blue-600',
    bg: 'bg-blue-50',
    border: 'border-blue-100',
  },
  {
    icon: TrendingUp,
    title: 'Best Deal Ranked',
    desc: 'We automatically highlight the cheapest option so you never overpay.',
    color: 'text-amber-600',
    bg: 'bg-amber-50',
    border: 'border-amber-100',
  },
  {
    icon: Clock,
    title: 'Delivery & Pickup ETA',
    desc: 'Compare estimated times for both delivery and pickup options.',
    color: 'text-rose-600',
    bg: 'bg-rose-50',
    border: 'border-rose-100',
  },
  {
    icon: ShieldCheck,
    title: 'Always Up-to-Date',
    desc: 'Fresh prices fetched in real-time. No stale data or outdated menus.',
    color: 'text-teal-600',
    bg: 'bg-teal-50',
    border: 'border-teal-100',
  },
]

const PLATFORM_LOGOS = [
  { name: 'Uber Eats', bg: 'bg-gray-900', text: 'text-white' },
  { name: 'DoorDash', bg: 'bg-red-600', text: 'text-white' },
  { name: 'Grubhub', bg: 'bg-orange-500', text: 'text-white' },
]

export default function Home() {
  const [popular, setPopular] = useState(POPULAR_FALLBACK)
  const [deals, setDeals] = useState([])
  const [dealsLocation, setDealsLocation] = useState('')
  const { search, setQuery } = useSearch()

  useEffect(() => {
    getPopularSearches(8).then((data) => {
      if (data.length > 0) setPopular(data)
    })

    // Fetch deals for a default location (NYC) to populate the landing page
    const defaultLocation = 'New York, NY'
    getDeals(defaultLocation, 4)
      .then((data) => {
        if (data.results?.length > 0) {
          setDeals(data.results)
          setDealsLocation(defaultLocation)
        }
      })
      .catch(() => {})
  }, [])

  const handlePopularClick = (term) => {
    setQuery(term)
  }

  return (
    <main className="flex flex-col items-center">
      {/* Hero */}
      <section className="w-full bg-gradient-to-br from-orange-500 via-red-500 to-pink-500 relative overflow-hidden">
        {/* Background pattern */}
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-10 left-10 w-72 h-72 bg-white rounded-full blur-3xl" />
          <div className="absolute bottom-10 right-10 w-96 h-96 bg-yellow-300 rounded-full blur-3xl" />
        </div>

        <div className="relative max-w-3xl mx-auto text-center py-20 sm:py-28 px-4">
          <div className="inline-flex items-center gap-2 bg-white/20 backdrop-blur-sm rounded-full px-4 py-2 mb-6">
            <DollarSign className="w-4 h-4 text-yellow-300" />
            <span className="text-white/90 text-sm font-medium">
              Save up to 40% on delivery fees
            </span>
          </div>

          <h1 className="text-4xl sm:text-6xl font-black text-white mb-5 leading-tight tracking-tight">
            Find the Best Deal{' '}
            <span className="text-yellow-300">on Food Delivery</span>
          </h1>
          <p className="text-orange-100 text-lg sm:text-xl mb-10 max-w-xl mx-auto leading-relaxed">
            Compare prices across Uber Eats, DoorDash, and Grubhub in one search. Delivery or pickup -- we show you every option.
          </p>

          <SearchBar large />

          {/* Popular searches */}
          <div className="mt-8 flex flex-wrap justify-center gap-2">
            <span className="text-orange-200 text-sm mr-1 self-center">Trending:</span>
            {popular.slice(0, 7).map((item) => (
              <button
                key={item.id}
                onClick={() => handlePopularClick(item.term || item.id)}
                className="px-3.5 py-1.5 rounded-full bg-white/15 hover:bg-white/25 backdrop-blur-sm text-white text-sm font-medium transition-all duration-200 hover:scale-105"
              >
                {item.term || item.id}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Platform logos */}
      <section className="w-full bg-white border-b border-gray-100 py-5 px-4">
        <div className="max-w-3xl mx-auto flex flex-wrap items-center justify-center gap-6 text-sm">
          <span className="text-gray-400 font-medium">Comparing prices from</span>
          {PLATFORM_LOGOS.map((p) => (
            <span
              key={p.name}
              className={`${p.bg} ${p.text} px-4 py-1.5 rounded-full text-xs font-bold tracking-wide`}
            >
              {p.name}
            </span>
          ))}
        </div>
      </section>

      {/* Features */}
      <section className="w-full py-20 px-4 bg-gray-50">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold text-gray-900 mb-3">
              Why use FoodFinder?
            </h2>
            <p className="text-gray-500 max-w-lg mx-auto">
              Stop opening three apps just to compare prices. We do it all in one search.
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className={`rounded-2xl border ${f.border} bg-white p-6 hover:shadow-lg transition-all duration-300 hover:-translate-y-0.5 group`}
              >
                <div className={`w-12 h-12 rounded-xl ${f.bg} flex items-center justify-center mb-4`}>
                  <f.icon className={`w-6 h-6 ${f.color}`} />
                </div>
                <h3 className="font-bold text-gray-900 mb-2 text-lg">{f.title}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="w-full py-20 px-4 bg-white">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl font-bold text-gray-900 text-center mb-12">
            How it works
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              { step: '1', title: 'Search', desc: 'Type a restaurant name, cuisine, or dish and your location.' },
              { step: '2', title: 'Compare', desc: 'See delivery fees, service fees, ETAs, and menu prices from all 3 platforms.' },
              { step: '3', title: 'Order', desc: 'Click through to the cheapest platform and place your order directly.' },
            ].map((item, i) => (
              <div key={item.step} className="text-center relative">
                <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-orange-500 to-red-500 flex items-center justify-center mx-auto mb-4 text-white font-black text-xl shadow-lg shadow-orange-200">
                  {item.step}
                </div>
                <h3 className="font-bold text-gray-900 text-lg mb-2">{item.title}</h3>
                <p className="text-sm text-gray-500">{item.desc}</p>
                {i < 2 && (
                  <ArrowRight className="hidden md:block absolute top-7 -right-4 w-5 h-5 text-gray-300" />
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Today's Best Deals */}
      {deals.length > 0 && (
        <section className="w-full py-20 px-4 bg-gray-50">
          <div className="max-w-5xl mx-auto">
            <div className="text-center mb-10">
              <div className="inline-flex items-center gap-2 bg-emerald-50 border border-emerald-200 rounded-full px-4 py-1.5 mb-4">
                <Tag className="w-4 h-4 text-emerald-600" />
                <span className="text-emerald-700 text-sm font-medium">Live deals</span>
              </div>
              <h2 className="text-3xl font-bold text-gray-900 mb-3">
                Today's Best Deals
              </h2>
              <p className="text-gray-500">
                Free delivery and promos happening right now near {dealsLocation}
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {deals.map((deal) => {
                const bestPlatform = deal.platforms?.[0]
                const promo = deal.platforms?.find((p) => p.promo_text)?.promo_text
                return (
                  <div
                    key={deal.restaurant_name}
                    className="bg-white rounded-2xl border border-gray-200 p-5 hover:shadow-lg hover:border-orange-200 transition-all duration-300"
                  >
                    <h3 className="font-bold text-gray-900 text-sm mb-2 truncate">
                      {deal.restaurant_name}
                    </h3>
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {deal.platforms?.map((p) => (
                        <PlatformBadge key={p.platform} platform={p.platform} />
                      ))}
                    </div>
                    {promo && (
                      <p className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-2.5 py-1.5 mb-3 font-medium">
                        {promo}
                      </p>
                    )}
                    <div className="flex items-center justify-between text-xs text-gray-500">
                      <span>
                        Delivery: <span className="font-semibold text-emerald-600">{formatPrice(bestPlatform?.delivery_fee ?? 0)}</span>
                      </span>
                      <span>{formatETA(bestPlatform?.estimated_delivery_minutes)} </span>
                    </div>
                    {bestPlatform?.restaurant_url && (
                      <a
                        href={bestPlatform.restaurant_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center justify-center gap-1.5 w-full mt-3 py-2 rounded-xl bg-orange-50 border border-orange-200 text-xs font-semibold text-orange-600 hover:bg-orange-100 transition-all duration-200"
                      >
                        Order Now <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </section>
      )}

      {/* CTA */}
      <section className="w-full py-20 px-4 bg-gray-50">
        <div className="max-w-2xl mx-auto text-center bg-white border border-gray-200 rounded-3xl px-8 py-12 shadow-sm">
          <h2 className="text-2xl font-bold text-gray-900 mb-3">Ready to save on delivery?</h2>
          <p className="text-gray-500 mb-8">Search any restaurant or dish and see all prices instantly.</p>
          <SearchBar />
        </div>
      </section>

      {/* Footer */}
      <footer className="w-full bg-white border-t border-gray-100 py-8 px-4">
        <div className="max-w-4xl mx-auto text-center text-sm text-gray-400">
          <p>FoodFinder compares prices from Uber Eats, DoorDash, and Grubhub. We are not affiliated with any of these platforms.</p>
          <p className="mt-2">Prices, fees, and availability may vary. Always confirm the final total before ordering.</p>
        </div>
      </footer>
    </main>
  )
}
