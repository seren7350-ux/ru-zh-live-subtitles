import { useLayoutEffect, useRef, useState } from "react"
import { animate, useReducedMotion } from "motion/react"

interface MarqueeLineProps {
  text: string
  language: string
  className: string
}

const PIXELS_PER_SECOND = 28
const END_PAUSE_SECONDS = 1.5

export function MarqueeLine({ text, language, className }: MarqueeLineProps) {
  const viewportRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLSpanElement>(null)
  const [overflowing, setOverflowing] = useState(false)
  const reducedMotion = useReducedMotion()

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    const content = textRef.current
    if (!viewport || !content) return

    let lastDistance = -1
    let stopAnimation: (() => void) | undefined
    const measure = () => {
      const distance = Math.max(0, Math.ceil(content.getBoundingClientRect().width - viewport.clientWidth))
      if (distance === lastDistance) return
      lastDistance = distance
      stopAnimation?.()
      // Reset Motion's cached x as well as the DOM; direct style writes alone
      // can be overwritten by the previous animation on the next frame.
      const reset = animate(content, { x: 0 }, { duration: 0 })
      stopAnimation = () => reset.stop()
      viewport.scrollLeft = 0
      setOverflowing(distance > 0)
      if (distance === 0 || reducedMotion) return

      const travel = distance / PIXELS_PER_SECOND
      const duration = 2 * (END_PAUSE_SECONDS + travel)
      const controls = animate(content, { x: [0, 0, -distance, -distance, 0] }, {
        duration,
        times: [0, END_PAUSE_SECONDS / duration, 0.5, (duration - travel) / duration, 1],
        ease: "linear",
        repeat: Infinity,
      })
      stopAnimation = () => controls.stop()
    }

    // Observing both boxes also catches font loading; no polling for fitting text.
    const observer = new ResizeObserver(measure)
    observer.observe(viewport)
    observer.observe(content)
    measure()
    return () => {
      observer.disconnect()
      stopAnimation?.()
    }
  }, [text, reducedMotion])

  return (
    <div
      ref={viewportRef}
      className={`subtitle-line ${className}`}
      lang={language}
      title={text}
      data-overflow={overflowing}
      data-reduced-motion={Boolean(reducedMotion)}
      tabIndex={overflowing ? 0 : undefined}
    >
      <span ref={textRef} className="subtitle-text">{text}</span>
    </div>
  )
}
