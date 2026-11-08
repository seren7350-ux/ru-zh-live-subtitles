import type { CSSProperties } from "react"
import { MarqueeLine } from "./MarqueeLine"

export interface SubtitleCardProps {
  chineseText: string
  russianText: string
  style?: CSSProperties
}

/** The subtitle surface itself: no preview canvas, fixtures, or session controls. */
export function SubtitleCard({ chineseText, russianText, style }: SubtitleCardProps) {
  return (
    <section className="subtitle-card" aria-label="双语字幕" style={style}>
      <span className="subtitle-dot" aria-hidden="true" />
      <MarqueeLine text={chineseText} language="zh-CN" className="subtitle-chinese" />
      <MarqueeLine text={russianText} language="ru" className="subtitle-russian" />
    </section>
  )
}
