import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'

function MemberPicksModal({ userId, username, groupId, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/groups/${groupId}/members/${userId}/picks`)
      .then(r => setData(r.data))
      .finally(() => setLoading(false))
  }, [userId, groupId])

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-end sm:items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl w-full max-w-md max-h-[80vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white rounded-t-2xl">
          <h2 className="font-semibold text-gray-900">{username}'s picks</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="p-5 space-y-5">
          {loading && (
            <div className="flex justify-center py-8">
              <div className="animate-spin w-5 h-5 border-2 border-brand-500 border-t-transparent rounded-full" />
            </div>
          )}

          {!loading && data && data.games.length === 0 && (
            <p className="text-sm text-gray-400 text-center py-6">No match results yet.</p>
          )}

          {!loading && data && data.games.map(game => (
            <div key={game.game_id}>
              <div className="mb-2">
                <p className="font-medium text-gray-800 text-sm leading-snug">{game.tournament_title}</p>
                <p className="text-xs text-gray-400">{game.division}'s Draw</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-left py-1.5 text-xs font-medium text-gray-400 uppercase tracking-wide">Round</th>
                      <th className="text-left py-1.5 text-xs font-medium text-gray-400 uppercase tracking-wide">Pick</th>
                      <th className="text-right py-1.5 text-xs font-medium text-gray-400 uppercase tracking-wide">Result</th>
                      <th className="text-right py-1.5 text-xs font-medium text-gray-400 uppercase tracking-wide">Pts</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {game.picks.map(pick => (
                      <tr key={pick.round_id}>
                        <td className="py-2 text-gray-500 text-xs whitespace-nowrap">{pick.round_name}</td>
                        <td className="py-2 font-medium text-gray-800">{pick.player_name}</td>
                        <td className="py-2 text-right">
                          {pick.is_correct === true && (
                            <span className="inline-block text-xs font-medium text-green-700 bg-green-50 px-1.5 py-0.5 rounded">Win</span>
                          )}
                          {pick.is_correct === false && (
                            <span className="inline-block text-xs font-medium text-red-600 bg-red-50 px-1.5 py-0.5 rounded">Out</span>
                          )}
                          {pick.is_correct === null && (
                            <span className="inline-block text-xs text-gray-400">—</span>
                          )}
                        </td>
                        <td className="py-2 text-right font-semibold text-gray-900">{pick.points_awarded}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function LeaderboardTable({ entries, currentUserId, onMemberClick }) {
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
            <tr
              key={entry.user_id}
              className={`cursor-pointer hover:bg-gray-50 transition-colors ${entry.user_id === currentUserId ? 'bg-brand-50 hover:bg-brand-50' : ''}`}
              onClick={() => onMemberClick(entry.user_id, entry.username)}
            >
              <td className="py-2.5 text-gray-400">{entry.rank}</td>
              <td className="py-2.5">
                <span className={`font-medium ${entry.user_id === currentUserId ? 'text-brand-700' : 'text-gray-800'}`}>
                  {entry.username}
                  {entry.user_id === currentUserId && <span className="text-xs text-brand-400 ml-1">(you)</span>}
                </span>
              </td>
              <td className="py-2.5 text-right font-semibold text-gray-900">{entry.total_points}</td>
              <td className="py-2.5 text-right hidden sm:table-cell">
                <span className="badge-active">Playing</span>
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

function OverallLeaderboard({ leaderboard, currentUserId, onMemberClick }) {
  const totals = {}
  for (const game of leaderboard) {
    for (const entry of game.entries) {
      if (!totals[entry.user_id]) {
        totals[entry.user_id] = { user_id: entry.user_id, username: entry.username, total_points: 0 }
      }
      totals[entry.user_id].total_points += entry.total_points
    }
  }

  const sorted = Object.values(totals).sort((a, b) => b.total_points - a.total_points)
  let rank = 1
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i].total_points < sorted[i - 1].total_points) rank = i + 1
    sorted[i].rank = rank
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-left py-2 text-xs font-medium text-gray-400 uppercase tracking-wide w-8">#</th>
            <th className="text-left py-2 text-xs font-medium text-gray-400 uppercase tracking-wide">Player</th>
            <th className="text-right py-2 text-xs font-medium text-gray-400 uppercase tracking-wide">Total pts</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {sorted.map(entry => (
            <tr
              key={entry.user_id}
              className={`cursor-pointer hover:bg-gray-50 transition-colors ${entry.user_id === currentUserId ? 'bg-brand-50 hover:bg-brand-50' : ''}`}
              onClick={() => onMemberClick(entry.user_id, entry.username)}
            >
              <td className="py-2.5 text-gray-400">{entry.rank}</td>
              <td className="py-2.5">
                <span className={`font-medium ${entry.user_id === currentUserId ? 'text-brand-700' : 'text-gray-800'}`}>
                  {entry.username}
                  {entry.user_id === currentUserId && <span className="text-xs text-brand-400 ml-1">(you)</span>}
                </span>
              </td>
              <td className="py-2.5 text-right font-semibold text-gray-900">{entry.total_points}</td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={3} className="py-4 text-center text-gray-400 text-xs">No picks yet</td>
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
  const [selectedMember, setSelectedMember] = useState(null) // { userId, username }

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

  function openMemberPicks(userId, username) {
    setSelectedMember({ userId, username })
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
      {selectedMember && (
        <MemberPicksModal
          userId={selectedMember.userId}
          username={selectedMember.username}
          groupId={id}
          onClose={() => setSelectedMember(null)}
        />
      )}

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

      {/* Overall leaderboard */}
      {leaderboard.length === 0 ? (
        <div className="card text-center py-10">
          <p className="text-gray-400 text-sm">No active games with group members yet.</p>
        </div>
      ) : (
        <>
          <div className="card">
            <h2 className="font-semibold text-gray-900 mb-4">Overall standings</h2>
            <OverallLeaderboard
              leaderboard={leaderboard}
              currentUserId={user?.id}
              onMemberClick={openMemberPicks}
            />
          </div>

          {/* Game list */}
          <div className="card">
            <h2 className="font-semibold text-gray-900 mb-3">Games</h2>
            <div className="divide-y divide-gray-50">
              {leaderboard.map(item => (
                <Link
                  key={item.game_id}
                  to={`/games/${item.game_id}`}
                  className="flex items-center justify-between py-3 hover:bg-gray-50 -mx-1 px-1 rounded-lg transition-colors"
                >
                  <div>
                    <p className="font-medium text-gray-800 text-sm leading-snug">{item.tournament_title}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{item.division}'s Draw</p>
                  </div>
                  <span className="text-gray-300 text-sm">→</span>
                </Link>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Members list */}
      <div className="card">
        <h2 className="font-semibold text-gray-900 mb-3">Members</h2>
        <div className="space-y-2">
          {group.members.map(m => (
            <div key={m.user_id} className="flex items-center justify-between text-sm">
              <button
                onClick={() => openMemberPicks(m.user_id, m.username)}
                className={`text-left hover:underline ${m.user_id === user?.id ? 'font-medium text-brand-700' : 'text-gray-700'}`}
              >
                {m.username}
                {m.user_id === group.created_by && <span className="text-xs text-gray-400 ml-1">· admin</span>}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
