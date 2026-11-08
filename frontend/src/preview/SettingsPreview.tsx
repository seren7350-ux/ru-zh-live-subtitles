import { SubtitleCard, subtitleStatuses, type SubtitleStatus } from "@/components/SubtitleCard"
import { SettingsWindow } from "@/settings/SettingsWindow"
import { getSubtitleSample } from "./subtitleSamples"
import "./settings-preview.css"

interface SettingsPreviewProps {
  status: SubtitleStatus
  onToggleSession: () => void
  onStatusChange: (status: SubtitleStatus) => void
}

/** Development-only pairing, never rendered inside the standalone settings view. */
export function SettingsPreview({ status, onToggleSession, onStatusChange }: SettingsPreviewProps) {
  return (
    <main className="settings-preview">
      <header className="settings-preview-header">
        <div><h1>设置与字幕联动</h1><p>开发场景 · 共享同一模拟会话</p></div>
        <div className="settings-preview-controls">
          <label>模拟状态<select value={status} onChange={(event) => onStatusChange(event.target.value as SubtitleStatus)}>{subtitleStatuses.map((item) => <option key={item}>{item}</option>)}</select></label>
          <a href="/settings.html">独立设置窗口</a><a href="/">字幕预览</a>
        </div>
      </header>
      <SettingsWindow status={status} onToggleSession={onToggleSession} />
      <section className="settings-linked-caption" aria-label="开发联动字幕">
        <p>独立字幕组件 · 开始 / 停止与上方 Input 页面双向联动</p>
        <SubtitleCard {...getSubtitleSample("short")} status={status} onToggleSession={onToggleSession} />
      </section>
    </main>
  )
}
