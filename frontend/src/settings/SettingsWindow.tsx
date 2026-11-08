import { useRef, useState } from "react"
import { motion, useReducedMotionConfig } from "motion/react"
import { Badge } from "@/components/ui/badge"
import type { SubtitleStatus } from "@/components/SubtitleCard"
import { InputPage } from "./InputPage"
import { SubtitlesPage } from "./SubtitlesPage"
import { WindowPage, defaultWindowSettings } from "./WindowPage"
import { DiagnosticsPage } from "./DiagnosticsPage"
import { ResetDialog } from "./ResetDialog"
import { messages, format, type Language } from "./messages"
import { defaultSubtitleAppearance } from "./subtitleAppearance"
import type { SubtitleAppearance } from "./subtitleAppearance"
import "./settings.css"

const pages = [
  { id: "input", title: "input", description: "inputDesc" },
  { id: "subtitles", title: "subtitles", description: "subtitlesDesc" },
  { id: "window", title: "window", description: "windowDesc" },
  { id: "diagnostics", title: "diagnostics", description: "diagDesc" },
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
  const [deviceFeedback, setDeviceFeedback] = useState<"" | "deviceChanged" | "devicesRefreshed">("")
  const [windowSettings, setWindowSettings] = useState(defaultWindowSettings)
  const [language, setLanguage] = useState<Language>("zh")
  const [confirmReset, setConfirmReset] = useState(false)
  const [resetPage, setResetPage] = useState<typeof pageId | null>(null)
  const [diagnosticReset, setDiagnosticReset] = useState(0)
  const resetButton = useRef<HTMLButtonElement>(null)
  const t = messages[language]
  function closeReset() { setConfirmReset(false); resetButton.current?.focus() }
  function restoreDefaults() {
    if (pageId === "input") { setMicrophone("default"); setDeviceFeedback("") }
    if (pageId === "subtitles") onSubtitleAppearanceChange({ ...defaultSubtitleAppearance })
    if (pageId === "window") setWindowSettings({ ...defaultWindowSettings })
    if (pageId === "diagnostics") setDiagnosticReset((value) => value + 1)
    setResetPage(pageId)
    closeReset()
  }
  const reducedMotion = useReducedMotionConfig()
  const page = pages.find((item) => item.id === pageId)!

  return (
    <section className="settings-window" aria-label={t.settings} lang={language} data-session-status={status}>
      <header className="settings-titlebar">
        <span className="settings-appmark" aria-hidden="true">字</span>
        <strong>{t.app}</strong><span className="settings-title-divider" /><span>{t.settings}</span>
        <Badge className="settings-mode-badge">{t.sim}</Badge>
        <select className="settings-language" aria-label={t.language} value={language} onChange={(event) => setLanguage(event.target.value as Language)}><option value="zh">简体中文</option><option value="en">English</option><option value="ru">Русский</option></select>
      </header>
      <div className="settings-body">
        <aside className="settings-sidebar">
          <nav aria-label={t.navigation}>
            {pages.map((item) => (
              <button type="button" key={item.id} aria-current={pageId === item.id ? "page" : undefined} onClick={() => setPageId(item.id)}>
                <NavigationIcon page={item.id} /><span>{t[item.title]}</span>
              </button>
            ))}
          </nav>
          <p className="settings-sidebar-note">{t.localDemo}<span>{t.micOff}</span></p>
        </aside>
        <div className="settings-content">
          <motion.div key={pageId} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reducedMotion ? 0 : 0.12 }}>
            <header className="settings-page-heading">
              <h1>{t[page.title]}</h1><p>{t[page.description]}</p>
            </header>
            {pageId === "input" ? (
              <InputPage messages={t} status={status} onToggleSession={onToggleSession} microphone={microphone} onMicrophoneChange={(value) => { setMicrophone(value); setDeviceFeedback("deviceChanged") }} deviceFeedback={deviceFeedback} onRefresh={() => setDeviceFeedback("devicesRefreshed")} />
            ) : pageId === "subtitles" ? (
              <SubtitlesPage messages={t} appearance={subtitleAppearance} onChange={onSubtitleAppearanceChange} />
            ) : pageId === "window" ? (
              <WindowPage messages={t} settings={windowSettings} onChange={setWindowSettings} />
            ) : (
              <DiagnosticsPage key={`${status}-${diagnosticReset}`} messages={t} status={status} />
            )}
            <div className="settings-reset"><button className="settings-button" type="button" ref={resetButton} onClick={() => setConfirmReset(true)}>{t.reset}</button><p role="status">{resetPage === pageId ? (pageId === "diagnostics" ? t.diagResetDone : t.resetDone) : ""}</p></div>
          </motion.div>
        </div>
      </div>
      {confirmReset && <ResetDialog title={t.resetTitle} description={pageId === "diagnostics" ? t.resetDiagDesc : format(t.resetDesc, { page: t[page.title] })} cancelLabel={t.cancel} confirmLabel={t.confirmReset} onCancel={closeReset} onConfirm={restoreDefaults} />}
    </section>
  )
}
