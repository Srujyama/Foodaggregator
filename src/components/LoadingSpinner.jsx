import { Loader2 } from 'lucide-react'
import { cn } from '../lib/utils.js'

export default function LoadingSpinner({ className }) {
  return (
    <div className={cn('flex items-center justify-center py-16', className)}>
      <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
    </div>
  )
}

export function SkeletonCard() {
  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-5 animate-pulse">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="h-5 bg-gray-200 rounded w-48 mb-2" />
          <div className="h-3 bg-gray-100 rounded w-32" />
        </div>
        <div className="h-8 bg-gray-200 rounded-lg w-16" />
      </div>
      <div className="flex gap-2 mb-4">
        <div className="h-6 bg-gray-200 rounded-full w-24" />
        <div className="h-6 bg-gray-200 rounded-full w-20" />
        <div className="h-6 bg-gray-200 rounded-full w-28" />
      </div>
      <div className="h-10 bg-gray-100 rounded-xl w-full" />
    </div>
  )
}

export function SkeletonResults() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  )
}
