import { format, type Messages } from "./messages"
export interface MockWindowSettings {
  topmost: boolean
  borderless: boolean
  toolbarAllowed: boolean
  x: number
  y: number
  width: number
  height: number
  startStopShortcut: string
  showHideShortcut: string
  settingsShortcut: string
  pinShortcut: string
  saveSrt: boolean
}

export const defaultWindowSettings: MockWindowSettings = {
  topmost: true, borderless: true, toolbarAllowed: true,
  x: 120, y: 120, width: 680, height: 140,
  startStopShortcut: "Ctrl + Alt + S", showHideShortcut: "Ctrl + Alt + H",
  settingsShortcut: "Ctrl + Alt + Comma", pinShortcut: "Ctrl + Alt + P",
  saveSrt: true,
}

const shortcuts = [
  { field: "startStopShortcut", label: "startStop", key: "S" },
  { field: "showHideShortcut", label: "showHide", key: "H" },
  { field: "settingsShortcut", label: "openSettings", key: "Comma" },
  { field: "pinShortcut", label: "togglePin", key: "P" },
] as const
const geometry = [
  { field: "x", label: "x", min: -10000, max: 10000 },
  { field: "y", label: "y", min: -10000, max: 10000 },
  { field: "width", label: "width", min: 420, max: 1920 },
  { field: "height", label: "height", min: 108, max: 1080 },
] as const

interface WindowPageProps {
  messages: Messages
  settings: MockWindowSettings
  onChange: (settings: MockWindowSettings) => void
}

/** Values only: no window APIs, shortcut registration, or filesystem access. */
export function WindowPage({ messages, settings, onChange }: WindowPageProps) {
  function setGeometry(field: typeof geometry[number], value: string) {
    const number = Number(value)
    if (!value.trim() || !Number.isFinite(number)) return
    onChange({ ...settings, [field.field]: Math.max(field.min, Math.min(field.max, Math.round(number))) })
  }

  return (
    <div className="settings-window-options">
      <section className="settings-group" aria-label={format(messages.simLabel, { label: messages.windowBehavior })}>
        <div className="settings-group-heading"><h2>{messages.windowBehavior}</h2><span className="settings-caption">{messages.sim}</span></div>
        <label className="settings-window-option"><span>{messages.topmost}</span><input aria-label={format(messages.simLabel, { label: messages.topmost })} type="checkbox" checked={settings.topmost} onChange={(event) => onChange({ ...settings, topmost: event.target.checked })} /></label>
        <label className="settings-window-option"><span>{messages.borderless}</span><input aria-label={format(messages.simLabel, { label: messages.borderless })} type="checkbox" checked={settings.borderless} onChange={(event) => onChange({ ...settings, borderless: event.target.checked })} /></label>
        <label className="settings-window-option"><span>{messages.toolbarAllowed}</span><input aria-label={format(messages.simLabel, { label: messages.toolbarAllowed })} type="checkbox" checked={settings.toolbarAllowed} onChange={(event) => onChange({ ...settings, toolbarAllowed: event.target.checked })} /></label>
        <p className="settings-window-feedback" role="status">{format(messages.behaviorFeedback, { topmost: settings.topmost ? messages.on : messages.off, borderless: settings.borderless ? messages.on : messages.off, toolbar: settings.toolbarAllowed ? messages.on : messages.off })}</p>
      </section>

      <section className="settings-group" aria-label={format(messages.simLabel, { label: messages.geometry })}>
        <div className="settings-group-heading"><h2>{messages.geometry}</h2><span className="settings-caption">{messages.sim} · DIP</span></div>
        <div className="settings-window-geometry">
          {geometry.map((field) => <label key={field.field}><span>{messages[field.label]}</span><input aria-label={format(messages.simLabel, { label: messages[field.label] })} type="number" step="1" min={field.min} max={field.max} value={settings[field.field]} onChange={(event) => setGeometry(field, event.target.value)} /></label>)}
        </div>
        <p className="settings-window-feedback" role="status">{format(messages.geometryFeedback, { x: settings.x, y: settings.y, width: settings.width, height: settings.height })}</p>
      </section>

      <section className="settings-group" aria-label={format(messages.simLabel, { label: messages.shortcuts })}>
        <div className="settings-group-heading"><h2>{messages.shortcuts}</h2><span className="settings-caption">{messages.sim}</span></div>
        <p className="settings-description">{messages.shortcutsHint}</p>
        {shortcuts.map((action) => (
          <label className="settings-window-shortcut" key={action.field}>
            <span>{messages[action.label]}</span>
            <select aria-label={format(messages.shortcutLabel, { action: messages[action.label] })} value={settings[action.field]} onChange={(event) => onChange({ ...settings, [action.field]: event.target.value })}>
              <option value="">{messages.unassigned}</option><option>{`Ctrl + Alt + ${action.key}`}</option><option>{`Ctrl + Shift + ${action.key}`}</option>
            </select>
          </label>
        ))}
        <p className="settings-window-feedback" role="status">{format(messages.shortcutsFeedback, { count: shortcuts.filter((action) => settings[action.field]).length })}</p>
      </section>

      <section className="settings-group" aria-label={format(messages.simLabel, { label: messages.srtGroup })}>
        <div className="settings-group-heading"><h2>{messages.srtGroup}</h2><span className="settings-caption">{messages.sim}</span></div>
        <label className="settings-window-option"><span>{messages.saveSrt}</span><input aria-label={format(messages.simLabel, { label: messages.saveSrt })} type="checkbox" checked={settings.saveSrt} onChange={(event) => onChange({ ...settings, saveSrt: event.target.checked })} /></label>
        <p className="settings-description">{messages.outputDir}</p>
        <code className="settings-window-path">C:\Demo\Subtitles</code>
        <p className="settings-window-feedback" role="status">{format(messages.srtFeedback, { enabled: settings.saveSrt ? messages.on : messages.off })}</p>
      </section>
    </div>
  )
}
