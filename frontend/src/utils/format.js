import { format, formatDistanceToNow, isPast, parseISO } from 'date-fns'

export function formatDateRange(start, end) {
  if (!start && !end) return ''
  try {
    const s = start ? format(parseISO(start), 'd MMM') : ''
    const e = end ? format(parseISO(end), 'd MMM yyyy') : ''
    return s && e ? `${s} – ${e}` : s || e
  } catch {
    return [start, end].filter(Boolean).join(' – ')
  }
}

export function formatDeadline(deadline) {
  if (!deadline) return ''
  try {
    const d = typeof deadline === 'string' ? parseISO(deadline) : deadline
    if (isPast(d)) return 'Deadline passed'
    return `${format(d, 'd MMM HH:mm')} UTC (${formatDistanceToNow(d, { addSuffix: true })})`
  } catch {
    return deadline
  }
}

export function formatDateTime(dt) {
  if (!dt) return ''
  try {
    const d = typeof dt === 'string' ? parseISO(dt) : dt
    return format(d, 'd MMM yyyy, HH:mm')
  } catch {
    return dt
  }
}
