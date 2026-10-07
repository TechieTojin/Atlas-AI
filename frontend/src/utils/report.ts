/** Pure helpers for presenting a markdown report: sectioning, reading time, title emphasis. */

export interface ReportSection {
  /** Stable DOM id for the table of contents. */
  id: string
  /** Heading text without markdown markers; empty for a leading untitled block. */
  title: string
  /** Heading level the author used (1 or 2); 0 for untitled preamble. */
  level: number
  /** Markdown body of the section, excluding its heading line. */
  body: string
}

const HEADING_PATTERN = /^(#{1,6})\s+(.*?)\s*#*\s*$/

export function slugify(text: string): string {
  const slug = text
    .toLowerCase()
    .replace(/\[[^\]]*\]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug || 'section'
}

/**
 * Splits markdown into top-level sections at the shallowest heading level the
 * document uses, so "# Title" documents and "## Title" documents both work.
 * Fenced code blocks are left intact.
 */
export function splitSections(markdown: string): ReportSection[] {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n')
  let inFence = false
  let shallowest = Infinity
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence
    if (inFence) continue
    const match = HEADING_PATTERN.exec(line)
    if (match) shallowest = Math.min(shallowest, match[1].length)
  }
  if (!Number.isFinite(shallowest)) {
    const body = markdown.trim()
    return body ? [{ id: 'report', title: '', level: 0, body }] : []
  }

  const sections: ReportSection[] = []
  const seen = new Map<string, number>()
  let current: ReportSection | null = null
  let preamble: string[] = []
  inFence = false

  const push = (section: ReportSection | null) => {
    if (!section) return
    section.body = section.body.trim()
    sections.push(section)
  }

  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence
    const match = inFence ? null : HEADING_PATTERN.exec(line)
    if (match && match[1].length === shallowest) {
      push(current)
      const title = match[2].trim()
      const base = slugify(title)
      const count = (seen.get(base) ?? 0) + 1
      seen.set(base, count)
      current = {
        id: count === 1 ? base : `${base}-${count}`,
        title,
        level: shallowest,
        body: '',
      }
      continue
    }
    if (current) current.body += `${line}\n`
    else preamble.push(line)
  }
  push(current)

  const intro = preamble.join('\n').trim()
  if (intro) sections.unshift({ id: 'introduction', title: '', level: 0, body: intro })
  return sections
}

const SUMMARY_TITLES = /^(executive\s+summary|summary|abstract|overview|key\s+takeaways?)$/i
const SOURCES_TITLES = /^(sources|references|bibliography|works\s+cited)$/i

export function isSummarySection(section: ReportSection): boolean {
  return SUMMARY_TITLES.test(section.title.trim())
}

export function isSourcesSection(section: ReportSection): boolean {
  return SOURCES_TITLES.test(section.title.trim())
}

/** Words per minute for an attentive technical reader. */
const READING_WPM = 220

export function wordCount(markdown: string): number {
  const text = markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#*_>`[\]()|-]+/g, ' ')
  return text.split(/\s+/).filter(Boolean).length
}

/** Estimated reading time in whole minutes (at least 1), or null for an empty report. */
export function readingMinutes(markdown: string): number | null {
  const words = wordCount(markdown)
  if (words === 0) return null
  return Math.max(1, Math.round(words / READING_WPM))
}

const STOPWORDS = new Set([
  'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'any', 'can', 'had', 'her', 'was',
  'one', 'our', 'out', 'has', 'have', 'been', 'from', 'that', 'this', 'with', 'what', 'which',
  'why', 'how', 'when', 'where', 'who', 'does', 'did', 'their', 'there', 'they', 'them', 'than',
  'then', 'into', 'over', 'under', 'about', 'most', 'more', 'some', 'such', 'very', 'will',
  'would', 'could', 'should', 'between', 'currently', 'previously', 'identified', 'biggest',
  'main', 'major', 'key', 'current', 'because', 'while', 'these', 'those', 'also', 'being',
])

export interface TitleSegment {
  text: string
  emphasised: boolean
}

/**
 * Chooses which words of the research question to emphasise: the content
 * words that the report's own section headings repeat. Nothing is emphasised
 * when the headings do not echo the question, so the title is never guessed.
 */
export function emphasiseTitle(title: string, headings: string[]): TitleSegment[] {
  const headingWords = new Set<string>()
  for (const heading of headings) {
    for (const word of heading.toLowerCase().match(/[a-z][a-z-]{3,}/g) ?? []) {
      headingWords.add(word)
      if (word.endsWith('s')) headingWords.add(word.slice(0, -1))
    }
  }
  const tokens = title.split(/(\s+)/)
  const segments: TitleSegment[] = []
  for (const token of tokens) {
    const bare = token.toLowerCase().replace(/[^a-z-]/g, '')
    const emphasised =
      bare.length >= 4 &&
      !STOPWORDS.has(bare) &&
      (headingWords.has(bare) || (bare.endsWith('s') && headingWords.has(bare.slice(0, -1))))
    const last = segments[segments.length - 1]
    if (last && last.emphasised === emphasised) last.text += token
    else if (/^\s+$/.test(token) && last) last.text += token
    else segments.push({ text: token, emphasised })
  }
  // Whitespace glued onto an emphasised run should not be highlighted when it
  // ends the run; trim trailing spaces out of emphasised segments.
  return segments.flatMap((segment) => {
    if (!segment.emphasised) return [segment]
    const match = /^(.*?)(\s+)$/s.exec(segment.text)
    if (!match) return [segment]
    return [
      { text: match[1], emphasised: true },
      { text: match[2], emphasised: false },
    ]
  })
}
