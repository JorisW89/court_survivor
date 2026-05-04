import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'

function LeaderboardTable({ entries, currentUserId }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-left py-2 text-xs font-medium text-gray-400 uppercase tracking-wide w-8">#</th>
            <th className="text-left py-2 text-xs font-medium text-gray-400 uppercase tracking-wide">Player</th>
            <th className="text-right py-2 text-xs font-medium text-gray-400 uppercase tracking-wide">Pts</th>
            <th className="text-right py-2 text-xs font-medium text-gray-400 uppercase tracking-wide hidden sm:table-cell">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {entries.map(entry => (
            <tr key={entry.user_id} className={entry.user_id === currentUserId ? 'bg-brand-50' : ''}>
              <td className="py-2.5 text-gray-400">{entry.rank}</td>
              <td className="py-2.5">
                <span className={`font-medium ${entry.user_id === currentUserId ? 'text-brand-700' : 'text-gray-800'}`}>
                  {entry.username}
                  {entry.user_id === currentUserId && <span className="text-xs text-brand-400 ml-1">(you)</span>}
                </span>
              </td>
              <td className="py-2.5 text-right font-semibold text-gray-900">{entry.total_points}</td>
              <td className="py-2.5 text-right hidden sm:table-cell">
                {entry.is_eliminated ? (
                  <span className="badge-eliminated">Out</span>
                ) : (
                  <span className="badge-surviving">In</span>
                )}
              </td>
            </tr>
          ))}
          {entries.length === 0 && (
            <tr>
              <td colSpan={4} className="py-4 text-center text-gray-400 text-xs">No picks yet</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default function GroupDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [group, setGroup] = useState(null)
  const [leaderboard, setLeaderboard] = useState([])
  const [loading, setLoading] = useState(true)
  const [copied, setCopied] = useState(false)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    Promise.all([
      api.get(`/groups/${id}`),
      api.get(`/groups/${id}/leaderboard`),
    ])
      .then(([g, lb]) => {
        setGroup(g.data)
        setLeaderboard(lb.data)
      })
      .catch(() => navigate('/groups'))
      .finally(() => setLoading(false))
  }, [id])

  function copyInvite() {
    navigator.clipboard.writeText(group.invite_code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  async function handleLeave() {
    if (!confirm('Leave this group?')) return
    setLeaving(true)
    try {
      await api.delete(`/groups/${id}/leave`)
      navigate('/groups')
    } catch {
      setLeaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!group) return null

  return (
    <div className="space-y-6">
      <div>
        <Link to="/groups" className="text-sm text-gray-400 hover:text-gray-600 mb-2 inline-block">← Groups</Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900">{group.name}</h1>
            <p className="text-sm text-gray-500">{group.members.length} member{group.members.length !== 1 ? 's' : ''}</p>
          </div>
          <button
            onClick={handleLeave}
            disabled={leaving}
            className="text-sm text-red-500 hover:text-red-700 transition-colors"
          >
            {leaving ? 'Leaving…' : 'Leave'}
          </button>
        </div>
      </div>

      {/* Invite */}
      <div className="card">
        <p className="text-sm font-medium text-gray-700 mb-2">Invite friends</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 bg-gray-50 text-gray-700 px-3 py-2 rounded-lg text-sm font-mono">
            {group.invite_code}
          </code>
          <button onClick={copyInvite} className="btn-secondary text-sm shrink-0">
            {copied ? 'Copied!' : 'Copy code'}
          </button>
        </div>
      </div>

      {/* Per-game leaderboards */}
      {leaderboard.length === 0 ? (
        <div className="card text-center py-10">
          <p className="text-gray-400 text-sm">No active games with group members yet.</p>
        </div>
      ) : (
        leaderboard.map(item => (
          <div key={item.game_id} className="card">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="font-semibold text-gray-900 leading-snug">{item.tournament_title}</h2>
                <p className="text-xs text-gray-400 mt-0.5">{item.division}'s Draw</p>
              </div>
              <Link
                to={`/games/${item.game_id}`}
                className="text-xs text-brand-600 font-medium hover:underline shrink-0"
              >
                View game →
              </Link>
            </div>
            <LeaderboardTable entries={item.entries} currentUserId={user?.id} />
          </div>
        ))
      )}

      {/* Members list */}
      <div className="card">
        <h2 className="font-semibold text-gray-900 mb-3">Members</h2>
        <div className="space-y-2">
          {group.members.map(m => (
            <div key={m.user_id} className="flex items-center justify-between text-sm">
              <span className={m.user_id === user?.id ? 'font-medium text-brand-700' : 'text-gray-700'}>
                {m.username}
                {m.user_id === group.created_by && <span className="text-xs text-gray-400 ml-1">· admin</span>}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
