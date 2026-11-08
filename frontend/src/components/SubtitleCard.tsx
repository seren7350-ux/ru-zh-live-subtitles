import { useEffect, useId, useRef, useState, type CSSProperties } from "react"
import { useReducedMotionConfig } from "motion/react"
import { SubtitleText } from "./SubtitleText"

export const subtitleStatuses = ["Ready", "Loading", "Listening", "Stopping", "Error"] as const
export type SubtitleStatus = typeof subtitleStatuses[number]

const statusHints: Record<SubtitleStatus, string> = {
  Ready: "待开始", Loading: "准备中", Listening: "模拟监听", Stopping: "收尾中", Error: "模拟错误，可重试",
}

function ControlIcon({ name }: { name: "play" | "pause" | "pin" | "settings" | "more" }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {name === "play" && <path d="m8 5 11 7-11 7Z" />}
      {name === "pause" && <path d="M8 5v14M16 5v14" />}
      {name === "pin" && <path d="m16 3 5 5-4 1-3 5-4-4 5-3 1-4ZM10 14l-6 6" />}
      {name === "settings" && <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>}
      {name === "more" && <><circle cx="5" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="19" cy="12" r="1" fill="currentColor" /></>}
    </svg>
  )
}

export interface SubtitleCardProps {
  chineseText: string
  russianText: string
  status: SubtitleStatus
  onToggleSession: () => void
  backgroundOpacity?: number
  textOpacity?: number
  showRussian?: boolean
  textOutline?: boolean
  style?: CSSProperties
}

/** UI only: session state/actions are supplied by the caller (currently a mock). */
export function SubtitleCard({ chineseText, russianText, status, onToggleSession, backgroundOpacity = 45, textOpacity = 100, showRussian = true, textOutline = false, style }: SubtitleCardProps) {
  const [hovered, setHovered] = useState(false)
  const [keyboardFocus, setKeyboardFocus] = useState(false)
  const [toolbarEnabled, setToolbarEnabled] = useState(true)
  const [pinned, setPinned] = useState(false)
  const [notice, setNotice] = useState("")
  const leaveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const descriptionId = useId()
  const reducedMotion = Boolean(useReducedMotionConfig())
  const toolbarVisible = toolbarEnabled && (hovered || keyboardFocus)
  const active = status === "Listening" || status === "Loading"
  const actionLabel = status === "Stopping" ? "停止中" : status === "Loading" ? "取消" : active ? "停止" : "开始"
  const backgroundAlpha = Math.max(0, Math.min(100, backgroundOpacity)) / 100
  const textAlpha = Math.max(0, Math.min(100, textOpacity)) / 100

  useEffect(() => () => {
    clearTimeout(leaveTimer.current)
    clearTimeout(noticeTimer.current)
  }, [])

  function announce(message: string) {
    clearTimeout(noticeTimer.current)
    setNotice(message)
    noticeTimer.current = setTimeout(() => setNotice(""), 1800)
  }

  return (
    <section
      className="subtitle-card"
      aria-label="双语字幕"
      aria-describedby={descriptionId}
      aria-keyshortcuts="F2 Escape"
      tabIndex={0}
      style={{ ...style, "--subtitle-background-opacity": backgroundAlpha, "--subtitle-text-opacity": textAlpha } as CSSProperties}
      data-status={status}
      data-background-hidden={backgroundAlpha === 0}
      data-text-outline={textOutline}
      data-toolbar-enabled={toolbarEnabled}
      data-reduced-motion={reducedMotion}
      onPointerEnter={() => { clearTimeout(leaveTimer.current); setHovered(true) }}
      onPointerLeave={() => { leaveTimer.current = setTimeout(() => setHovered(false), 140) }}
      onPointerDown={() => setKeyboardFocus(false)}
      onFocus={(event) => setKeyboardFocus(event.target.matches(":focus-visible"))}
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setKeyboardFocus(false) }}
      onDoubleClick={(event) => {
        if ((event.target as Element).closest("button, a, input, select, textarea, .subtitle-line")) return
        if (window.getSelection()?.toString().trim()) return
        setToolbarEnabled((enabled) => !enabled)
      }}
      onKeyDown={(event) => {
        if (event.key === "Tab") setKeyboardFocus(true)
        if (event.key === "F2") {
          event.preventDefault()
          setKeyboardFocus(true)
          setToolbarEnabled((enabled) => !enabled)
        }
        if (event.key === "Escape") {
          event.preventDefault()
          setToolbarEnabled(false)
          setNotice("")
          event.currentTarget.focus({ preventScroll: true })
        }
      }}
    >
      <div className="subtitle-material" aria-hidden="true" />
      <div className="subtitle-chrome" aria-hidden="true" />
      <div className="subtitle-status" role="status" aria-live={status === "Error" ? "assertive" : "polite"}>
        <span className="subtitle-dot" aria-hidden="true" />
        <span className="subtitle-status-label">{status}</span>
        <span className="subtitle-feedback" title={notice || statusHints[status]}>{notice || statusHints[status]}</span>
      </div>
      <div className="subtitle-toolbar" role="toolbar" aria-label="字幕工具栏" data-visible={toolbarVisible} aria-hidden={!toolbarVisible} inert={!toolbarVisible}>
        <button type="button" className="subtitle-control subtitle-control-primary" onClick={onToggleSession} disabled={status === "Stopping"} aria-label={`${actionLabel}识别（模拟）`} title={`${actionLabel}识别（模拟）`}>
          <ControlIcon name={active ? "pause" : "play"} /><span>{actionLabel}</span>
        </button>
        <button type="button" className="subtitle-control" aria-label="置顶（模拟）" aria-pressed={pinned} title="置顶（模拟）" onClick={() => { setPinned(!pinned); announce(pinned ? "置顶关 · 模拟" : "置顶开 · 模拟") }}>
          <ControlIcon name="pin" />
        </button>
        <button type="button" className="subtitle-control" aria-label="设置（模拟）" title="设置（模拟）" onClick={() => announce("设置入口 · 模拟")}>
          <ControlIcon name="settings" />
        </button>
        <button type="button" className="subtitle-control" aria-label="更多操作（模拟）" title="更多操作（模拟）" onClick={() => announce("更多操作 · 模拟")}>
          <ControlIcon name="more" />
        </button>
      </div>
      {/* Appearance opacity and Motion's fade opacity intentionally use different elements. */}
      <div className="subtitle-appearance">
        <SubtitleText chineseText={chineseText} russianText={russianText} showRussian={showRussian} />
      </div>
      <p id={descriptionId} className="sr-only">悬停或聚焦可显示工具栏。双击卡片空白区域或按 F2 切换显示许可，Escape 收起。所有按钮均为模拟操作。</p>
    </section>
  )
}
