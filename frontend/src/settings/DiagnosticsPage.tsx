import { format, type Messages } from "./messages"
import { useState } from "react"
import type { SubtitleStatus } from "@/components/SubtitleCard"

const models = [
  { name: "Silero VAD", purpose: "vad" },
  { name: "GigaAM", purpose: "asr" },
  { name: "NLLB", purpose: "translation" },
] as const
const records = [
  "record0",
  "record1",
] as const

/** Fixed demo data only; session status comes from the existing caller. */
export function DiagnosticsPage({ status, messages }: { status: SubtitleStatus; messages: Messages }) {
  const [feedback, setFeedback] = useState<{ status: SubtitleStatus; text: keyof Messages }>()
  const error = status === "Error"
  const errorDetail = "errorDetail" as const
  function announce(text: keyof Messages) { setFeedback({ status, text }) }

  return (
    <div className="settings-diagnostics">
      <section className="settings-group" aria-label={messages.appInfo}>
        <div className="settings-group-heading"><h2>{messages.appInfo}</h2><span className="settings-caption">{messages.fixedDemo}</span></div>
        <dl className="settings-diagnostic-info">
          <div><dt>{messages.appName}</dt><dd>{messages.appFull}</dd></div>
          <div><dt>{messages.uiDemo}</dt><dd>{messages.uiDemoValue}</dd></div>
          <div><dt>{messages.version}</dt><dd>{messages.versionValue}</dd></div>
          <div><dt>{messages.currentSession}</dt><dd className="diagnostic-session" role="status">{messages[status]} · {messages.sim}</dd></div>
        </dl>
      </section>
      <section className="settings-group" aria-label={messages.modelInfo}>
        <div className="settings-group-heading"><h2>{messages.modelInfo}</h2><span className="settings-caption">{messages.noService}</span></div>
        <ul className="settings-model-list">
          {models.map((model) => <li key={model.name}><span><strong>{model.name}</strong><small>{messages[model.purpose]}</small></span><span className="settings-caption">{messages.notLoaded}</span></li>)}
        </ul>
      </section>
      <section className="settings-group" aria-label={messages.logsErrors}>
        <div className="settings-group-heading"><h2>{messages.logsErrors}</h2><span className="settings-caption">{messages.sim}</span></div>
        <p className="settings-description">{messages.logDirectory}</p>
        <code className="settings-diagnostic-path">C:\Demo\Logs</code>
        <p className="settings-diagnostic-error" role="status" data-error={error}>{error ? messages.recentError : messages.noError}</p>
        <ul className="settings-diagnostic-records">{records.map((record) => <li key={record}>{messages[record]}</li>)}{error && <li>{messages.record2}</li>}</ul>
      </section>
      <section className="settings-group" aria-label={format(messages.simLabel, { label: messages.operations })}>
        <h2>{messages.operations}</h2>
        <div className="settings-diagnostic-actions">
          <button className="settings-button" type="button" onClick={() => announce("feedbackLog")}>{messages.viewLogs}</button>
          <button className="settings-button" type="button" onClick={() => announce("feedbackExport")}>{messages.export}</button>
          <button className="settings-button" type="button" onClick={() => announce(error ? errorDetail : "feedbackNoError")}>{messages.viewError}</button>
        </div>
        <p className="settings-diagnostic-feedback" role="status">{feedback?.status === status ? messages[feedback.text] : messages.feedbackDefault}</p>
      </section>
    </div>
  )
}
