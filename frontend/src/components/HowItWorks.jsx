import { useState } from 'react'

const steps = [
  {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
      </svg>
    ),
    title: 'Pick one player per round',
    desc: 'Each round, choose a player you think will win their match. You can pick up until 1 hour before the match starts.',
  },
  {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    ),
    title: 'Build your streak',
    desc: 'Every correct pick extends your streak. Your points per round equal your streak length plus any ranking bonus. A wrong pick or missed deadline resets your streak to zero.',
  },
  {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
    ),
    title: 'Earn ranking bonuses',
    desc: 'Pick the underdog and earn extra points. If your player\'s ranking is lower than their opponent\'s: +1 for a gap of 1–4, +2 for 5–9, +3 for 10 or more.',
  },
  {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
      </svg>
    ),
    title: 'No repeat picks',
    desc: 'You can\'t pick the same player twice in the same tournament, so plan ahead.',
  },
]

export default function HowItWorks({ collapsible = false }) {
  const [open, setOpen] = useState(false)

  if (collapsible) {
    return (
      <div className="card mb-6">
        <button
          onClick={() => setOpen(o => !o)}
          className="w-full flex items-center justify-between text-left"
        >
          <span className="text-sm font-semibold text-gray-700">How it works</span>
          <svg
            className={`w-4 h-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
        {open && <RulesList />}
      </div>
    )
  }

  return (
    <div className="mt-5">
      <RulesList light />
    </div>
  )
}

function RulesList({ light = false }) {
  return (
    <ul className={`mt-4 space-y-3 ${light ? 'text-brand-100' : 'text-gray-600'}`}>
      {steps.map((s, i) => (
        <li key={i} className="flex gap-3">
          <span className={`mt-0.5 shrink-0 ${light ? 'text-brand-200' : 'text-brand-500'}`}>
            {s.icon}
          </span>
          <div>
            <p className={`text-sm font-semibold ${light ? 'text-white' : 'text-gray-800'}`}>{s.title}</p>
            <p className="text-sm">{s.desc}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}
