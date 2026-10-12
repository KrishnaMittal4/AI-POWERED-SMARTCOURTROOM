import { useEffect, useRef } from 'react'

/**
 * ParticleBackground - High-performance interactive gaming canvas background.
 * Renders glowing ambient stardust & cyber constellation lines that react to cursor movement and clicks.
 */
export default function ParticleBackground({ theme = 'dark' }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let animationFrameId
    let isVisible = true

    // Size canvas to viewport
    let width = (canvas.width = window.innerWidth)
    let height = (canvas.height = window.innerHeight)

    const handleResize = () => {
      if (!canvas) return
      width = canvas.width = window.innerWidth
      height = canvas.height = window.innerHeight
    }
    window.addEventListener('resize', handleResize)

    // Cursor tracking
    const mouse = {
      x: -1000,
      y: -1000,
      radius: 140,
    }

    const handleMouseMove = (e) => {
      mouse.x = e.clientX
      mouse.y = e.clientY
    }

    const handleMouseLeave = () => {
      mouse.x = -1000
      mouse.y = -1000
    }

    // Spark burst on click
    const handleMouseClick = (e) => {
      const clickX = e.clientX
      const clickY = e.clientY
      for (let i = 0; i < 8; i++) {
        const angle = Math.random() * Math.PI * 2
        const speed = 1.5 + Math.random() * 3
        sparks.push({
          x: clickX,
          y: clickY,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          radius: 1.5 + Math.random() * 2,
          alpha: 1,
          decay: 0.02 + Math.random() * 0.03,
          color: Math.random() > 0.3 ? '212, 160, 23' : '6, 182, 212', // Gold or Cyber Cyan
        })
      }
    }

    window.addEventListener('mousemove', handleMouseMove, { passive: true })
    window.addEventListener('mouseleave', handleMouseLeave)
    window.addEventListener('click', handleMouseClick, { passive: true })

    // Particle Setup
    const isDark = theme === 'dark'
    const particleCount = Math.min(65, Math.floor((width * height) / 18000))
    const particles = []
    const sparks = []

    const colorPalette = isDark
      ? ['212, 160, 23', '232, 197, 58', '6, 182, 212', '168, 85, 247']
      : ['184, 134, 11', '160, 110, 20', '30, 120, 180']

    for (let i = 0; i < particleCount; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.45,
        vy: (Math.random() - 0.5) * 0.45,
        radius: Math.random() * 1.8 + 0.8,
        baseAlpha: Math.random() * 0.4 + 0.2,
        pulseSpeed: 0.01 + Math.random() * 0.02,
        pulseOffset: Math.random() * Math.PI * 2,
        color: colorPalette[Math.floor(Math.random() * colorPalette.length)],
      })
    }

    let tick = 0

    const render = () => {
      if (!isVisible) {
        animationFrameId = requestAnimationFrame(render)
        return
      }

      ctx.clearRect(0, 0, width, height)
      tick += 1

      // Render & update sparks from clicks
      for (let i = sparks.length - 1; i >= 0; i--) {
        const s = sparks[i]
        s.x += s.vx
        s.y += s.vy
        s.alpha -= s.decay
        if (s.alpha <= 0) {
          sparks.splice(i, 1)
          continue
        }
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${s.color}, ${s.alpha})`
        ctx.shadowBlur = 8
        ctx.shadowColor = `rgba(${s.color}, 0.8)`
        ctx.fill()
        ctx.shadowBlur = 0
      }

      // Update & render particles
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i]

        // Ambient movement
        p.x += p.vx
        p.y += p.vy

        // Screen wrap
        if (p.x < 0) p.x = width
        else if (p.x > width) p.x = 0
        if (p.y < 0) p.y = height
        else if (p.y > height) p.y = 0

        // Cursor interaction (repulsion)
        const dx = p.x - mouse.x
        const dy = p.y - mouse.y
        const dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < mouse.radius && dist > 0) {
          const force = (1 - dist / mouse.radius) * 1.8
          p.x += (dx / dist) * force
          p.y += (dy / dist) * force
        }

        // Pulsing glow
        const pulse = Math.sin(tick * p.pulseSpeed + p.pulseOffset) * 0.15
        const alpha = Math.max(0.1, Math.min(1, p.baseAlpha + pulse))

        // Draw particle
        ctx.beginPath()
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(${p.color}, ${alpha})`
        ctx.fill()

        // Constellation lines to neighboring particles
        for (let j = i + 1; j < particles.length; j++) {
          const p2 = particles[j]
          const ldx = p.x - p2.x
          const ldy = p.y - p2.y
          const lineDist = Math.sqrt(ldx * ldx + ldy * ldy)

          if (lineDist < 95) {
            const lineAlpha = (1 - lineDist / 95) * (isDark ? 0.12 : 0.08)
            ctx.beginPath()
            ctx.moveTo(p.x, p.y)
            ctx.lineTo(p2.x, p2.y)
            ctx.strokeStyle = `rgba(${p.color}, ${lineAlpha})`
            ctx.lineWidth = 0.75
            ctx.stroke()
          }
        }
      }

      animationFrameId = requestAnimationFrame(render)
    }

    const handleVisibilityChange = () => {
      isVisible = !document.hidden
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    animationFrameId = requestAnimationFrame(render)

    return () => {
      cancelAnimationFrame(animationFrameId)
      window.removeEventListener('resize', handleResize)
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseleave', handleMouseLeave)
      window.removeEventListener('click', handleMouseClick)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [theme])

  return (
    <canvas
      ref={canvasRef}
      className="particle-background-canvas"
      aria-hidden="true"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        pointerEvents: 'none',
        zIndex: 0,
      }}
    />
  )
}
