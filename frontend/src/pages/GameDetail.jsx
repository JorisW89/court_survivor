import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'
import { formatDeadline, formatDateRange } from '../utils/format'

const MATCH_PICK_LOCK_OFFSET_MS = 60 * 60 * 1000

function parseMatchTime(matchTime) {
  if (!matchTime) return null
  const normalized = String(matchTime).replace(' ', 'T')
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

function getMatchPickDeadline(matchTime) {
  const startTime = parseMatchTime(matchTime)
  return startTime ? new Date(startTime.getTime() - MATCH_PICK_LOCK_OFFSET_MS) : null
}

function formatTimeLeft(ms) {
  if (ms <= 0) return 'locked'

  const totalSeconds = Math.floor(ms / 1000)
  const days = Math.floor(totalSeconds / 86400)
  const hours = Math.floor((totalSeconds % 86400) / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${seconds.toString().padStart(2, '0')}s`
  return `${seconds}s`
}

function MatchPickTimer({ match, now }) {
  const deadline = getMatchPickDeadline(match.match_time)

  if (!deadline) {
    return (
      <span className="text-[11px] font-semibold rounded-full bg-gray-50 text-gray-500 px-2.5 py-1">
        Pick window TBA
      </span>
    )
  }

  const msLeft = deadline.getTime() - now.getTime()
  const locked = msLeft <= 0 || match.is_locked

  return (
    <span className={`text-[11px] font-semibold rounded-full px-2.5 py-1 ${
      locked
        ? 'bg-amber-50 text-amber-700'
        : msLeft < 10 * 60 * 1000
        ? 'bg-red-50 text-red-700'
        : 'bg-emerald-50 text-emerald-700'
    }`}>
      {locked ? 'Pick locked' : `Pick closes in ${formatTimeLeft(msLeft)}`}
    </span>
  )
}

// ── Pick history row ───────────────────────────────────────────────────────

function PickHistoryRow({ pick }) {
  const correct = pick.is_correct
  return (
    <div className={`flex items-center justify-between px-4 py-3 rounded-xl text-sm ${
      correct === true ? 'bg-emerald-50' : correct === false ? 'bg-red-50' : 'bg-gray-50'
    }`}>
      <div className="flex items-center gap-3">
        <span className={`text-xs font-semibold w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${
          correct === true  ? 'bg-emerald-200 text-emerald-800' :
          correct === false ? 'bg-red-200 text-red-700' :
                              'bg-gray-200 text-gray-600'
        }`}>
          {pick.round_order}
        </span>
        <div>
          <p className="font-medium text-gray-900">{pick.player_name}</p>
          <p className="text-xs text-gray-500">
            {pick.round_name}
            {pick.player_rank && <span> · rank #{pick.player_rank}</span>}
          </p>
        </div>
      </div>
      <div className="text-right shrink-0">
        {correct === true  && (
          <div>
            <span className="text-emerald-700 font-semibold">+{pick.points_awarded} pts</span>
            <p className="text-[11px] text-emerald-600">
              {pick.streak_points} streak{pick.ranking_bonus ? ` + ${pick.ranking_bonus} bonus` : ''}
            </p>
          </div>
        )}
        {correct === false && <span className="text-red-600 font-medium">Lost · 0 pts</span>}
        {correct === null  && <span className="text-amber-600 text-xs font-medium">Pending</span>}
      </div>
    </div>
  )
}

// ── Match card — shows two players, click one to pick ─────────────────────

function PlayerButton({ player, state, onClick }) {
  // state: 'selected' | 'other-selected' | 'used' | 'idle'
  const base = 'flex-1 flex flex-col items-stretch justify-center gap-2 px-3 py-4 rounded-xl border-2 transition-all text-sm font-medium'
  const styles = {
    selected:       'border-brand-500 bg-brand-50 text-brand-700 shadow-sm',
    'other-selected': 'border-gray-100 bg-gray-50 text-gray-400 opacity-60',
    used:           'border-gray-100 bg-gray-50 text-gray-400 cursor-not-allowed opacity-50',
    idle:           'border-gray-200 bg-white text-gray-800 hover:border-brand-300 hover:bg-brand-50/50 cursor-pointer',
  }

  return (
    <button
      type="button"
      disabled={state === 'used'}
      onClick={onClick}
      className={`${base} ${styles[state]}`}
    >
      <span className="text-center leading-snug text-gray-900">{player.name}</span>
      <div className="flex flex-wrap items-center justify-center gap-1.5">
        <span className="text-[11px] font-semibold rounded-full bg-gray-100 text-gray-600 px-2 py-0.5">
          {player.rank ? `#${player.rank}` : 'Unranked'}
        </span>
        {player.ranking_bonus > 0 && (
          <span className="text-[11px] font-semibold rounded-full bg-amber-100 text-amber-700 px-2 py-0.5">
            +{player.ranking_bonus} upset
          </span>
        )}
      </div>
      <div className={`rounded-lg px-2.5 py-2 text-center ${
        state === 'selected' ? 'bg-white text-brand-700' : 'bg-gray-50 text-gray-600'
      }`}>
        <p className="text-[11px] font-medium uppercase tracking-wide">If they win</p>
        <p className="text-lg leading-tight font-bold">+{player.potential_points} pts</p>
        <p className="text-[11px]">
          {player.streak_points} streak{player.ranking_bonus ? ` + ${player.ranking_bonus} bonus` : ''}
        </p>
      </div>
      {state === 'selected' && (
        <span className="text-xs bg-brand-500 text-white rounded-full px-2 py-0.5 mt-1">Your pick</span>
      )}
      {state === 'used' && (
        <span className="text-xs text-gray-400 mt-0.5">Already used</span>
      )}
    </button>
  )
}

function MatchCard({ match, selectedPlayerId, onSelect, roundLocked, now }) {
  const { player1, player2 } = match
  const matchPickDeadline = getMatchPickDeadline(match.match_time)
  const matchTimerLocked = matchPickDeadline ? now >= matchPickDeadline : false
  const locked = roundLocked || match.is_locked || matchTimerLocked

  function stateFor(player) {
    if (player.already_picked) return 'used'
    if (locked) return selectedPlayerId === player.id ? 'selected' : 'other-selected'
    if (selectedPlayerId === null) return 'idle'
    if (selectedPlayerId === player.id) return 'selected'
    return 'other-selected'
  }

  function handleClick(player) {
    if (locked || player.already_picked) return
    onSelect(selectedPlayerId === player.id ? null : player.id)
  }

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <MatchPickTimer match={match} now={now} />
        {match.match_time && (
          <span className="text-[11px] text-gray-400">
            Starts {parseMatchTime(match.match_time)?.toLocaleString([], {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        )}
      </div>
      <div className="flex items-stretch gap-2">
        <PlayerButton player={player1} state={stateFor(player1)} onClick={() => handleClick(player1)} />
        <div className="flex items-center justify-center w-7 shrink-0">
          <span className="text-xs font-semibold text-gray-300">vs</span>
        </div>
        <PlayerButton player={player2} state={stateFor(player2)} onClick={() => handleClick(player2)} />
      </div>
      {locked && !roundLocked && (
        <p className="text-xs text-amber-600 pl-1">Locked — match starts within 1 hour</p>
      )}
    </div>
  )
}

function PickPointsPreview({ player }) {
  if (!player) return null
  return (
    <div className="rounded-xl border border-brand-100 bg-brand-50 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-500">Selected pick</p>
          <p className="font-semibold text-brand-900">{player.name}</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold text-brand-700">+{player.potential_points}</p>
          <p className="text-xs text-brand-500">points if they win</p>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded-lg bg-white px-2 py-2">
          <p className="font-bold text-gray-900">#{player.rank || '—'}</p>
          <p className="text-gray-500">Rank</p>
        </div>
        <div className="rounded-lg bg-white px-2 py-2">
          <p className="font-bold text-gray-900">+{player.streak_points}</p>
          <p className="text-gray-500">Streak</p>
        </div>
        <div className="rounded-lg bg-white px-2 py-2">
          <p className="font-bold text-gray-900">+{player.ranking_bonus}</p>
          <p className="text-gray-500">Bonus</p>
        </div>
      </div>
    </div>
  )
}

// ── Previous round result (most recent completed, always expanded) ─────────

function PreviousRoundResult({ round, myPick }) {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-gray-900">{round.round_name} Results</h2>
        {myPick && (
          <span className={`text-xs px-2.5 py-1 rounded-full font-semibold ${
            myPick.is_correct ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
          }`}>
            {myPick.is_correct ? `+${myPick.points_awarded} pts` : '0 pts'}
          </span>
        )}
      </div>

      {myPick && (
        <div className={`mb-3 flex items-center gap-2 px-3 py-2.5 rounded-xl text-sm ${
          myPick.is_correct ? 'bg-emerald-50' : 'bg-red-50'
        }`}>
          <span className={`font-bold text-base ${myPick.is_correct ? 'text-emerald-600' : 'text-red-500'}`}>
            {myPick.is_correct ? '✓' : '✗'}
          </span>
          <span className="text-gray-500">Your pick:</span>
          <span className={`font-semibold ${myPick.is_correct ? 'text-emerald-800' : 'text-red-700'}`}>
            {myPick.player_name}
          </span>
          <span className={`text-xs ml-auto ${myPick.is_correct ? 'text-emerald-600' : 'text-red-500'}`}>
            {myPick.is_correct ? 'Won' : 'Lost'}
          </span>
        </div>
      )}

      <div className="divide-y divide-gray-50">
        {round.matches.map(m => {
          const p1Won = m.winner_name === m.player1_name
          const p2Won = m.winner_name === m.player2_name
          const userPickedP1 = myPick?.player_name === m.player1_name
          const userPickedP2 = myPick?.player_name === m.player2_name
          return (
            <div key={m.match_id} className="py-2.5 flex items-center gap-3 text-sm">
              <div className="flex-1 text-right">
                <span className={`${p1Won ? 'font-semibold text-gray-900' : 'text-gray-400'} ${userPickedP1 ? 'underline decoration-dotted' : ''}`}>
                  {m.player1_name}
                </span>
                {userPickedP1 && (
                  <span className="ml-1.5 text-xs text-gray-400">(your pick)</span>
                )}
              </div>
              <span className="text-xs text-gray-300 shrink-0">vs</span>
              <div className="flex-1">
                <span className={`${p2Won ? 'font-semibold text-gray-900' : 'text-gray-400'} ${userPickedP2 ? 'underline decoration-dotted' : ''}`}>
                  {m.player2_name}
                </span>
                {userPickedP2 && (
                  <span className="ml-1.5 text-xs text-gray-400">(your pick)</span>
                )}
              </div>
              {m.score && (
                <span className="text-xs text-gray-400 shrink-0 hidden sm:block">{m.score}</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Upcoming round draw (read-only, no auth required) ─────────────────────

function UpcomingRoundDraw({ round }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="border border-gray-100 rounded-2xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-700 text-sm">{round.round_name}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
            round.status === 'open'   ? 'bg-emerald-50 text-emerald-700' :
            round.status === 'locked' ? 'bg-amber-50 text-amber-700' :
                                        'bg-gray-100 text-gray-500'
          }`}>{round.status}</span>
        </div>
        <span className="text-xs text-gray-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="divide-y divide-gray-50">
          {round.matches.map(m => (
            <div key={m.match_id} className="px-4 py-3 flex items-center gap-3 text-sm">
              <div className="flex-1 text-right">
                <span className={m.winner_name === m.player1_name ? 'font-semibold text-gray-900' : 'text-gray-700'}>
                  {m.player1_name}
                </span>
              </div>
              <span className="text-xs text-gray-300 shrink-0">vs</span>
              <div className="flex-1">
                <span className={m.winner_name === m.player2_name ? 'font-semibold text-gray-900' : 'text-gray-700'}>
                  {m.player2_name}
                </span>
              </div>
              {m.match_time && (
                <span className="text-xs text-gray-400 shrink-0 hidden sm:block">
                  {new Date(m.match_time).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Completed round results ────────────────────────────────────────────────

function CompletedRoundResults({ round }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-gray-100 rounded-2xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <span className="font-medium text-gray-700 text-sm">{round.round_name}</span>
        <span className="text-xs text-gray-400">{open ? '▲' : '▼'} Results</span>
      </button>
      {open && (
        <div className="divide-y divide-gray-50">
          {round.matches.map(m => (
            <div key={m.match_id} className="px-4 py-3 flex items-center gap-3 text-sm">
              <div className="flex-1 text-right">
                <span className={m.winner_name === m.player1_name ? 'font-semibold text-gray-900' : 'text-gray-400'}>
                  {m.player1_name}
                </span>
              </div>
              <span className="text-xs text-gray-300 shrink-0">vs</span>
              <div className="flex-1">
                <span className={m.winner_name === m.player2_name ? 'font-semibold text-gray-900' : 'text-gray-400'}>
                  {m.player2_name}
                </span>
              </div>
              {m.score && (
                <span className="text-xs text-gray-400 shrink-0 hidden sm:block">{m.score}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function GameDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const [game, setGame] = useState(null)
  const [roundData, setRoundData] = useState(null)
  const [drawData, setDrawData] = useState(null)
  const [selectedPlayer, setSelectedPlayer] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')
  const [now, setNow] = useState(() => new Date())

  const loadGame = useCallback(async () => {
    const r = await api.get(`/games/${id}`)
    setGame(r.data)
    return r.data
  }, [id])

  const loadRoundPlayers = useCallback(async (gameData) => {
    const round = gameData?.current_round
    if (!round || !user || round.status === 'completed') return
    try {
      const r = await api.get(`/games/${id}/rounds/${round.id}/players`)
      setRoundData(r.data)
      setSelectedPlayer(r.data.my_pick || null)
    } catch {
      // round may have no matches yet
    }
  }, [id, user])

  const loadDraw = useCallback(async () => {
    try {
      const r = await api.get(`/games/${id}/draw`)
      setDrawData(r.data)
    } catch {
      // draw not critical
    }
  }, [id])

  useEffect(() => {
    Promise.all([
      loadGame().then(gameData => loadRoundPlayers(gameData)),
      loadDraw(),
    ])
      .catch(() => setError('Failed to load game'))
      .finally(() => setLoading(false))
  }, []) // eslint-disable-line

  useEffect(() => {
    const timerId = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timerId)
  }, [])

  function isMatchLocked(match) {
    const deadline = getMatchPickDeadline(match.match_time)
    return Boolean(match.is_locked || (deadline && now >= deadline))
  }

  async function handleSubmitPick() {
    if (!selectedPlayer || !game?.current_round) return
    setSubmitting(true)
    setError('')
    try {
      await api.post('/picks', {
        game_id: game.id,
        round_id: game.current_round.id,
        player_id: selectedPlayer,
      })
      setSuccessMsg('Pick saved!')
      setTimeout(() => setSuccessMsg(''), 3000)
      const r = await api.get(`/games/${id}`)
      setGame(r.data)
      await loadRoundPlayers(r.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to submit pick')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="animate-spin w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!game) {
    return <div className="card text-center py-12 text-gray-500">Game not found.</div>
  }

  const myP = game.my_participant
  const currentRound = game.current_round
  const canPick = user && currentRound && ['open', 'upcoming'].includes(currentRound.status)

  const lastCompletedRound = drawData?.rounds
    ?.filter(r => r.status === 'completed' && r.matches?.length > 0)
    ?.sort((a, b) => b.round_order - a.round_order)[0]
  const myLastPick = lastCompletedRound
    ? myP?.my_picks?.find(p => p.round_id === lastCompletedRound.round_id)
    : null
  const roundIsLocked = currentRound?.status === 'locked'
  const alreadyPickedThisRound = myP?.my_picks?.find(p => p.round_id === currentRound?.id)
  const selectedMatchLocked = selectedPlayer != null && roundData?.matches?.find(
    m => m.player1.id === selectedPlayer || m.player2.id === selectedPlayer
  )
  const selectedMatchIsLocked = selectedMatchLocked ? isMatchLocked(selectedMatchLocked) : false
  const selectedPlayerDetail = roundData?.matches
    ?.flatMap(m => [m.player1, m.player2])
    ?.find(p => p.id === selectedPlayer)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link to="/" className="text-sm text-gray-400 hover:text-gray-600 mb-2 inline-block">← All games</Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs text-gray-400 uppercase tracking-wide font-medium mb-1">
              {game.tournament.category || 'PSA World Tour'}
            </p>
            <h1 className="text-xl font-bold text-gray-900">{game.tournament.title}</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {formatDateRange(game.tournament.start_date, game.tournament.end_date)} · {game.division}'s Draw
            </p>
          </div>
          <Link to={`/games/${id}/leaderboard`} className="btn-secondary text-sm shrink-0">
            Leaderboard
          </Link>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="card py-4 text-center">
          <p className="text-2xl font-bold text-gray-900">{myP?.total_points ?? '—'}</p>
          <p className="text-xs text-gray-500 mt-0.5">Your points</p>
        </div>
        <div className="card py-4 text-center">
          <p className="text-2xl font-bold text-gray-900">{myP?.current_streak ?? 0}</p>
          <p className="text-xs text-gray-500 mt-0.5">Current streak</p>
        </div>
        <div className="card py-4 text-center">
          <p className="text-2xl font-bold text-gray-900">{game.participant_count}</p>
          <p className="text-xs text-gray-500 mt-0.5">Participants</p>
        </div>
      </div>

      {/* Previous round result */}
      {lastCompletedRound && (
        <PreviousRoundResult round={lastCompletedRound} myPick={myLastPick} />
      )}

      {/* Current round — pick section */}
      {currentRound && (
        <div className="card">
          <div className="flex items-center justify-between mb-1">
            <h2 className="font-semibold text-gray-900">{currentRound.name}</h2>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              currentRound.status === 'open'   ? 'bg-emerald-50 text-emerald-700' :
              currentRound.status === 'locked' ? 'bg-amber-50 text-amber-700' :
                                                  'bg-gray-50 text-gray-500'
            }`}>
              {currentRound.status}
            </span>
          </div>

          <p className="text-xs text-gray-400 mb-5">
            Each match locks 1 hour before it starts
          </p>

          {/* Match draw */}
          {(canPick || roundIsLocked) && roundData?.matches?.length > 0 ? (
            <div className="space-y-3">
              <p className="text-sm text-gray-500 mb-1">
                {canPick
                  ? alreadyPickedThisRound
                    ? 'Your current pick is highlighted. Tap another player to change it.'
                    : 'Pick one player from the draw. Points shown are awarded if that player wins.'
                  : 'Picks are locked for this round.'}
              </p>

              {roundData.matches.map(match => (
                <MatchCard
                  key={match.match_id}
                  match={match}
                  selectedPlayerId={selectedPlayer}
                  onSelect={canPick ? setSelectedPlayer : () => {}}
                  roundLocked={roundIsLocked}
                  now={now}
                />
              ))}

              {canPick && (
                <div className="pt-2 space-y-2">
                  <PickPointsPreview player={selectedPlayerDetail} />
                  {error    && <p className="text-sm text-red-600">{error}</p>}
                  {successMsg && <p className="text-sm text-emerald-600">{successMsg}</p>}
                  {selectedMatchIsLocked && (
                    <p className="text-sm text-amber-600">This match has already locked. Pick a different match.</p>
                  )}
                  <button
                    onClick={handleSubmitPick}
                    disabled={!selectedPlayer || submitting || selectedMatchIsLocked}
                    className="btn-primary w-full"
                  >
                    {submitting
                      ? 'Saving…'
                      : alreadyPickedThisRound
                      ? 'Update pick'
                      : 'Confirm pick'}
                  </button>
                </div>
              )}
            </div>
          ) : !user ? (
            <p className="text-sm text-gray-500">
              <Link to="/login" className="text-brand-600 font-medium hover:underline">Sign in</Link> to make picks.
            </p>
          ) : (
            <p className="text-sm text-gray-400">No draw available yet for this round.</p>
          )}
        </div>
      )}

      {/* Pick history */}
      {myP?.my_picks?.length > 0 && (
        <div className="card">
          <h2 className="font-semibold text-gray-900 mb-4">Your picks</h2>
          <div className="space-y-2">
            {myP.my_picks.map(pick => (
              <PickHistoryRow key={pick.round_id} pick={pick} />
            ))}
          </div>
        </div>
      )}

      {/* Full draw — all rounds except the current pick round (already shown above) */}
      {drawData?.rounds?.some(r => r.matches?.length > 0 && r.round_id !== currentRound?.id) && (
        <div className="card">
          <h2 className="font-semibold text-gray-900 mb-3">Full Draw</h2>
          <div className="space-y-2">
            {drawData.rounds
              .filter(r => r.matches?.length > 0 && r.round_id !== currentRound?.id)
              .sort((a, b) => a.round_order - b.round_order)
              .map(r =>
                r.status === 'completed'
                  ? <CompletedRoundResults key={r.round_id} round={r} />
                  : <UpcomingRoundDraw key={r.round_id} round={r} />
              )}
          </div>
        </div>
      )}
    </div>
  )
}
