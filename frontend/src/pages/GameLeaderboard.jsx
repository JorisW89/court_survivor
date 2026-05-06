import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { formatDateRange } from '../utils/format'

export default function GameLeaderboard() {
  const { id } = useParams()
  const { user } = useAuth()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/games/${id}/leaderboard`)
      .then(r => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [id])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!data) return <div className="card text-center py-12 text-gray-500">Not found.</div>

  const { game, entries, my_rank } = data

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/games/${id}`} className="text-sm text-gray-400 hover:text-gray-600 mb-2 inline-block">← Back to game</Link>
        <h1 className="text-xl font-bold text-gray-900">{game.tournament.title}</h1>
        <p className="text-sm text-gray-500">
          {formatDateRange(game.tournament.start_date, game.tournament.end_date)} · {game.division}'s Draw
        </p>
      </div>

      {my_rank && (
        <div className="card bg-brand-50 border-brand-100">
          <p className="text-sm text-brand-600 font-medium">Your rank: #{my_rank} of {entries.length}</p>
        </div>
      )}

      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide w-10">#</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Player</th>
              <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Points</th>
              <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide hidden sm:table-cell">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {entries.map(entry => (
              <tr
                key={entry.user_id}
                className={`${entry.user_id === user?.id ? 'bg-brand-50' : 'hover:bg-gray-50'} transition-colors`}
              >
                <td className="px-4 py-3 text-gray-400 font-medium">{entry.rank}</td>
                <td className="px-4 py-3">
                  <span className={`font-medium ${entry.user_id === user?.id ? 'text-brand-700' : 'text-gray-900'}`}>
                    {entry.username}
                    {entry.user_id === user?.id && <span className="text-xs text-brand-400 ml-1">(you)</span>}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-semibold text-gray-900">{entry.total_points}</td>
                <td className="px-4 py-3 text-right hidden sm:table-cell">
                  <span className="badge-surviving">Playing</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {entries.length === 0 && (
          <p className="text-center text-gray-400 text-sm py-8">No participants yet.</p>
        )}
      </div>
    </div>
  )
}
