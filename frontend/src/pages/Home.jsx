import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { isPast, parseISO } from 'date-fns'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import GameCard from '../components/GameCard'
import HowItWorks from '../components/HowItWorks'

function isTournamentFinished(game) {
  const end = game.tournament?.end_date
  return end ? isPast(parseISO(end)) : false
}

export default function Home() {
  const { user } = useAuth()
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [pastExpanded, setPastExpanded] = useState(false)

  useEffect(() => {
    api.get('/games')
      .then(r => setGames(r.data))
      .catch(() => setError('Failed to load games'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full" />
      </div>
    )
  }

  const activeGames = games.filter(g => !isTournamentFinished(g))
  const pastGames = games.filter(g => isTournamentFinished(g))

  return (
    <div>
      {!user ? (
        <div className="card bg-gradient-to-br from-brand-600 to-brand-700 text-white mb-8 border-0">
          <h1 className="text-2xl font-bold mb-2">Court Survivor</h1>
          <p className="text-brand-100">
            Pick one squash player per round, build a streak, and earn bonus points for upsets.
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

      {!error && activeGames.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-gray-500">No active tournaments right now.</p>
          <p className="text-gray-400 text-sm mt-1">Check back soon — new tournaments are added automatically.</p>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {activeGames.map(game => (
          <GameCard key={game.id} game={game} />
        ))}
      </div>

      {pastGames.length > 0 && (
        <div className="mt-8">
          <button
            onClick={() => setPastExpanded(prev => !prev)}
            className="flex items-center gap-2 text-sm font-medium text-gray-500 hover:text-gray-700 transition-colors mb-4"
          >
            <svg
              className={`w-4 h-4 transition-transform ${pastExpanded ? 'rotate-90' : ''}`}
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            Past Tournaments ({pastGames.length})
          </button>

          {pastExpanded && (
            <div className="grid gap-4 sm:grid-cols-2">
              {pastGames.map(game => (
                <GameCard key={game.id} game={game} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
