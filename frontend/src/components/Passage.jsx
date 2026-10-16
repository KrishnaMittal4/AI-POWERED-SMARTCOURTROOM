import { useMemo } from 'react'
import { highlightPassage, queryKeywords, splitKeywords } from '../lib/utils.js'

// Shows a retrieved passage. Query words are marked, and the sentence closest
// to the generated answer is outlined, so a reader can check the answer fast.
export default function Passage({ text, query, answer }) {
  const keywords = useMemo(() => queryKeywords(query), [query])
  const cleaned = useMemo(() => (text || '')
    .replace(/^(?:[A-H]\s+){5,}[A-H]\s+/i, '')
    .replace(/\s+/g, ' ')
    .trim(), [text])
  const sentences = useMemo(() => highlightPassage(cleaned, answer), [cleaned, answer])
  if (!text) return null
  return (
    <blockquote className="passage">
      {sentences.map((s, i) => (
        <span key={i} className={s.best ? 'best' : undefined}>
          {splitKeywords(s.text, keywords).map((p, j) => (p.hit ? <mark key={j}>{p.text}</mark> : <span key={j}>{p.text}</span>))}{' '}
        </span>
      ))}
    </blockquote>
  )
}
