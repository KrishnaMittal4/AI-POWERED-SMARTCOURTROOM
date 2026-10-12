import React, { useState, useEffect, useRef } from 'react'

export default function VoiceInput({ onTranscript, disabled = false, className = '' }) {
  const [supported, setSupported] = useState(false)
  const [listening, setListening] = useState(false)
  const [lang, setLang] = useState('en-IN') // 'en-IN' or 'hi-IN'
  const [statusText, setStatusText] = useState('')
  const recognitionRef = useRef(null)

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (SpeechRecognition) {
      setSupported(true)
      const recognition = new SpeechRecognition()
      recognition.continuous = true
      recognition.interimResults = true
      recognition.lang = lang

      recognition.onstart = () => {
        setListening(true)
        setStatusText(lang === 'hi-IN' ? 'सुन रहा हूँ... बोलिए' : 'Listening... Speak now')
      }

      recognition.onresult = (event) => {
        let finalTranscript = ''
        let interimTranscript = ''

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const item = event.results[i]
          if (item.isFinal) {
            finalTranscript += item[0].transcript
          } else {
            interimTranscript += item[0].transcript
          }
        }

        const transcript = (finalTranscript || interimTranscript).trim()
        if (transcript) {
          onTranscript(transcript, Boolean(finalTranscript))
        }
      }

      recognition.onerror = (event) => {
        if (event.error === 'not-allowed') {
          setStatusText('Microphone permission blocked')
        } else if (event.error === 'no-speech') {
          // keep waiting
        } else {
          setStatusText(`Mic error: ${event.error}`)
        }
        setListening(false)
      }

      recognition.onend = () => {
        setListening(false)
        setStatusText('')
      }

      recognitionRef.current = recognition
    } else {
      setSupported(false)
    }

    return () => {
      if (recognitionRef.current) {
        try { recognitionRef.current.abort() } catch (_) {}
      }
    }
  }, [lang, onTranscript])

  const toggleListen = () => {
    if (!recognitionRef.current) return

    if (listening) {
      recognitionRef.current.stop()
      setListening(false)
      setStatusText('')
    } else {
      try {
        recognitionRef.current.lang = lang
        recognitionRef.current.start()
      } catch (err) {
        console.warn('Speech recognition error:', err)
      }
    }
  }

  if (!supported) return null

  return (
    <div className={`voice-input-container ${className}`}>
      {listening && (
        <div className="voice-listening-indicator" title="Microphone active">
          <span className="voice-pulse-ring" />
          <span className="voice-wave-bar bar-1" />
          <span className="voice-wave-bar bar-2" />
          <span className="voice-wave-bar bar-3" />
          <span className="voice-wave-bar bar-4" />
          <span className="voice-status-text">{statusText}</span>
        </div>
      )}

      {/* Language Selector Pill */}
      <div className="voice-lang-selector" title="Select speech recognition language">
        <button
          type="button"
          className={`voice-lang-pill ${lang === 'en-IN' ? 'active' : ''}`}
          onClick={() => {
            if (listening) recognitionRef.current?.stop()
            setLang('en-IN')
          }}
          disabled={disabled}
        >
          EN
        </button>
        <button
          type="button"
          className={`voice-lang-pill ${lang === 'hi-IN' ? 'active' : ''}`}
          onClick={() => {
            if (listening) recognitionRef.current?.stop()
            setLang('hi-IN')
          }}
          disabled={disabled}
        >
          हिन्दी
        </button>
      </div>

      {/* Mic Button */}
      <button
        type="button"
        className={`voice-mic-btn ${listening ? 'listening' : ''}`}
        onClick={toggleListen}
        disabled={disabled}
        title={listening ? 'Stop recording voice' : `Speak in ${lang === 'hi-IN' ? 'Hindi' : 'English / Hinglish'}`}
        aria-label="Voice input speech to text"
      >
        {listening ? (
          <span className="mic-icon-active">🔴</span>
        ) : (
          <span className="mic-icon-idle">🎙️</span>
        )}
      </button>
    </div>
  )
}
