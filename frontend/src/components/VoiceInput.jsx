import React, { useEffect, useRef, useState } from 'react'

export default function VoiceInput({ value = '', onTranscript, disabled = false, className = '' }) {
  const [supported, setSupported] = useState(true)
  const [listening, setListening] = useState(false)
  const [lang, setLang] = useState('en-IN')
  const [statusText, setStatusText] = useState('')
  const recognitionRef = useRef(null)
  const baseRef = useRef('')
  const finalRef = useRef('')
  const callbackRef = useRef(onTranscript)
  callbackRef.current = onTranscript

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) { setSupported(false); return }
    setSupported(true)
    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.maxAlternatives = 1
    recognition.lang = lang

    recognition.onstart = () => { setListening(true); setStatusText(lang === 'hi-IN' ? 'सुन रहा है…' : 'Listening…') }
    recognition.onresult = (event) => {
      let interim = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const text = event.results[i][0]?.transcript || ''
        if (event.results[i].isFinal) finalRef.current += `${text} `
        else interim += text
      }
      const dictated = `${finalRef.current}${interim}`.trim()
      const combined = [baseRef.current.trim(), dictated].filter(Boolean).join(' ')
      callbackRef.current?.(combined, !interim)
    }
    recognition.onerror = (event) => {
      const messages = { 'not-allowed':'Microphone permission blocked', 'audio-capture':'No microphone detected', 'network':'Speech service unavailable', 'no-speech':'No speech detected' }
      setStatusText(messages[event.error] || `Microphone error: ${event.error}`)
      if (event.error !== 'no-speech') setListening(false)
    }
    recognition.onend = () => setListening(false)
    recognitionRef.current = recognition
    return () => { try { recognition.abort() } catch {} }
  }, [lang])

  function toggleListen() {
    const r = recognitionRef.current
    if (!r) return
    if (listening) { r.stop(); return }
    baseRef.current = value || ''
    finalRef.current = ''
    setStatusText('')
    try { r.lang = lang; r.start() } catch { setStatusText('Microphone is already starting. Try again.') }
  }

  function switchLanguage(next) {
    if (listening) { try { recognitionRef.current?.stop() } catch {} }
    setLang(next); setStatusText('')
  }

  return (
    <div className={`voice-input-container ${className}`}>
      <div className="voice-lang-selector" title="Speech language">
        <button type="button" className={`voice-lang-pill ${lang === 'en-IN' ? 'active' : ''}`} onClick={() => switchLanguage('en-IN')} disabled={disabled}>EN</button>
        <button type="button" className={`voice-lang-pill ${lang === 'hi-IN' ? 'active' : ''}`} onClick={() => switchLanguage('hi-IN')} disabled={disabled}>हिन्दी</button>
      </div>
      <button type="button" className={`voice-mic-btn ${listening ? 'listening' : ''}`} onClick={toggleListen} disabled={disabled || !supported} title={!supported ? 'Browser speech recognition is not supported. Use Chrome or Edge.' : listening ? 'Stop dictation' : `Dictate in ${lang === 'hi-IN' ? 'Hindi' : 'English'}`} aria-label="Voice input">
        {listening ? '■' : '🎙️'}
      </button>
      {(listening || statusText || !supported) && <span className={`voice-inline-status ${!supported ? 'error' : ''}`}>{!supported ? 'Voice input requires Chrome/Edge' : statusText}</span>}
    </div>
  )
}
