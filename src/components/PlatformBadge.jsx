import { cn } from '../lib/utils.js'

const PLATFORM_CONFIG = {
  uber_eats: {
    label: 'Uber Eats',
    bg: 'bg-black',
    text: 'text-white',
    dot: 'bg-green-400',
  },
  doordash: {
    label: 'DoorDash',
    bg: 'bg-red-600',
    text: 'text-white',
    dot: 'bg-red-300',
  },
  grubhub: {
    label: 'Grubhub',
    bg: 'bg-orange-500',
    text: 'text-white',
    dot: 'bg-orange-200',
  },
}

export default function PlatformBadge({ platform, size = 'sm' }) {
  const config = PLATFORM_CONFIG[platform] || {
    label: platform,
    bg: 'bg-gray-500',
    text: 'text-white',
    dot: 'bg-gray-300',
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full font-medium',
        config.bg,
        config.text,
        size === 'sm' ? 'px-2.5 py-0.5 text-xs' : 'px-3 py-1 text-sm',
      )}
    >
      <span className={cn('rounded-full', config.dot, size === 'sm' ? 'w-1.5 h-1.5' : 'w-2 h-2')} />
      {config.label}
    </span>
  )
}

export { PLATFORM_CONFIG }
