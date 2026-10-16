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

describe('Workspace V2 dictionaries', () => {
  const namespaces = ['documentChat', 'collections', 'runTimeline'] as const
  const dictionaries = { ml, hi, es, fr, de } as Record<string, Record<string, unknown>>

  it.each(Object.keys(dictionaries))('%s mirrors every V2 key with the same placeholders', (code) => {
    for (const namespace of namespaces) {
      const english = flatten(en[namespace] as unknown as Tree)
      const translated = flatten(dictionaries[code][namespace] as Tree)
      expect(Object.keys(translated).sort(), `${code}:${namespace}`).toEqual(Object.keys(english).sort())
      for (const [key, text] of Object.entries(translated)) {
        expect(placeholders(text), `${code}:${namespace}.${key}`).toEqual(placeholders(english[key]))
        expect(text.trim(), `${code}:${namespace}.${key}`).not.toBe('')
      }
    }
    expect((dictionaries[code].nav as Record<string, string>).collections).toBeTruthy()
  })
})
