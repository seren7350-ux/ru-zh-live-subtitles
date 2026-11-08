import { StrictMode, useState } from "react"
import { createRoot } from "react-dom/client"
import { MotionConfig } from "motion/react"
import { SettingsWindow } from "@/settings/SettingsWindow"
import { useMockSession } from "@/preview/useMockSession"
import { defaultSubtitleAppearance } from "@/settings/subtitleAppearance"
import "./styles.css"

function StandaloneSettings() {
  const session = useMockSession()
  const [subtitleAppearance, setSubtitleAppearance] = useState(defaultSubtitleAppearance)
  return <SettingsWindow status={session.status} onToggleSession={session.toggleSession} subtitleAppearance={subtitleAppearance} onSubtitleAppearanceChange={setSubtitleAppearance} />
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <StandaloneSettings />
    </MotionConfig>
  </StrictMode>,
)
