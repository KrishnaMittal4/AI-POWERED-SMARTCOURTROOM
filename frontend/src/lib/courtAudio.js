/**
 * Courtroom Audio & Voice Synthesis Utility
 * - Procedural Double Gavel Strike via Web Audio API (realistic resonant wooden acoustics)
 * - Text-to-Speech playback for Legal Advice in English & Hindi via Web Speech API
 */

let audioCtx = null

function getAudioContext() {
  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext
    if (AudioContextClass) {
      audioCtx = new AudioContextClass()
    }
  }
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume()
  }
  return audioCtx
}

/**
 * Procedural double gavel sound: Strike 1 + Strike 2 with wooden body resonance
 */
export function playGavelStrike() {
  try {
    const ctx = getAudioContext()
    if (!ctx) return

    const now = ctx.currentTime

    const singleStrike = (startTime, gainMult = 1.0) => {
      // 1. Initial sharp impact click
      const clickOsc = ctx.createOscillator()
      const clickGain = ctx.createGain()
      clickOsc.type = "triangle"
      clickOsc.frequency.setValueAtTime(340, startTime)
      clickOsc.frequency.exponentialRampToValueAtTime(80, startTime + 0.04)
      clickGain.gain.setValueAtTime(0.8 * gainMult, startTime)
      clickGain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.05)
      clickOsc.connect(clickGain)
      clickGain.connect(ctx.destination)
      clickOsc.start(startTime)
      clickOsc.stop(startTime + 0.06)

      // 2. Heavy wooden desk resonance (low body)
      const woodOsc = ctx.createOscillator()
      const woodGain = ctx.createGain()
      woodOsc.type = "sine"
      woodOsc.frequency.setValueAtTime(130, startTime)
      woodOsc.frequency.exponentialRampToValueAtTime(45, startTime + 0.22)
      woodGain.gain.setValueAtTime(0.9 * gainMult, startTime)
      woodGain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.25)
      woodOsc.connect(woodGain)
      woodGain.connect(ctx.destination)
      woodOsc.start(startTime)
      woodOsc.stop(startTime + 0.26)

      // 3. High wooden harmonic overtone
      const toneOsc = ctx.createOscillator()
      const toneGain = ctx.createGain()
      toneOsc.type = "sine"
      toneOsc.frequency.setValueAtTime(520, startTime)
      toneOsc.frequency.exponentialRampToValueAtTime(220, startTime + 0.12)
      toneGain.gain.setValueAtTime(0.3 * gainMult, startTime)
      toneGain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.14)
      toneOsc.connect(toneGain)
      toneGain.connect(ctx.destination)
      toneOsc.start(startTime)
      toneOsc.stop(startTime + 0.15)
    }

    // Double gavel strike: first strike at T=0, second sharper strike at T+0.28s
    singleStrike(now, 0.85)
    singleStrike(now + 0.28, 1.0)
  } catch (err) {
    console.warn("Could not play gavel strike:", err)
  }
}

/**
 * Text-to-Speech reader for legal advice
 */
export function speakLegalAdvice(text, lang = "en", { onStart, onEnd, onError } = {}) {
  if (!("speechSynthesis" in window)) {
    alert("Text-to-speech is not supported by your browser.")
    return false
  }

  // Cancel any active speech
  window.speechSynthesis.cancel()

  const cleanText = text
    .replace(/[#*`_~]/g, "")
    .replace(/\s+/g, " ")
    .trim()

  if (!cleanText) return false

  const utter = new SpeechSynthesisUtterance(cleanText)
  utter.rate = 0.95
  utter.pitch = 1.0

  if (lang === "hi") {
    utter.lang = "hi-IN"
  } else {
    utter.lang = "en-IN"
  }

  // Pick appropriate Indian voice if available
  const voices = window.speechSynthesis.getVoices()
  const matchingVoice = voices.find(v =>
    lang === "hi"
      ? v.lang.startsWith("hi")
      : v.lang.includes("en-IN") || v.name.toLowerCase().includes("india")
  )
  if (matchingVoice) utter.voice = matchingVoice

  if (onStart) utter.onstart = onStart
  if (onEnd) utter.onend = onEnd
  if (onError) utter.onerror = onError

  window.speechSynthesis.speak(utter)
  return true
}

export function stopSpeaking() {
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel()
  }
}

export function isSpeaking() {
  return "speechSynthesis" in window && window.speechSynthesis.speaking
}
