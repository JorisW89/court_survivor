import { Link } from 'react-router-dom'
import { formatDeadline, formatDateRange } from '../utils/format'

function StatusBadge({ game, myParticipant }) {
  if (!myParticipant) return null
  if (myParticipant.my_picks?.length > 0) {
    return <span className="badge-active">Playing</span>
  }
  return <span className="badge-pending">Pick needed</span>
}

export default function GameCard({ game }) {
  const { tournament, division, current_round, participant_count, my_participant } = game

  const needsPick = my_participant &&
    current_round?.status === 'open' &&
    !my_participant.my_picks?.find(p => p.round_id === current_round?.id)

  const currentPick = current_round
    ? my_participant?.my_picks?.find(p => p.round_id === current_round.id)
    : null

  return (
    <Link
      to={`/games/${game.id}`}
      className={`card block hover:shadow-md transition-shadow ${needsPick ? 'ring-2 ring-brand-500' : ''}`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-0.5">
            {tournament.category || 'PSA World Tour'}
          </p>
          <h3 className="font-semibold text-gray-900 leading-snug">{tournament.title}</h3>
          <p className="text-sm text-gray-500 mt-0.5">{formatDateRange(tournament.start_date, tournament.end_date)}</p>
        </div>
        <span className={`shrink-0 text-xs font-semibold px-2.5 py-1 rounded-full ${
          division === 'Men' ? 'bg-blue-50 text-blue-700' : 'bg-pink-50 text-pink-700'
        }`}>
          {division === 'Men' ? "Men's" : "Women's"}
        </span>
      </div>

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-sm text-gray-500">
          {current_round ? (
            <span>{current_round.name}</span>
          ) : (
            <span>No active round</span>
          )}
          <span>·</span>
          <span>{participant_count} participant{participant_count !== 1 ? 's' : ''}</span>
        </div>
        <div className="flex items-center gap-2">
          {needsPick && (
            <span className="badge-pending animate-pulse">Pick now!</span>
          )}
          <StatusBadge game={game} myParticipant={my_participant} />
          {my_participant && (
            <span className="text-sm font-semibold text-gray-900">{my_participant.total_points}pts</span>
          )}
        </div>
      </div>

      {currentPick && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-gray-500">
          <span className="font-medium text-gray-700">{currentPick.player_name}</span>
          {currentPick.opponent_name && (
            <>
              <span className="text-gray-300">vs</span>
              <span>{currentPick.opponent_name}</span>
            </>
          )}
        </div>
      )}

      {current_round?.pick_deadline && (
        <p className="text-xs text-gray-400 mt-1">
          Last pick closes: {formatDeadline(current_round.pick_deadline)}
        </p>
      )}
    </Link>
  )
}
