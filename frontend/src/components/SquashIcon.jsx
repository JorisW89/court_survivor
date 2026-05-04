export default function SquashIcon({ className = "w-6 h-6" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <ellipse cx="12" cy="9" rx="6" ry="6.5" stroke="currentColor" strokeWidth="1.6"/>
      <line x1="9.5" y1="3" x2="9.5" y2="15" stroke="currentColor" strokeWidth="0.8" strokeLinecap="round" opacity="0.65"/>
      <line x1="12" y1="2.5" x2="12" y2="15.5" stroke="currentColor" strokeWidth="0.8" strokeLinecap="round" opacity="0.65"/>
      <line x1="14.5" y1="3" x2="14.5" y2="15" stroke="currentColor" strokeWidth="0.8" strokeLinecap="round" opacity="0.65"/>
      <line x1="6.2" y1="6.5" x2="17.8" y2="6.5" stroke="currentColor" strokeWidth="0.8" strokeLinecap="round" opacity="0.65"/>
      <line x1="6" y1="9" x2="18" y2="9" stroke="currentColor" strokeWidth="0.8" strokeLinecap="round" opacity="0.65"/>
      <line x1="6.2" y1="11.5" x2="17.8" y2="11.5" stroke="currentColor" strokeWidth="0.8" strokeLinecap="round" opacity="0.65"/>
      <rect x="11" y="15" width="2" height="7" rx="1" fill="currentColor"/>
    </svg>
  )
}
