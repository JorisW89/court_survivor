import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import GameCard from '../components/GameCard'

export default function Home() {
  const { user } = useAuth()
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

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

  return (
    <div>
      {!user && (
        <div className="card bg-gradient-to-br from-brand-600 to-brand-700 text-white mb-8 border-0">
          <div className="max-w-lg">
            <h1 className="text-2xl font-bold mb-2">Court Survivor</h1>
            <p className="text-brand-100 mb-4">
              Pick one player per round. Correct picks build a streak, upsets add ranking bonuses,
              and you can never pick the same player twice.
            </p>
            <div className="flex gap-3">
              <Link to="/register" className="bg-white text-brand-600 font-semibold px-4 py-2 rounded-lg hover:bg-brand-50 transition-colors text-sm">
                Get started
              </Link>
              <Link to="/login" className="text-white border border-white/30 font-medium px-4 py-2 rounded-lg hover:bg-white/10 transition-colors text-sm">
                Sign in
              </Link>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between mb-5">
        <h2 className="text-lg font-semibold text-gray-900">Active Tournaments</h2>
        {user && games.length > 0 && (
          <Link to="/groups" className="text-sm text-brand-600 font-medium hover:underline">
            My groups →
          </Link>
        )}
      </div>

      {error && (
        <div className="card border-red-100 bg-red-50 text-red-700 text-sm">{error}</div>
      )}

      {!error && games.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-gray-500">No active tournaments right now.</p>
          <p className="text-gray-400 text-sm mt-1">Check back soon — new tournaments are added automatically.</p>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {games.map(game => (
          <GameCard key={game.id} game={game} />
        ))}
      </div>
    </div>
  )
}
