import { useState, useEffect, useCallback } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { isPast, parseISO } from 'date-fns'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import SportIcon, { sportTheme } from '../components/SportIcon'

function SportBadge({ sport }) {
  const theme = sportTheme(sport ?? 'squash')
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${theme.pill}`}>
      <SportIcon sport={sport ?? 'squash'} className="w-2.5 h-2.5" />
      {theme.label}
    </span>
  )
}

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
                <div className="flex items-center gap-1.5 flex-wrap">
                  <p className="font-medium text-gray-800 text-sm leading-snug">{game.tournament_title}</p>
                  <SportBadge sport={game.sport} />
                </div>
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

function TournamentFilter({ groupId }) {
  const [open, setOpen] = useState(false)
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(false)
  const [toggling, setToggling] = useState(new Set())

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/groups/${groupId}/games`)
      .then(r => setGames(r.data))
      .finally(() => setLoading(false))
  }, [groupId])

  useEffect(() => {
    if (open && games.length === 0) load()
  }, [open, load, games.length])

  async function toggle(game) {
    if (toggling.has(game.game_id)) return
    setToggling(prev => new Set(prev).add(game.game_id))
    try {
      if (game.selected) {
        await api.delete(`/groups/${groupId}/games/${game.game_id}`)
      } else {
        await api.post(`/groups/${groupId}/games/${game.game_id}`)
      }
      setGames(prev => prev.map(g =>
        g.game_id === game.game_id ? { ...g, selected: !g.selected } : g
      ))
    } finally {
      setToggling(prev => { const s = new Set(prev); s.delete(game.game_id); return s })
    }
  }

  const hasSelection = games.some(g => g.selected)
  const activeGames = games.filter(g => !g.tournament_end_date || !isPast(parseISO(g.tournament_end_date)))
  const pastGames = games.filter(g => g.tournament_end_date && isPast(parseISO(g.tournament_end_date)))

  function GameRow({ game }) {
    const busy = toggling.has(game.game_id)
    return (
      <div className="flex items-center justify-between py-2.5">
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-800 leading-snug truncate">{game.tournament_title}</p>
          <p className="text-xs text-gray-400 mt-0.5">{game.division}'s Draw</p>
        </div>
        <button
          onClick={() => toggle(game)}
          disabled={busy}
          className={`relative shrink-0 ml-3 w-10 h-5 rounded-full transition-colors duration-200 focus:outline-none ${
            game.selected ? 'bg-brand-500' : 'bg-gray-200'
          } ${busy ? 'opacity-50' : ''}`}
          aria-label={game.selected ? 'Remove from ranking' : 'Add to ranking'}
        >
          <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200 ${
            game.selected ? 'translate-x-5' : 'translate-x-0'
          }`} />
        </button>
      </div>
    )
  }

  return (
    <div className="card">
      <button
        onClick={() => setOpen(prev => !prev)}
        className="flex items-center justify-between w-full text-left"
      >
        <div>
          <h2 className="font-semibold text-gray-900">Tournament filter</h2>
          <p className="text-xs text-gray-400 mt-0.5">
            {hasSelection ? 'Only selected tournaments count toward the ranking' : 'All active tournaments count toward the ranking'}
          </p>
        </div>
        <svg
          className={`w-4 h-4 text-gray-400 transition-transform shrink-0 ml-3 ${open ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="mt-4">
          {loading ? (
            <div className="flex justify-center py-6">
              <div className="animate-spin w-5 h-5 border-2 border-brand-500 border-t-transparent rounded-full" />
            </div>
          ) : (
            <>
              {!hasSelection && (
                <p className="text-xs text-gray-400 mb-3 italic">
                  Toggle tournaments on to limit the ranking to specific events. When none are selected, all active tournaments count.
                </p>
              )}
              {activeGames.length > 0 && (
                <div className="divide-y divide-gray-50">
                  {activeGames.map(g => <GameRow key={g.game_id} game={g} />)}
                </div>
              )}
              {pastGames.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Past</p>
                  <div className="divide-y divide-gray-50">
                    {pastGames.map(g => <GameRow key={g.game_id} game={g} />)}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
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
  const [selectedMember, setSelectedMember] = useState(null)

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

  const sportGroups = leaderboard.reduce((acc, item) => {
    const s = item.sport ?? 'squash'
    if (!acc[s]) acc[s] = []
    acc[s].push(item)
    return acc
  }, {})
  const hasMultipleSports = Object.keys(sportGroups).length > 1

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

      {/* Tournament filter */}
      <TournamentFilter groupId={id} />

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

          {/* Game list — grouped by sport when mixed */}
          <div className="card">
            <h2 className="font-semibold text-gray-900 mb-3">Games</h2>
            {hasMultipleSports ? (
              <div className="space-y-4">
                {Object.entries(sportGroups).map(([sport, items]) => {
                  const theme = sportTheme(sport)
                  return (
                    <div key={sport}>
                      <div className="flex items-center gap-1.5 mb-2">
                        <SportIcon sport={sport} className={`w-3.5 h-3.5 ${theme.icon}`} />
                        <span className={`text-xs font-semibold uppercase tracking-wide ${theme.text}`}>{theme.label}</span>
                      </div>
                      <div className="divide-y divide-gray-50">
                        {items.map(item => (
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
                  )
                })}
              </div>
            ) : (
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
            )}
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
