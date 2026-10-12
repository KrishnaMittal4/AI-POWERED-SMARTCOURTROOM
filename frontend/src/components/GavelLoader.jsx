import { useState, useEffect } from 'react'

const LEGAL_PHASES = [
  { text: 'Interrogating Indian Case Law Vector Corpus…', code: 'VEC_SCAN' },
  { text: 'Extracting Ratio Decidendi & Binding Precedents…', code: 'RATIO_EXTRACT' },
  { text: 'Cross-Verifying Statutory Sections & Citations…', code: 'CIT_VALIDATE' },
  { text: 'Evaluating Supreme Court Precedent Hierarchy…', code: 'BENCH_ANALYSIS' },
  { text: 'Synthesizing Verified Legal Intelligence…', code: 'FINAL_SYNTH' },
]

export default function GavelLoader({ elapsed = 0, verify = true }) {
  const [phaseIndex, setPhaseIndex] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => {
      setPhaseIndex((prev) => (prev + 1) % LEGAL_PHASES.length)
    }, 2400)
    return () => clearInterval(timer)
  }, [])

  const currentPhase = LEGAL_PHASES[phaseIndex]

  return (
    <div className="gavel-loader-container" role="status" aria-live="polite">
      {/* Shockwave & Gavel Animation Stage */}
      <div className="gavel-stage">
        <div className="shockwave-ring ring-1" />
        <div className="shockwave-ring ring-2" />
        <div className="shockwave-ring ring-3" />
        <div className="impact-flash" />

        {/* Animated 3D Gavel */}
        <div className="gavel-arm">
          <svg
            className="gavel-svg"
            viewBox="0 0 120 120"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <linearGradient id="goldHead" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#f5d860" />
                <stop offset="50%" stopColor="#d4a017" />
                <stop offset="100%" stopColor="#8a6508" />
              </linearGradient>
              <linearGradient id="woodHandle" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#8a5a26" />
                <stop offset="50%" stopColor="#5c3a17" />
                <stop offset="100%" stopColor="#3d260f" />
              </linearGradient>
              <filter id="goldGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feDropShadow dx="0" dy="0" stdDeviation="4" floodColor="#f59e0b" floodOpacity="0.8" />
              </filter>
            </defs>

            {/* Handle */}
            <rect
              x="57"
              y="22"
              width="6"
              height="60"
              rx="3"
              fill="url(#woodHandle)"
              transform="rotate(-40 60 52)"
            />
            {/* Grip rings */}
            <circle cx="85" cy="80" r="4" fill="#f5d860" />

            {/* Gavel Head */}
            <g transform="rotate(-40 60 52)" filter="url(#goldGlow)">
              <rect x="42" y="16" width="36" height="16" rx="4" fill="url(#goldHead)" />
              <rect x="40" y="14" width="40" height="4" rx="2" fill="#f5d860" />
              <rect x="40" y="30" width="40" height="4" rx="2" fill="#8a6508" />
              <line x1="60" y1="16" x2="60" y2="32" stroke="#f5d860" strokeWidth="2" />
            </g>
          </svg>
        </div>

        {/* Sound Block / Anvil */}
        <div className="sound-block">
          <div className="sound-block-top" />
          <div className="sound-block-base" />
        </div>
      </div>

      {/* Futuristic HUD Info */}
      <div className="gavel-hud-meta">
        <div className="gavel-hud-badge">
          <span className="hud-pulse-dot" />
          <span className="hud-status-code">RAG_KERNEL: {currentPhase.code}</span>
          <span className="hud-timer">T+{elapsed}s</span>
        </div>

        <h3 className="gavel-phase-title">{currentPhase.text}</h3>

        <div className="gavel-equalizer">
          <span className="eq-bar bar-1" />
          <span className="eq-bar bar-2" />
          <span className="eq-bar bar-3" />
          <span className="eq-bar bar-4" />
          <span className="eq-bar bar-5" />
          <span className="eq-bar bar-6" />
          <span className="eq-bar bar-7" />
        </div>

        <p className="gavel-hud-sub">
          {verify ? '⚡ Dual-Model Citation Cross-Verification Active' : '⚡ Accelerated Passage Extraction'}
        </p>
      </div>
    </div>
  )
}
