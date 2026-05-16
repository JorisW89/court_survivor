import SquashIcon from './SquashIcon'
import TennisIcon from './TennisIcon'

export default function SportIcon({ sport, className }) {
  if (sport === 'tennis') return <TennisIcon className={className} />
  return <SquashIcon className={className} />
}

export function sportTheme(sport) {
  if (sport === 'tennis') {
    return {
      pill: 'bg-orange-50 text-orange-600',
      pillDark: 'bg-orange-100 text-orange-700',
      ring: 'ring-orange-400',
      text: 'text-orange-600',
      icon: 'text-orange-500',
      label: 'Tennis',
    }
  }
  return {
    pill: 'bg-brand-50 text-brand-600',
    pillDark: 'bg-brand-100 text-brand-700',
    ring: 'ring-brand-500',
    text: 'text-brand-600',
    icon: 'text-brand-600',
    label: 'Squash',
  }
}

export function sportCategoryLabel(sport, category) {
  if (category) return category
  return sport === 'tennis' ? 'Grand Slam' : 'PSA World Tour'
}
