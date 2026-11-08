import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { MotionConfig } from "motion/react"
import { SettingsWindow } from "@/settings/SettingsWindow"
import { useMockSession } from "@/preview/useMockSession"
import "./styles.css"

function StandaloneSettings() {
  const session = useMockSession()
  return <SettingsWindow status={session.status} onToggleSession={session.toggleSession} />
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <StandaloneSettings />
    </MotionConfig>
  </StrictMode>,
)
