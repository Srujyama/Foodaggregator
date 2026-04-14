import { useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '../lib/utils.js'

const LOADING_MESSAGES = [
  'Searching Uber Eats...',
  'Checking DoorDash...',
  'Scanning Grubhub...',
  'Comparing delivery fees...',
  'Finding the best deals...',
  'Loading menus...',
  'Almost there...',
]

export default function LoadingSpinner({ className }) {
  const [msgIndex, setMsgIndex] = useState(0)

  useEffect(() => {
    const interval = setInterval(() => {
      setMsgIndex((i) => (i + 1) % LOADING_MESSAGES.length)
    }, 2200)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className={cn('flex flex-col items-center justify-center py-20 gap-4', className)}>
      <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
      <p className="text-sm text-gray-400 animate-pulse">{LOADING_MESSAGES[msgIndex]}</p>
    </div>
  )
}

export function SkeletonCard() {
  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-5 animate-pulse">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="h-5 bg-gray-200 rounded-lg w-48 mb-2" />
          <div className="h-3 bg-gray-100 rounded w-32" />
        </div>
        <div className="text-right">
          <div className="h-3 bg-gray-100 rounded w-12 mb-1" />
          <div className="h-6 bg-gray-200 rounded-lg w-16" />
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 mb-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-24 bg-gray-100 rounded-xl" />
        ))}
      </div>
      <div className="h-10 bg-gray-100 rounded-xl w-full" />
    </div>
  )
}

export function SkeletonResults() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 5 }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  )
}
