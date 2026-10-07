/**
 * Locale-aware formatting built on Intl. These format UI values only; never
 * pass source titles, URLs, filenames, identifiers or stored report text.
 */

export type DateInput = string | number | Date

export interface LocaleFormatters {
  locale: string
  number: (value: number, options?: Intl.NumberFormatOptions) => string
  /** `ratio` is a fraction: 0.42 formats as "42%" in English. */
  percent: (ratio: number, maximumFractionDigits?: number) => string
  date: (value: DateInput, options?: Intl.DateTimeFormatOptions) => string
  time: (value: DateInput) => string
  dateTime: (value: DateInput) => string
  /** "3 days ago", "in 2 hours", "now"; `now` is injectable for tests. */
  relativeTime: (value: DateInput, now?: number) => string
  plural: (count: number) => Intl.LDMLPluralRule
  /**
   * Compact "5m ago" / "3h ago" / "2d ago" for lists, then a short date after a
   * week. Returns null under 45 seconds so callers can show their own "just now".
   */
  ago: (value: DateInput, now?: number) => string | null
  /** "120ms", "1.5s", "5m 3s" in English; locale units elsewhere. */
  duration: (ms: number) => string
  /** "1.5 KB"; the unit symbols are kept, the number is localised. */
  bytes: (value: number) => string
  /** A 0..1 ratio, or an already-scaled percentage above 1, rounded to a whole percent. */
  percentValue: (value: number) => string
  /** "5 min" reading-time style minutes. */
  minutes: (value: number) => string
}

function toDate(value: DateInput): Date | null {
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['second', 60],
  ['minute', 60],
  ['hour', 24],
  ['day', 7],
  ['week', 4.345],
  ['month', 12],
  ['year', Number.POSITIVE_INFINITY],
]

/**
 * Narrow relative time reads "2d ago" in English, but French narrow is a bare
 * "-2 j" and German narrow a cryptic "vor 5 m"; those use the short style.
 */
const AGO_STYLE: Record<string, Intl.RelativeTimeFormatStyle> = { fr: 'short', de: 'short' }

export function createFormatters(locale: string): LocaleFormatters {
  const numbers = new Intl.NumberFormat(locale)
  const plurals = new Intl.PluralRules(locale)
  const relative = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const times = new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' })
  const dateTimes = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' })

  return {
    locale,
    number: (value, options) =>
      options ? new Intl.NumberFormat(locale, options).format(value) : numbers.format(value),
    percent: (ratio, maximumFractionDigits = 0) =>
      new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits }).format(ratio),
    date: (value, options = { year: 'numeric', month: 'short', day: 'numeric' }) => {
      const date = toDate(value)
      return date ? new Intl.DateTimeFormat(locale, options).format(date) : ''
    },
    time: (value) => {
      const date = toDate(value)
      return date ? times.format(date) : ''
    },
    dateTime: (value) => {
      const date = toDate(value)
      return date ? dateTimes.format(date) : ''
    },
    relativeTime: (value, now = Date.now()) => {
      const date = toDate(value)
      if (!date) return ''
      let amount = (date.getTime() - now) / 1000
      for (const [unit, size] of RELATIVE_UNITS) {
        if (Math.abs(amount) < size) return relative.format(Math.round(amount), unit)
        amount /= size
      }
      return ''
    },
    plural: (count) => plurals.select(count),
    ago: (value, now = Date.now()) => {
      const date = toDate(value)
      if (!date) return ''
      const diff = now - date.getTime()
      if (diff < 45_000) return null
      // The phrase follows the language ("2d ago"); regional data such as en-IN
      // would spell it out ("2 days ago") and change the compact list layout.
      const language = locale.split('-')[0]
      const compact = new Intl.RelativeTimeFormat(language, { style: AGO_STYLE[language] ?? 'narrow' })
      const minutes = Math.round(diff / 60_000)
      if (minutes < 60) return compact.format(-minutes, 'minute')
      const hours = Math.round(minutes / 60)
      if (hours < 24) return compact.format(-hours, 'hour')
      const days = Math.round(hours / 24)
      if (days < 7) return compact.format(-days, 'day')
      return new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(date)
    },
    duration: (ms) => {
      if (!Number.isFinite(ms) || ms < 0) return '—'
      const unit = (value: number, name: string, fraction = 0) =>
        new Intl.NumberFormat(locale, {
          style: 'unit',
          unit: name,
          unitDisplay: 'narrow',
          minimumFractionDigits: fraction,
          maximumFractionDigits: fraction,
        }).format(value)
      if (ms < 1000) return unit(Math.round(ms), 'millisecond')
      if (ms < 60_000) return unit(ms / 1000, 'second', 1)
      const minutes = Math.floor(ms / 60_000)
      const seconds = Math.round((ms % 60_000) / 1000)
      return `${unit(minutes, 'minute')} ${unit(seconds, 'second')}`
    },
    bytes: (value) => {
      if (!Number.isFinite(value) || value < 0) return '—'
      const oneDecimal = (n: number) =>
        new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(n)
      if (value < 1024) return `${numbers.format(value)} B`
      if (value < 1024 * 1024) return `${oneDecimal(value / 1024)} KB`
      return `${oneDecimal(value / (1024 * 1024))} MB`
    },
    percentValue: (value) => {
      if (!Number.isFinite(value)) return '—'
      const ratio = value <= 1 ? value : value / 100
      return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(ratio)
    },
    minutes: (value) =>
      new Intl.NumberFormat(locale, { style: 'unit', unit: 'minute', unitDisplay: 'short' }).format(value),
  }
}
