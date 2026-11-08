import { useState } from "react"
import { motion, useReducedMotionConfig } from "motion/react"
import { Badge } from "@/components/ui/badge"
import type { SubtitleStatus } from "@/components/SubtitleCard"
import { InputPage } from "./InputPage"
import { SubtitlesPage } from "./SubtitlesPage"
import { WindowPage, defaultWindowSettings } from "./WindowPage"
import type { SubtitleAppearance } from "./subtitleAppearance"
import "./settings.css"

const pages = [
  { id: "input", title: "Input", description: "选择音频来源，查看模型状态并控制字幕会话。" },
  { id: "subtitles", title: "Subtitles", description: "字幕显示与可读性。" },
  { id: "window", title: "Window", description: "窗口参数、快捷键与字幕保存的模拟配置。" },
  { id: "diagnostics", title: "Diagnostics", description: "运行信息与诊断。" },
] as const

function NavigationIcon({ page }: { page: typeof pages[number]["id"] }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {page === "input" && <><rect x="9" y="3" width="6" height="12" rx="3" /><path d="M6 11v1a6 6 0 0 0 12 0v-1M12 18v3m-3 0h6" /></>}
      {page === "subtitles" && <><rect x="3" y="5" width="18" height="14" rx="3" /><path d="M6 11h5m3 0h4M6 15h3m3 0h6" /></>}
      {page === "window" && <><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M3 9h18M7 6.5h.01m3 0h.01" /></>}
      {page === "diagnostics" && <><path d="M4 16V8m5 10V6m5 15V3m5 13V8" /></>}
    </svg>
  )
}

export interface SettingsWindowProps {
  status: SubtitleStatus
  onToggleSession: () => void
  subtitleAppearance: SubtitleAppearance
  onSubtitleAppearanceChange: (appearance: SubtitleAppearance) => void
}

/** Shared settings view. The entry/preview supplies the existing mock session. */
export function SettingsWindow({ status, onToggleSession, subtitleAppearance, onSubtitleAppearanceChange }: SettingsWindowProps) {
  const [pageId, setPageId] = useState<typeof pages[number]["id"]>("input")
  const [microphone, setMicrophone] = useState("default")
  const [deviceFeedback, setDeviceFeedback] = useState("")
  const [windowSettings, setWindowSettings] = useState(defaultWindowSettings)
  const reducedMotion = useReducedMotionConfig()
  const page = pages.find((item) => item.id === pageId)!

  return (
    <section className="settings-window" aria-label="字幕设置" data-session-status={status}>
      <header className="settings-titlebar">
        <span className="settings-appmark" aria-hidden="true">字</span>
        <strong>实时字幕</strong><span className="settings-title-divider" /><span>设置</span>
        <Badge className="settings-mode-badge">模拟</Badge>
      </header>
      <div className="settings-body">
        <aside className="settings-sidebar">
          <nav aria-label="设置导航">
            {pages.map((item) => (
              <button type="button" key={item.id} aria-current={pageId === item.id ? "page" : undefined} onClick={() => setPageId(item.id)}>
                <NavigationIcon page={item.id} /><span>{item.title}</span>
              </button>
            ))}
          </nav>
          <p className="settings-sidebar-note">本地演示<span>麦克风未启用</span></p>
        </aside>
        <div className="settings-content">
          <motion.div key={pageId} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reducedMotion ? 0 : 0.12 }}>
            <header className="settings-page-heading">
              <h1>{page.title}</h1><p>{page.description}</p>
            </header>
            {pageId === "input" ? (
              <InputPage status={status} onToggleSession={onToggleSession} microphone={microphone} onMicrophoneChange={(value) => { setMicrophone(value); setDeviceFeedback("已切换模拟输入设备") }} deviceFeedback={deviceFeedback} onRefresh={() => setDeviceFeedback("已刷新：3 个模拟设备")} />
            ) : pageId === "subtitles" ? (
              <SubtitlesPage appearance={subtitleAppearance} onChange={onSubtitleAppearanceChange} />
            ) : pageId === "window" ? (
              <WindowPage settings={windowSettings} onChange={setWindowSettings} />
            ) : (
              <div className="settings-placeholder">
                <NavigationIcon page={pageId} />
                <h2>此页面尚未实现</h2>
                <p>此演示暂未提供该页面的设置项。</p>
              </div>
            )}
          </motion.div>
        </div>
      </div>
    </section>
  )
}
