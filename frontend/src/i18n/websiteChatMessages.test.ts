import { describe, expect, it } from 'vitest'
import de from './messages/de'
import { en } from './messages/en'
import es from './messages/es'
import fr from './messages/fr'
import hi from './messages/hi'
import ml from './messages/ml'

type Tree = { [key: string]: string | Tree }

function flatten(tree: Tree, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') out[path] = value
    else Object.assign(out, flatten(value, path))
  }
  return out
}

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort()

describe('Website Chat dictionaries', () => {
  const english = flatten(en.websiteChat as unknown as Tree)
  const dictionaries = { ml, hi, es, fr, de } as Record<string, { websiteChat?: unknown; nav?: { websiteChat?: string } }>

  it.each(Object.keys(dictionaries))('%s has every Website Chat key with the same placeholders', (code) => {
    const translated = flatten(dictionaries[code].websiteChat as Tree)
    expect(Object.keys(translated).sort()).toEqual(Object.keys(english).sort())
    for (const [key, text] of Object.entries(translated)) {
      expect(placeholders(text), `${code}:${key}`).toEqual(placeholders(english[key]))
      expect(text.trim(), `${code}:${key}`).not.toBe('')
    }
    expect(dictionaries[code].nav?.websiteChat).toBeTruthy()
  })

  it('translates every backend error code', () => {
    const codes = Object.keys(english).filter((key) => key.startsWith('errors.'))
    expect(codes.length).toBeGreaterThanOrEqual(29)
  })
})
