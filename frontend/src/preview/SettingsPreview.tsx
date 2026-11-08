import { useState, type CSSProperties } from "react"
import { SubtitleCard, subtitleStatuses, type SubtitleStatus } from "@/components/SubtitleCard"
import { SettingsWindow } from "@/settings/SettingsWindow"
import { defaultSubtitleAppearance } from "@/settings/subtitleAppearance"
import { getSubtitleSample, subtitleSamples } from "./subtitleSamples"
import "./settings-preview.css"

interface SettingsPreviewProps {
  status: SubtitleStatus
  onToggleSession: () => void
  onStatusChange: (status: SubtitleStatus) => void
}

/** Development-only pairing, never rendered inside the standalone settings view. */
export function SettingsPreview({ status, onToggleSession, onStatusChange }: SettingsPreviewProps) {
  const [appearance, setAppearance] = useState(defaultSubtitleAppearance)
  const [sampleId, setSampleId] = useState("short")
  const [compact, setCompact] = useState(false)
  const { chineseFontSize, russianFontSize, ...displayProps } = appearance

  return (
    <main className="settings-preview">
      <header className="settings-preview-header">
        <div><h1>设置与字幕联动</h1><p>开发场景 · 共享同一模拟会话</p></div>
        <div className="settings-preview-controls">
          <label>模拟状态<select value={status} onChange={(event) => onStatusChange(event.target.value as SubtitleStatus)}>{subtitleStatuses.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label>字幕示例<select value={sampleId} onChange={(event) => setSampleId(event.target.value)}>{subtitleSamples.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          <label>字幕尺寸<select value={compact ? "compact" : "default"} onChange={(event) => setCompact(event.target.value === "compact")}><option value="default">680 × 140</option><option value="compact">420 × 108</option></select></label>
          <a href="/settings.html">独立设置窗口</a><a href="/">字幕预览</a>
        </div>
      </header>
      <SettingsWindow status={status} onToggleSession={onToggleSession} subtitleAppearance={appearance} onSubtitleAppearanceChange={setAppearance} />
      <section className="settings-linked-caption" aria-label="开发联动字幕">
        <p>独立字幕组件 · 与上方设置共享会话及展示参数</p>
        <SubtitleCard {...getSubtitleSample(sampleId)} {...displayProps} status={status} onToggleSession={onToggleSession} style={{ width: compact ? 420 : 680, height: compact ? 108 : 140, "--subtitle-chinese-size": `${chineseFontSize}px`, "--subtitle-russian-size": `${russianFontSize}px` } as CSSProperties} />
      </section>
    </main>
  )
}
