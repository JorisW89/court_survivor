import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import GameCard from '../components/GameCard'
import HowItWorks from '../components/HowItWorks'
import SportIcon, { sportTheme } from '../components/SportIcon'

const FILTERS = ['all', 'squash', 'tennis']

function SportFilterTabs({ filter, onChange, sports }) {
  const visible = ['all', ...sports]
  if (visible.length <= 2) return null // only one sport — no tabs needed

  return (
    <div className="flex gap-1 bg-gray-100 rounded-xl p-1 mb-5">
      {visible.map(s => {
        const theme = sportTheme(s)
        const active = filter === s
        return (
          <button
            key={s}
            onClick={() => onChange(s)}
            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              active ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {s !== 'all' && (
              <SportIcon sport={s} className={`w-3.5 h-3.5 ${active ? theme.icon : 'text-gray-400'}`} />
            )}
            {s === 'all' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        )
      })}
    </div>
  )
}

function SportSection({ sport, games }) {
  const theme = sportTheme(sport)
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <SportIcon sport={sport} className={`w-4 h-4 ${theme.icon}`} />
        <h3 className={`text-sm font-semibold uppercase tracking-wide ${theme.text}`}>
          {theme.label}
        </h3>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {games.map(game => (
          <GameCard key={game.id} game={game} />
        ))}
      </div>
    </div>
  )
}

export default function Home() {
  const { user } = useAuth()
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('all')

  useEffect(() => {
    api.get('/games')
      .then(r => setGames(r.data))
      .catch(() => setError('Failed to load games'))
      .finally(() => setLoading(false))
  }, [])

  const availableSports = useMemo(() => {
    const seen = new Set(games.map(g => g.tournament.sport ?? 'squash'))
    return FILTERS.filter(s => s !== 'all' && seen.has(s))
  }, [games])

  const filteredGames = useMemo(() => {
    if (filter === 'all') return games
    return games.filter(g => (g.tournament.sport ?? 'squash') === filter)
  }, [games, filter])

  const groupedBySport = useMemo(() => {
    if (filter !== 'all' || availableSports.length <= 1) return null
    const groups = {}
    for (const s of availableSports) {
      const sg = filteredGames.filter(g => (g.tournament.sport ?? 'squash') === s)
      if (sg.length > 0) groups[s] = sg
    }
    return groups
  }, [filter, filteredGames, availableSports])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full" />
      </div>
    )
  }

  return (
    <div>
      {!user ? (
        <div className="card bg-gradient-to-br from-brand-600 to-brand-700 text-white mb-8 border-0">
          <h1 className="text-2xl font-bold mb-2">Court Survivor</h1>
          <p className="text-brand-100">
            Pick one player per round across squash and tennis, build a streak, and earn bonus points for upsets.
            One wrong pick and your streak resets.
          </p>
          <HowItWorks />
          <div className="flex gap-3 mt-6">
            <Link to="/register" className="bg-white text-brand-600 font-semibold px-4 py-2 rounded-lg hover:bg-brand-50 transition-colors text-sm">
              Get started
            </Link>
            <Link to="/login" className="text-white border border-white/30 font-medium px-4 py-2 rounded-lg hover:bg-white/10 transition-colors text-sm">
              Sign in
            </Link>
          </div>
        </div>
      ) : (
        <HowItWorks collapsible />
      )}

      <div className="flex items-center justify-between mb-5">
        <h2 className="text-lg font-semibold text-gray-900">Active Tournaments</h2>
      </div>

      {error && (
        <div className="card border-red-100 bg-red-50 text-red-700 text-sm">{error}</div>
      )}

      {!error && (
        <>
          <SportFilterTabs filter={filter} onChange={setFilter} sports={availableSports} />

          {filteredGames.length === 0 ? (
            <div className="card text-center py-12">
              <p className="text-gray-500">No active tournaments right now.</p>
              <p className="text-gray-400 text-sm mt-1">Check back soon — new tournaments are added automatically.</p>
            </div>
          ) : groupedBySport ? (
            <div className="space-y-8">
              {Object.entries(groupedBySport).map(([sport, sportGames]) => (
                <SportSection key={sport} sport={sport} games={sportGames} />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {filteredGames.map(game => (
                <GameCard key={game.id} game={game} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
