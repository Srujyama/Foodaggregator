import { AlertCircle, RefreshCw } from 'lucide-react'

export default function ErrorBanner({ message, onRetry }) {
  return (
    <div className="rounded-2xl border border-red-200 bg-red-50 p-6 flex flex-col items-center text-center gap-3">
      <AlertCircle className="w-8 h-8 text-red-400" />
      <div>
        <p className="font-semibold text-red-800">Something went wrong</p>
        <p className="text-sm text-red-600 mt-1">{message || 'Please try again.'}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-2 mt-1 px-4 py-2 rounded-xl bg-red-100 hover:bg-red-200 text-red-700 text-sm font-medium transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Try Again
        </button>
      )}
    </div>
  )
}
