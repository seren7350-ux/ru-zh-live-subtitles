import { useEffect, useRef, useState } from "react"
import type { SubtitleStatus } from "@/components/SubtitleCard"

/** Phase 1 mock only. No devices, models, persistence, or native window actions. */
export function useMockSession() {
  const [status, setCurrentStatus] = useState<SubtitleStatus>("Ready")
  const pending = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(pending.current), [])

  function setStatus(next: SubtitleStatus) {
    clearTimeout(pending.current)
    setCurrentStatus(next)
  }

  function toggleSession() {
    if (status === "Stopping") return
    const stopping = status === "Loading" || status === "Listening"
    setStatus(stopping ? "Stopping" : "Loading")
    pending.current = setTimeout(() => setCurrentStatus(stopping ? "Ready" : "Listening"), stopping ? 350 : 600)
  }

  return { status, setStatus, toggleSession }
}
