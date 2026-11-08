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
  { field: "startStopShortcut", label: "开始 / 停止识别", key: "S" },
  { field: "showHideShortcut", label: "显示 / 隐藏字幕", key: "H" },
  { field: "settingsShortcut", label: "打开设置", key: "Comma" },
  { field: "pinShortcut", label: "切换置顶", key: "P" },
] as const
const geometry = [
  { field: "x", label: "X 坐标", min: -10000, max: 10000 },
  { field: "y", label: "Y 坐标", min: -10000, max: 10000 },
  { field: "width", label: "窗口宽度", min: 420, max: 1920 },
  { field: "height", label: "窗口高度", min: 108, max: 1080 },
] as const

interface WindowPageProps {
  settings: MockWindowSettings
  onChange: (settings: MockWindowSettings) => void
}

/** Values only: no window APIs, shortcut registration, or filesystem access. */
export function WindowPage({ settings, onChange }: WindowPageProps) {
  function setGeometry(field: typeof geometry[number], value: string) {
    const number = Number(value)
    if (!value.trim() || !Number.isFinite(number)) return
    onChange({ ...settings, [field.field]: Math.max(field.min, Math.min(field.max, Math.round(number))) })
  }

  return (
    <div className="settings-window-options">
      <section className="settings-group" aria-label="窗口行为（模拟）">
        <div className="settings-group-heading"><h2>窗口行为</h2><span className="settings-caption">模拟</span></div>
        <label className="settings-window-option"><span>窗口置顶</span><input aria-label="窗口置顶（模拟）" type="checkbox" checked={settings.topmost} onChange={(event) => onChange({ ...settings, topmost: event.target.checked })} /></label>
        <label className="settings-window-option"><span>无边框模式</span><input aria-label="无边框模式（模拟）" type="checkbox" checked={settings.borderless} onChange={(event) => onChange({ ...settings, borderless: event.target.checked })} /></label>
        <label className="settings-window-option"><span>工具栏显示许可</span><input aria-label="工具栏显示许可（模拟）" type="checkbox" checked={settings.toolbarAllowed} onChange={(event) => onChange({ ...settings, toolbarAllowed: event.target.checked })} /></label>
        <p className="settings-window-feedback" role="status">置顶{settings.topmost ? "开" : "关"} · 无边框{settings.borderless ? "开" : "关"} · 工具栏许可{settings.toolbarAllowed ? "开" : "关"}。仅记录模拟值，不改变窗口或当前字幕工具栏。</p>
      </section>

      <section className="settings-group" aria-label="位置与尺寸（模拟）">
        <div className="settings-group-heading"><h2>位置与尺寸</h2><span className="settings-caption">模拟 · DIP</span></div>
        <div className="settings-window-geometry">
          {geometry.map((field) => <label key={field.field}><span>{field.label}</span><input aria-label={`${field.label}（模拟）`} type="number" step="1" min={field.min} max={field.max} value={settings[field.field]} onChange={(event) => setGeometry(field, event.target.value)} /></label>)}
        </div>
        <p className="settings-window-feedback" role="status">位置 ({settings.x}, {settings.y})，尺寸 {settings.width} × {settings.height} DIP。仅保留设置值，不移动或缩放窗口。</p>
      </section>

      <section className="settings-group" aria-label="全局快捷键（模拟）">
        <div className="settings-group-heading"><h2>全局快捷键</h2><span className="settings-caption">模拟</span></div>
        <p className="settings-description">选择候选组合或关闭此项，不注册系统快捷键。</p>
        {shortcuts.map((action) => (
          <label className="settings-window-shortcut" key={action.field}>
            <span>{action.label}</span>
            <select aria-label={`${action.label}快捷键（模拟）`} value={settings[action.field]} onChange={(event) => onChange({ ...settings, [action.field]: event.target.value })}>
              <option value="">未设置</option><option>{`Ctrl + Alt + ${action.key}`}</option><option>{`Ctrl + Shift + ${action.key}`}</option>
            </select>
          </label>
        ))}
        <p className="settings-window-feedback" role="status">已配置 {shortcuts.filter((action) => settings[action.field]).length} 项模拟快捷键，未检查系统占用，未注册。</p>
      </section>

      <section className="settings-group" aria-label="SRT 保存（模拟）">
        <div className="settings-group-heading"><h2>SRT 字幕保存</h2><span className="settings-caption">模拟</span></div>
        <label className="settings-window-option"><span>保存 SRT</span><input aria-label="保存 SRT（模拟）" type="checkbox" checked={settings.saveSrt} onChange={(event) => onChange({ ...settings, saveSrt: event.target.checked })} /></label>
        <p className="settings-description">模拟输出目录</p>
        <code className="settings-window-path">C:\Demo\Subtitles</code>
        <p className="settings-window-feedback" role="status">SRT 保存已{settings.saveSrt ? "开启" : "关闭"}（模拟）。固定示例路径，不读取目录或写入文件。</p>
      </section>
    </div>
  )
}
