import type { SubtitleStatus } from "@/components/SubtitleCard"

const microphones = [
  { id: "default", name: "系统默认麦克风（模拟）" },
  { id: "array", name: "麦克风阵列（模拟）" },
  { id: "usb", name: "USB 麦克风（模拟）" },
]
const models = [
  { name: "Silero VAD", purpose: "语音活动检测" },
  { name: "GigaAM", purpose: "俄语识别" },
  { name: "NLLB", purpose: "中文翻译" },
]
const sessionHints: Record<SubtitleStatus, string> = {
  Ready: "准备就绪，开始后演示字幕会话。",
  Loading: "正在准备模拟会话，可以取消。",
  Listening: "正在演示监听，未采集任何音频。",
  Stopping: "正在结束模拟会话，请稍候。",
  Error: "模拟会话发生错误，请重试。",
}

interface InputPageProps {
  status: SubtitleStatus
  onToggleSession: () => void
  microphone: string
  onMicrophoneChange: (value: string) => void
  deviceFeedback: string
  onRefresh: () => void
}

export function InputPage({ status, onToggleSession, microphone, onMicrophoneChange, deviceFeedback, onRefresh }: InputPageProps) {
  const busy = status === "Loading" || status === "Listening" || status === "Stopping"
  const modelLabel = status === "Loading" ? "准备中" : status === "Error" ? "准备失败" : "已就绪"
  const actionLabel = status === "Loading" ? "取消准备" : status === "Listening" ? "停止识别" : status === "Stopping" ? "停止中…" : status === "Error" ? "重试" : "开始识别"

  return (
    <div className="settings-input">
      <section className="settings-group" aria-labelledby="microphone-heading">
        <div className="settings-group-heading"><h2 id="microphone-heading">麦克风</h2><span className="settings-caption">音频输入</span></div>
        <p className="settings-description">选择用于俄语识别的输入设备。</p>
        <div className="settings-device-controls">
          <select aria-label="麦克风" value={microphone} disabled={busy} onChange={(event) => onMicrophoneChange(event.target.value)}>
            {microphones.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <button type="button" className="settings-button" disabled={busy} onClick={onRefresh}>刷新</button>
        </div>
        <p className="settings-device-feedback" role="status">{busy ? "会话结束后可更换输入设备。" : deviceFeedback || "固定模拟设备，不会访问麦克风。"}</p>
      </section>

      <section className="settings-group" aria-labelledby="models-heading">
        <div className="settings-group-heading"><h2 id="models-heading">本地模型</h2><span className="settings-model-summary">{modelLabel} · 模拟</span></div>
        <ul className="settings-model-list">
          {models.map((model) => (
            <li key={model.name}><span><strong>{model.name}</strong><small>{model.purpose}</small></span><span className="settings-model-state"><i aria-hidden="true" />{modelLabel}</span></li>
          ))}
        </ul>
      </section>

      <section className="settings-group settings-session" aria-labelledby="session-heading">
        <div className="settings-session-description">
          <div className="settings-group-heading"><h2 id="session-heading">字幕会话</h2><span className="settings-session-state" role="status"><i aria-hidden="true" />{status}</span></div>
          <p className="settings-description" role="status">{sessionHints[status]}</p>
        </div>
        <button type="button" className="settings-button settings-button-primary" disabled={status === "Stopping"} onClick={onToggleSession}>{actionLabel}</button>
      </section>
      <p className="settings-footnote">此界面使用模拟数据，不会加载模型、采集音频或保存配置。</p>
    </div>
  )
}
