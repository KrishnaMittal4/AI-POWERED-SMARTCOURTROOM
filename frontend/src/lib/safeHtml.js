import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ breaks: true, gfm: true })

// Every link in rendered answers opens in a new tab without giving the target
// page access to this one.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.getAttribute('href')) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

/**
 * Markdown -> sanitized HTML. The text comes from an LLM that has read PDFs and
 * user questions, so it must be treated as untrusted: without this, a crafted
 * passage or question could inject <script>/<img onerror> into the page and
 * read anything the page can (history in localStorage, the admin key in
 * sessionStorage). Citation buttons (class, data-index, data-kind, title) are
 * ordinary allowed attributes and survive.
 */
export function renderMarkdown(text) {
  return DOMPurify.sanitize(marked.parse(text || ''), {
    FORBID_TAGS: ['style', 'form', 'iframe', 'object', 'embed', 'link', 'meta'],
    FORBID_ATTR: ['style'],
  })
}
