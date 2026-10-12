import { useMemo } from 'react'
import { highlightPassage, queryKeywords, splitKeywords } from '../lib/utils.js'

// Shows a retrieved passage. Query words are marked, and the sentence closest
// to the generated answer is outlined, so a reader can check the answer fast.
export default function Passage({ text, query, answer }) {
  const keywords = useMemo(() => queryKeywords(query), [query])
  const sentences = useMemo(() => highlightPassage(text, answer), [text, answer])
  if (!text) return null
  return (
    <blockquote className="passage">
      {sentences.map((s, i) => (
        <span key={i} className={s.best ? 'best' : undefined}>
          {s.best && <span className="sr-only">Closest to the answer: </span>}
          {splitKeywords(s.text, keywords).map((p, j) => (p.hit ? <mark key={j}>{p.text}</mark> : <span key={j}>{p.text}</span>))}{' '}
        </span>
      ))}
    </blockquote>
  )
}
