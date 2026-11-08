import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { MotionConfig } from "motion/react"
import { SubtitleCard } from "@/components/SubtitleCard"
import { getSubtitleSample } from "@/preview/subtitleSamples"
import { useMockSession } from "@/preview/useMockSession"
import "./styles.css"

// Standalone mock entry. A future host can supply text to the same root component.
const sample = getSubtitleSample(new URLSearchParams(window.location.search).get("sample"))

function StandaloneSubtitle() {
  const session = useMockSession()
  return <SubtitleCard {...sample} status={session.status} onToggleSession={session.toggleSession} />
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <StandaloneSubtitle />
    </MotionConfig>
  </StrictMode>,
)
