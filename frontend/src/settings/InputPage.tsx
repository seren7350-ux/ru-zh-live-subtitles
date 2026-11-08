import { type Messages } from "./messages"
import type { SubtitleStatus } from "@/components/SubtitleCard"

const microphones = [
  { id: "default", name: "micDefault" },
  { id: "array", name: "micArray" },
  { id: "usb", name: "micUsb" },
] as const
const models = [
  { name: "Silero VAD", purpose: "vad" },
  { name: "GigaAM", purpose: "asr" },
  { name: "NLLB", purpose: "translation" },
] as const
const sessionHints: Record<SubtitleStatus, keyof Messages> = {
  Ready: "hintReady",
  Loading: "hintLoading",
  Listening: "hintListening",
  Stopping: "hintStopping",
  Error: "hintError",
}

interface InputPageProps {
  messages: Messages
  status: SubtitleStatus
  onToggleSession: () => void
  microphone: string
  onMicrophoneChange: (value: string) => void
  deviceFeedback: "" | "deviceChanged" | "devicesRefreshed"
  onRefresh: () => void
}

export function InputPage({ messages, status, onToggleSession, microphone, onMicrophoneChange, deviceFeedback, onRefresh }: InputPageProps) {
  const busy = status === "Loading" || status === "Listening" || status === "Stopping"
  const modelLabel = status === "Loading" ? messages.preparing : status === "Error" ? messages.prepareFailed : messages.modelReady
  const actionLabel = status === "Loading" ? messages.cancelPrepare : status === "Listening" ? messages.stop : status === "Stopping" ? messages.stoppingAction : status === "Error" ? messages.retry : messages.start

  return (
    <div className="settings-input">
      <section className="settings-group" aria-labelledby="microphone-heading">
        <div className="settings-group-heading"><h2 id="microphone-heading">{messages.microphone}</h2><span className="settings-caption">{messages.audioInput}</span></div>
        <p className="settings-description">{messages.micDescription}</p>
        <div className="settings-device-controls">
          <select aria-label={messages.microphone} value={microphone} disabled={busy} onChange={(event) => onMicrophoneChange(event.target.value)}>
            {microphones.map((item) => <option key={item.id} value={item.id}>{messages[item.name]}</option>)}
          </select>
          <button type="button" className="settings-button" disabled={busy} onClick={onRefresh}>{messages.refresh}</button>
        </div>
        <p className="settings-device-feedback" role="status">{busy ? messages.deviceLocked : (deviceFeedback ? messages[deviceFeedback] : messages.deviceDefault)}</p>
      </section>

      <section className="settings-group" aria-labelledby="models-heading">
        <div className="settings-group-heading"><h2 id="models-heading">{messages.localModels}</h2><span className="settings-model-summary">{modelLabel} · {messages.sim}</span></div>
        <ul className="settings-model-list">
          {models.map((model) => (
            <li key={model.name}><span><strong>{model.name}</strong><small>{messages[model.purpose]}</small></span><span className="settings-model-state"><i aria-hidden="true" />{modelLabel}</span></li>
          ))}
        </ul>
      </section>

      <section className="settings-group settings-session" aria-labelledby="session-heading">
        <div className="settings-session-description">
          <div className="settings-group-heading"><h2 id="session-heading">{messages.session}</h2><span className="settings-session-state" role="status"><i aria-hidden="true" />{messages[status]}</span></div>
          <p className="settings-description" role="status">{messages[sessionHints[status]]}</p>
        </div>
        <button type="button" className="settings-button settings-button-primary" disabled={status === "Stopping"} onClick={onToggleSession}>{actionLabel}</button>
      </section>
      <p className="settings-footnote">{messages.inputFootnote}</p>
    </div>
  )
}
