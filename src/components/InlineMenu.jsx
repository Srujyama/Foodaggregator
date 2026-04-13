import { useState, useEffect } from 'react'
import { ExternalLink, Loader2, ShoppingBag } from 'lucide-react'
import { getRestaurant } from '../lib/api.js'
import { formatPrice } from '../lib/utils.js'
import PlatformBadge from './PlatformBadge.jsx'
import { cn } from '../lib/utils.js'

const PLATFORM_LABELS = {
  uber_eats: 'Uber Eats',
  doordash: 'DoorDash',
  grubhub: 'Grubhub',
}

export default function InlineMenu({ restaurantName, location, platforms }) {
  const [detailData, setDetailData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState(null)

  // Check if search results already have menu items
  const existingMenus = platforms.filter((p) => p.menu_items?.length > 0)

  useEffect(() => {
    // If we already have menu data from search, use it
    if (existingMenus.length > 0) {
      setActiveTab(existingMenus[0].platform)
      return
    }

    // Otherwise fetch the restaurant details to get menus
    let cancelled = false
    setLoading(true)
    setError(null)

    getRestaurant(restaurantName, location)
      .then((data) => {
        if (!cancelled) {
          setDetailData(data)
          const withMenu = data?.platforms?.filter((p) => p.menu_items?.length > 0)
          if (withMenu?.length > 0) {
            setActiveTab(withMenu[0].platform)
          }
        }
      })
      .catch((err) => {
        if (!cancelled) setError('Could not load menu')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [restaurantName, location])

  // Use existing menus if available, otherwise use fetched data
  const menuPlatforms = existingMenus.length > 0
    ? existingMenus
    : (detailData?.platforms?.filter((p) => p.menu_items?.length > 0) || [])

  return (
    <div className="border-t border-gray-100 bg-gray-50/50">
      {loading && (
        <div className="flex items-center justify-center gap-2 py-8 text-gray-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading menu...</span>
        </div>
      )}

      {error && (
        <div className="px-5 py-4 text-center text-sm text-gray-400">
          {error}. Check the full details page for menu info.
        </div>
      )}

      {!loading && menuPlatforms.length === 0 && !error && (
        <div className="px-5 py-6 text-center text-sm text-gray-400">
          Menu not available for this restaurant. Try viewing on the platform directly.
        </div>
      )}

      {!loading && menuPlatforms.length > 0 && (
        <>
          {/* Platform tabs */}
          <div className="flex items-center gap-1 px-5 pt-3 pb-2 overflow-x-auto">
            {menuPlatforms.map((p) => (
              <button
                key={p.platform}
                onClick={() => setActiveTab(p.platform)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap',
                  activeTab === p.platform
                    ? 'bg-white text-gray-900 shadow-sm border border-gray-200'
                    : 'text-gray-500 hover:text-gray-700 hover:bg-white/50',
                )}
              >
                <PlatformBadge platform={p.platform} />
                <span className="text-gray-400">({p.menu_items.length})</span>
              </button>
            ))}
          </div>

          {/* Menu items for active tab */}
          {menuPlatforms
            .filter((p) => p.platform === activeTab)
            .map((platform) => (
              <div key={platform.platform} className="px-5 pb-4">
                <div className="bg-white rounded-xl border border-gray-200 overflow-hidden divide-y divide-gray-100">
                  {platform.menu_items.slice(0, 20).map((item, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
                    >
                      {item.image_url && (
                        <img
                          src={item.image_url}
                          alt={item.name}
                          className="w-14 h-14 rounded-lg object-cover shrink-0"
                          onError={(e) => { e.target.style.display = 'none' }}
                        />
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-gray-900 text-sm">{item.name}</p>
                        {item.description && (
                          <p className="text-xs text-gray-400 line-clamp-2 mt-0.5">{item.description}</p>
                        )}
                      </div>
                      <span className="font-semibold text-gray-800 text-sm shrink-0 tabular-nums">
                        {formatPrice(item.price)}
                      </span>
                    </div>
                  ))}
                  {platform.menu_items.length > 20 && (
                    <div className="px-4 py-2 text-center text-xs text-gray-400 bg-gray-50">
                      +{platform.menu_items.length - 20} more items
                    </div>
                  )}
                </div>

                {/* Order button */}
                {platform.restaurant_url && (
                  <a
                    href={platform.restaurant_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-2 w-full mt-3 py-2.5 rounded-xl bg-gradient-to-r from-orange-500 to-red-500 text-white text-sm font-semibold hover:from-orange-600 hover:to-red-600 transition-all duration-200 shadow-sm"
                  >
                    <ShoppingBag className="w-4 h-4" />
                    Order on {PLATFORM_LABELS[platform.platform] || platform.platform}
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                )}
              </div>
            ))}
        </>
      )}
    </div>
  )
}
