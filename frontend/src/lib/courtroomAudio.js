/**
 * Courtroom Audio Engine: Web Audio API Gavel + Multi-Agent Speech Synthesis
 * Provides immersive voice narration for Petitioner, Respondent, and Presiding Bench.
 */

export function cleanTextForSpeech(text) {
  if (!text) return ''
  return text
    // Remove markdown headers
    .replace(/^#+\s+/gm, '')
    // Remove bold/italics
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    // Remove markdown links
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    // Remove citation bracket numbers like [1], [2]
    .replace(/\[\d+\]/g, '')
    // Clean multiple linebreaks and symbols
    .replace(/[#>*~`]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Synthesizes an authentic double gavel strike using the browser's Web Audio API.
 * 100% offline, zero network requests, instant wooden resonance.
 */
export function playGavelSound() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return
    const ctx = new AudioCtx()
    const now = ctx.currentTime

    const strike = (t) => {
      // 1. Sharp wooden impact click (Transient)
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'triangle'
      osc.frequency.setValueAtTime(160, t)
      osc.frequency.exponentialRampToValueAtTime(40, t + 0.1)
      gain.gain.setValueAtTime(0.7, t)
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.18)
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start(t)
      osc.stop(t + 0.18)

      // 2. Heavy wooden desk resonance (Body)
      const bodyOsc = ctx.createOscillator()
      const bodyGain = ctx.createGain()
      bodyOsc.type = 'sine'
      bodyOsc.frequency.setValueAtTime(85, t)
      bodyOsc.frequency.exponentialRampToValueAtTime(30, t + 0.28)
      bodyGain.gain.setValueAtTime(0.5, t)
      bodyGain.gain.exponentialRampToValueAtTime(0.001, t + 0.28)
      bodyOsc.connect(bodyGain)
      bodyGain.connect(ctx.destination)
      bodyOsc.start(t)
      bodyOsc.stop(t + 0.28)
    }

    strike(now)
    strike(now + 0.26)
  } catch (err) {
    console.warn('Gavel audio synthesis failed:', err)
  }
}

/**
 * Returns distinct voice configurations for each courtroom persona.
 */
export function getPersonaVoiceConfig(role, voices = []) {
  const englishVoices = voices.filter((v) => v.lang && v.lang.startsWith('en'))
  const pool = englishVoices.length > 0 ? englishVoices : voices

  if (role === 'petitioner') {
    // Confident, persuasive counsel: slightly higher pitch, slightly brisk
    const preferred = pool.find((v) => /david|alex|daniel|male|george/i.test(v.name)) || pool[0]
    return {
      voice: preferred || null,
      pitch: 1.08,
      rate: 1.02,
    }
  }

  if (role === 'respondent') {
    // Sharp, measured defense counsel: distinct tone
    const preferred = pool.find((v) => /samantha|victoria|karen|female|zira/i.test(v.name)) || pool[1] || pool[0]
    return {
      voice: preferred || null,
      pitch: 0.96,
      rate: 0.98,
    }
  }

  // Presiding Bench (Chief Justice)
  // Deep, authoritative, deliberate cadence
  const benchPreferred = pool.find((v) => /rishi|mark|james|richard|google uk english male/i.test(v.name)) || pool[0]
  return {
    voice: benchPreferred || null,
    pitch: 0.84,
    rate: 0.92,
  }
}
