import { useState, useRef } from 'react'

/**
 * TiltCard - Renders an interactive 3D perspective tilt card with holographic glare reflection.
 * Used for citation cards, feature pills, hero suggestions, and interactive panels.
 */
export default function TiltCard({
  children,
  className = '',
  maxTilt = 8,
  glare = true,
  onClick,
  style = {},
  as: Component = 'div',
  ...rest
}) {
  const cardRef = useRef(null)
  const [transform, setTransform] = useState('')
  const [glareStyle, setGlareStyle] = useState({ opacity: 0 })
  const [isHovered, setIsHovered] = useState(false)

  const handleMouseMove = (e) => {
    if (!cardRef.current) return
    const rect = cardRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    const centerX = rect.width / 2
    const centerY = rect.height / 2

    const rotX = ((y - centerY) / centerY) * -maxTilt
    const rotY = ((x - centerX) / centerX) * maxTilt

    setTransform(`perspective(700px) rotateX(${rotX.toFixed(2)}deg) rotateY(${rotY.toFixed(2)}deg) translateZ(6px) scale3d(1.015, 1.015, 1.015)`)

    if (glare) {
      const glareX = (x / rect.width) * 100
      const glareY = (y / rect.height) * 100
      setGlareStyle({
        opacity: 0.8,
        background: `radial-gradient(circle at ${glareX}% ${glareY}%, rgba(255, 215, 0, 0.18) 0%, rgba(255, 255, 255, 0.05) 40%, transparent 80%)`,
      })
    }
  }

  const handleMouseEnter = () => {
    setIsHovered(true)
  }

  const handleMouseLeave = () => {
    setIsHovered(false)
    setTransform('perspective(700px) rotateX(0deg) rotateY(0deg) translateZ(0px) scale3d(1, 1, 1)')
    setGlareStyle({ opacity: 0 })
  }

  return (
    <Component
      ref={cardRef}
      className={`tilt-card-root ${isHovered ? 'tilt-active' : ''} ${className}`}
      onMouseMove={handleMouseMove}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={onClick}
      style={{
        transform,
        transformStyle: 'preserve-3d',
        transition: isHovered ? 'transform 0.08s ease-out' : 'transform 0.4s cubic-bezier(0.2, 0.8, 0.2, 1)',
        position: 'relative',
        willChange: 'transform',
        ...style,
      }}
      {...rest}
    >
      {children}
      {glare && (
        <div
          className="tilt-glare-overlay"
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: 'inherit',
            pointerEvents: 'none',
            zIndex: 10,
            transition: 'opacity 0.25s ease',
            ...glareStyle,
          }}
        />
      )}
    </Component>
  )
}
