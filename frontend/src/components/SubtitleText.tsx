import { useLayoutEffect, useRef, useState } from "react"
import { animate, useReducedMotionConfig } from "motion/react"
import { MarqueeLine } from "./MarqueeLine"

interface SubtitleTextProps {
  chineseText: string
  russianText: string
  showRussian?: boolean
}

/** One DOM pair, replaced after fade-out; superseded updates never commit. */
export function SubtitleText({ chineseText, russianText, showRussian = true }: SubtitleTextProps) {
  const [displayed, setDisplayed] = useState({ chineseText, russianText })
  const displayedRef = useRef(displayed)
  const containerRef = useRef<HTMLDivElement>(null)
  const reducedMotion = Boolean(useReducedMotionConfig())

  useLayoutEffect(() => {
    const element = containerRef.current
    if (!element) return
    let cancelled = false
    const unchanged = displayedRef.current.chineseText === chineseText && displayedRef.current.russianText === russianText
    if (unchanged || reducedMotion) {
      if (!unchanged) setDisplayed({ chineseText, russianText })
      const reset = animate(element, { opacity: 1 }, { duration: 0 })
      return () => reset.stop()
    }
    const exit = animate(element, { opacity: 0 }, { duration: 0.06, ease: "easeOut" })
    exit.then(() => {
      if (!cancelled) setDisplayed({ chineseText, russianText })
    })
    return () => { cancelled = true; exit.stop() }
  }, [chineseText, russianText, reducedMotion])

  useLayoutEffect(() => {
    displayedRef.current = displayed
    const element = containerRef.current
    if (!element) return
    const enter = animate(element, { opacity: 1 }, { duration: reducedMotion ? 0 : 0.1, ease: "easeOut" })
    return () => enter.stop()
  }, [displayed, reducedMotion])

  return (
    <div ref={containerRef} className="subtitle-content">
      <MarqueeLine text={displayed.chineseText} language="zh-CN" className="subtitle-chinese" />
      {showRussian && <MarqueeLine text={displayed.russianText} language="ru" className="subtitle-russian" />}
    </div>
  )
}
