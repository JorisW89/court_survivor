import { useState, useEffect } from 'react'
import { Link, Navigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'

function StatCard({ label, value, sub }) {
  return (
    <div className="card py-4 px-5">
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  )
}

function statusBadge(status) {
  const map = {
    active: 'bg-green-50 text-green-700',
    completed: 'bg-gray-100 text-gray-500',
    upcoming: 'bg-yellow-50 text-yellow-700',
  }
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium capitalize ${map[status] ?? 'bg-gray-100 text-gray-500'}`}>
      {status}
    </span>
  )
}

export default function Profile() {
  const { user } = useAuth()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get('/auth/me/stats')
      .then(r => setStats(r.data))
      .catch(() => setError('Failed to load profile stats'))
      .finally(() => setLoading(false))
  }, [])

  if (!user) return <Navigate to="/login" replace />

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (error) {
    return <div className="card border-red-100 bg-red-50 text-red-700 text-sm">{error}</div>
  }

  const memberSince = stats.member_since
    ? new Date(stats.member_since).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
    : null

  return (
    <div className="space-y-7">
      {/* Header */}
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded-full bg-brand-600 flex items-center justify-center text-white text-xl font-bold select-none">
          {stats.username.charAt(0).toUpperCase()}
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900">{stats.username}</h1>
          {memberSince && <p className="text-sm text-gray-400">Member since {memberSince}</p>}
        </div>
      </div>

      {/* Stats grid */}
      <div>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Overview</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <StatCard label="Tournaments" value={stats.games_played} sub="games entered" />
          <StatCard label="Total Points" value={stats.total_points} />
          <StatCard
            label="Avg Points"
            value={stats.games_played > 0 ? stats.avg_points_per_game : '—'}
            sub="per tournament"
          />
          <StatCard
            label="Pick Accuracy"
            value={stats.total_picks > 0 ? `${stats.pick_accuracy}%` : '—'}
            sub={stats.total_picks > 0 ? `${stats.correct_picks} / ${stats.total_picks} picks` : 'no picks yet'}
          />
          <StatCard
            label="Avg Rank"
            value={stats.avg_rank != null ? `#${stats.avg_rank}` : '—'}
            sub="across tournaments"
          />
          <StatCard
            label="Favourite Pick"
            value={stats.most_picked_player ?? '—'}
            sub={stats.most_picked_player ? 'most picked player' : 'no picks yet'}
          />
        </div>
      </div>

      {/* Tournament history */}
      <div>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">Tournament History</h2>
        {stats.games.length === 0 ? (
          <div className="card text-center py-10">
            <p className="text-gray-500 text-sm">You haven't entered any tournaments yet.</p>
            <Link to="/" className="text-brand-600 text-sm font-medium hover:underline mt-1 inline-block">Browse active tournaments →</Link>
          </div>
        ) : (
          <div className="card p-0 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Tournament</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide hidden sm:table-cell">Division</th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide hidden sm:table-cell">Status</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Pts</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">Rank</th>
                  <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide hidden sm:table-cell">Correct</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {stats.games.map(g => (
                  <tr key={g.game_id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <Link to={`/games/${g.game_id}`} className="font-medium text-gray-900 hover:text-brand-600 transition-colors line-clamp-1">
                        {g.tournament_title}
                      </Link>
                      <span className="text-xs text-gray-400 sm:hidden">{g.division}'s</span>
                    </td>
                    <td className="px-4 py-3 text-gray-500 hidden sm:table-cell">{g.division}'s</td>
                    <td className="px-4 py-3 hidden sm:table-cell">{statusBadge(g.game_status)}</td>
                    <td className="px-4 py-3 text-right font-semibold text-gray-900">{g.total_points}</td>
                    <td className="px-4 py-3 text-right text-gray-500">
                      {g.rank ? `#${g.rank}` : '—'}
                      {g.rank && <span className="text-gray-400 text-xs"> /{g.participants}</span>}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-500 hidden sm:table-cell">
                      {g.picks_made > 0 ? `${g.correct_picks}/${g.picks_made}` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
