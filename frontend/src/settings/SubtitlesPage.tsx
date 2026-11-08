import type { SubtitleAppearance } from "./subtitleAppearance"

interface SubtitlesPageProps {
  appearance: SubtitleAppearance
  onChange: (appearance: SubtitleAppearance) => void
}

export function SubtitlesPage({ appearance, onChange }: SubtitlesPageProps) {
  function setNumber(key: "chineseFontSize" | "russianFontSize" | "backgroundOpacity" | "textOpacity", value: string, min: number, max: number) {
    const number = Number(value)
    if (!value.trim() || !Number.isFinite(number)) return
    onChange({ ...appearance, [key]: Math.max(min, Math.min(max, Math.round(number))) })
  }

  return (
    <div className="settings-subtitles">
      <section className="settings-group" aria-label="字幕文字">
        <h2>字幕文字</h2>
        <label className="settings-subtitle-row">
          <span><strong>中文字号</strong><small>18–32 px</small></span>
          <span className="settings-subtitle-number"><input aria-label="中文字号" type="number" min="18" max="32" step="1" value={appearance.chineseFontSize} onChange={(event) => setNumber("chineseFontSize", event.target.value, 18, 32)} /><span>px</span></span>
        </label>
        <label className="settings-subtitle-row">
          <span><strong>俄文字号</strong><small>12–22 px</small></span>
          <span className="settings-subtitle-number"><input aria-label="俄文字号" type="number" min="12" max="22" step="1" value={appearance.russianFontSize} onChange={(event) => setNumber("russianFontSize", event.target.value, 12, 22)} /><span>px</span></span>
        </label>
        <label className="settings-subtitle-row">
          <span><strong>显示俄文字幕</strong><small>在中文下方显示原文</small></span>
          <input className="settings-subtitle-toggle" aria-label="显示俄文字幕" type="checkbox" checked={appearance.showRussian} onChange={(event) => onChange({ ...appearance, showRussian: event.target.checked })} />
        </label>
      </section>

      <section className="settings-group" aria-label="不透明度">
        <h2>不透明度</h2>
        <label className="settings-subtitle-row">
          <span><strong>背景不透明度</strong><small>仅影响卡片背景材质</small></span>
          <span className="settings-subtitle-number"><input aria-label="背景不透明度" type="number" min="0" max="100" step="1" value={appearance.backgroundOpacity} onChange={(event) => setNumber("backgroundOpacity", event.target.value, 0, 100)} /><span>%</span></span>
        </label>
        <label className="settings-subtitle-row">
          <span><strong>字幕文字不透明度</strong><small>仅影响字幕文字及描边</small></span>
          <span className="settings-subtitle-number"><input aria-label="字幕文字不透明度" type="number" min="0" max="100" step="1" value={appearance.textOpacity} onChange={(event) => setNumber("textOpacity", event.target.value, 0, 100)} /><span>%</span></span>
        </label>
      </section>

      <section className="settings-group" aria-label="可读性">
        <label className="settings-subtitle-row">
          <span><strong>黑色文字描边</strong><small>以细黑边增强复杂背景中的可读性</small></span>
          <input className="settings-subtitle-toggle" aria-label="黑色文字描边" type="checkbox" checked={appearance.textOutline} onChange={(event) => onChange({ ...appearance, textOutline: event.target.checked })} />
        </label>
      </section>
      <p className="settings-footnote">固定字号，不随字幕长短自动缩放。更改仅在当前演示中保留。</p>
    </div>
  )
}
