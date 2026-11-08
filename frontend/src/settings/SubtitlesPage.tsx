import { type Messages } from "./messages"
import type { SubtitleAppearance } from "./subtitleAppearance"

interface SubtitlesPageProps {
  messages: Messages
  appearance: SubtitleAppearance
  onChange: (appearance: SubtitleAppearance) => void
}

export function SubtitlesPage({ messages, appearance, onChange }: SubtitlesPageProps) {
  function setNumber(key: "chineseFontSize" | "russianFontSize" | "backgroundOpacity" | "textOpacity", value: string, min: number, max: number) {
    const number = Number(value)
    if (!value.trim() || !Number.isFinite(number)) return
    onChange({ ...appearance, [key]: Math.max(min, Math.min(max, Math.round(number))) })
  }

  return (
    <div className="settings-subtitles">
      <section className="settings-group" aria-label={messages.textGroup}>
        <h2>{messages.textGroup}</h2>
        <label className="settings-subtitle-row">
          <span><strong>{messages.chineseSize}</strong><small>18–32 px</small></span>
          <span className="settings-subtitle-number"><input aria-label={messages.chineseSize} type="number" min="18" max="32" step="1" value={appearance.chineseFontSize} onChange={(event) => setNumber("chineseFontSize", event.target.value, 18, 32)} /><span>px</span></span>
        </label>
        <label className="settings-subtitle-row">
          <span><strong>{messages.russianSize}</strong><small>12–22 px</small></span>
          <span className="settings-subtitle-number"><input aria-label={messages.russianSize} type="number" min="12" max="22" step="1" value={appearance.russianFontSize} onChange={(event) => setNumber("russianFontSize", event.target.value, 12, 22)} /><span>px</span></span>
        </label>
        <label className="settings-subtitle-row">
          <span><strong>{messages.showRussian}</strong><small>{messages.russianBelow}</small></span>
          <input className="settings-subtitle-toggle" aria-label={messages.showRussian} type="checkbox" checked={appearance.showRussian} onChange={(event) => onChange({ ...appearance, showRussian: event.target.checked })} />
        </label>
      </section>

      <section className="settings-group" aria-label={messages.opacity}>
        <h2>{messages.opacity}</h2>
        <label className="settings-subtitle-row">
          <span><strong>{messages.backgroundOpacity}</strong><small>{messages.backgroundOnly}</small></span>
          <span className="settings-subtitle-number"><input aria-label={messages.backgroundOpacity} type="number" min="0" max="100" step="1" value={appearance.backgroundOpacity} onChange={(event) => setNumber("backgroundOpacity", event.target.value, 0, 100)} /><span>%</span></span>
        </label>
        <label className="settings-subtitle-row">
          <span><strong>{messages.textOpacity}</strong><small>{messages.textOnly}</small></span>
          <span className="settings-subtitle-number"><input aria-label={messages.textOpacity} type="number" min="0" max="100" step="1" value={appearance.textOpacity} onChange={(event) => setNumber("textOpacity", event.target.value, 0, 100)} /><span>%</span></span>
        </label>
      </section>

      <section className="settings-group settings-readability" aria-label={messages.readability}>
        <label className="settings-subtitle-row">
          <span><strong>{messages.outline}</strong><small>{messages.outlineHint}</small></span>
          <input className="settings-subtitle-toggle" aria-label={messages.outline} type="checkbox" checked={appearance.textOutline} onChange={(event) => onChange({ ...appearance, textOutline: event.target.checked })} />
        </label>
      </section>
      <p className="settings-footnote">{messages.subtitleFootnote}</p>
    </div>
  )
}
