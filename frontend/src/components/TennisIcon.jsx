export default function TennisIcon({ className = "w-6 h-6" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.6" />
      {/* Tennis ball seam — two S-curves crossing at center */}
      <path
        d="M12 3C7.5 4.5 7.5 10 12 12C16.5 14 16.5 19.5 12 21"
        stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" fill="none"
      />
      <path
        d="M12 3C16.5 4.5 16.5 10 12 12C7.5 14 7.5 19.5 12 21"
        stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" fill="none" opacity="0.55"
      />
    </svg>
  )
}
