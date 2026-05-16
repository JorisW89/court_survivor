import { Link } from 'react-router-dom'
import { formatDeadline, formatDateRange } from '../utils/format'
import SportIcon, { sportTheme, sportCategoryLabel } from './SportIcon'

function StatusBadge({ game, myParticipant }) {
  if (!myParticipant) return null
  if (myParticipant.my_picks?.length > 0) {
    return <span className="badge-active">Playing</span>
  }
  return <span className="badge-pending">Pick needed</span>
}

export default function GameCard({ game }) {
  const { tournament, division, current_round, participant_count, my_participant } = game
  const sport = tournament.sport ?? 'squash'
  const theme = sportTheme(sport)

  const needsPick = my_participant &&
    current_round?.status === 'open' &&
    !my_participant.my_picks?.find(p => p.round_id === current_round?.id)

  const currentPick = current_round
    ? my_participant?.my_picks?.find(p => p.round_id === current_round.id)
    : null

  return (
    <Link
      to={`/games/${game.id}`}
      className={`card block hover:shadow-md transition-shadow ${needsPick ? `ring-2 ${theme.ring}` : ''}`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <SportIcon sport={sport} className={`w-3.5 h-3.5 shrink-0 ${theme.icon}`} />
            <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">
              {sportCategoryLabel(sport, tournament.category)}
            </p>
          </div>
          <h3 className="font-semibold text-gray-900 leading-snug">{tournament.title}</h3>
          <p className="text-sm text-gray-500 mt-0.5">{formatDateRange(tournament.start_date, tournament.end_date)}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${
            division === 'Men' ? 'bg-blue-50 text-blue-700' : 'bg-pink-50 text-pink-700'
          }`}>
            {division === 'Men' ? "Men's" : "Women's"}
          </span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${theme.pill}`}>
            {theme.label}
          </span>
        </div>
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
