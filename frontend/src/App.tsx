import { motion } from "motion/react"
import { Badge } from "@/components/ui/badge"

export default function App() {
  return (
    <main className="grid min-h-svh place-items-center bg-background px-6 py-12 text-foreground">
      <div className="w-full max-w-[680px] space-y-6">
        <header className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl border border-border bg-secondary text-primary" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="5" width="18" height="14" rx="3" />
              <path d="M7 10h4m3 0h3M7 14h2m3 0h5" />
            </svg>
          </span>
          <div>
            <h1 className="text-base font-semibold tracking-tight">俄中字幕</h1>
            <p className="mt-1 text-xs text-muted-foreground">俄语 → 中文</p>
          </div>
        </header>

        {/* Static Ready mock only. Session controls belong to later slices. */}
        <motion.section
          initial={false}
          aria-labelledby="subtitle-heading"
          className="rounded-2xl border border-border bg-card p-6 text-card-foreground shadow-overlay"
        >
          <div className="flex items-center justify-between gap-4">
            <h2 id="subtitle-heading" className="text-xs font-medium text-muted-foreground">字幕</h2>
            <Badge variant="outline" role="status" className="gap-2 text-muted-foreground">
              <span className="size-1.5 rounded-full bg-ready" aria-hidden="true" />
              Ready
            </Badge>
          </div>
          <div className="space-y-2 py-6 text-center">
            <p className="text-xl font-medium tracking-tight">等待字幕</p>
            <p className="text-sm text-muted-foreground">此处将显示实时字幕</p>
          </div>
        </motion.section>

        <p className="text-center text-xs text-muted-foreground">界面预览，麦克风未启用。</p>
      </div>
    </main>
  )
}
