// Every date/time the user sees goes through here, so all of them are shown in the
// browser's own timezone. The API speaks UTC ISO 8601 with offsets.

const dateTime = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
})

const timeOnly = new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
})

const dayAndTime = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
})

/** "Tue, Oct 13, 8:00 AM CDT" */
export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso))
}

/** "8:00 AM CDT" */
export function formatTime(iso: string): string {
  return timeOnly.format(new Date(iso))
}

/** "Tue 8:00 AM CDT" */
export function formatDayTime(iso: string): string {
  return dayAndTime.format(new Date(iso))
}

/** "12h 05m" */
export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, '0')}m`
}

/** The browser's IANA zone, e.g. "America/Chicago", for the "times shown in…" note. */
export function localZoneName(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone
}

/** A Date as the "YYYY-MM-DDTHH:mm" string a datetime-local input expects, in local time. */
export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/**
 * A datetime-local value (local wall time, no zone) as ISO 8601 with the local offset,
 * e.g. "2026-10-13T08:00" -> "2026-10-13T08:00:00-05:00" in Chicago during DST.
 */
export function localInputToIso(value: string): string {
  // Date parses offset-less date-time strings as local time.
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) throw new Error(`Invalid date/time: ${value}`)
  const offset = -date.getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  const pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, '0')
  return `${toLocalInputValue(date)}:00${sign}${pad(offset / 60)}:${pad(offset % 60)}`
}

/** The next whole local hour from ``now``: the default departure. */
export function nextHour(now: Date = new Date()): Date {
  const next = new Date(now)
  next.setMinutes(0, 0, 0)
  next.setHours(next.getHours() + 1)
  return next
}
