import { useEffect, useRef, useState } from "react"
import { MotionConfig } from "motion/react"
import { Badge } from "@/components/ui/badge"
import { SubtitleCard, subtitleStatuses, type SubtitleStatus } from "@/components/SubtitleCard"
import { getSubtitleSample, subtitleSamples } from "@/preview/subtitleSamples"
import { useMockSession } from "@/preview/useMockSession"
import "./preview/preview.css"

// Development canvas only. subtitle.html mounts SubtitleCard without this page.
export default function App() {
  const [sample, setSample] = useState(() =>
    getSubtitleSample(new URLSearchParams(window.location.search).get("sample")),
  )
  const [compact, setCompact] = useState(false)
  const [backdrop, setBackdrop] = useState("blue")
  const [reduceMotion, setReduceMotion] = useState(false)
  const session = useMockSession()
  const pendingUpdates = useRef<ReturnType<typeof setTimeout>[]>([])
  useEffect(() => () => pendingUpdates.current.forEach(clearTimeout), [])
  const width = compact ? 420 : 680
  const height = compact ? 108 : 140

  return (
    <main className="preview-page font-sans text-foreground" data-backdrop={backdrop}>
      <div className="preview-content">
        <header className="space-y-2">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold">字幕预览</h1>
            <Badge>独立前端</Badge>
          </div>
          <p className="text-sm text-muted-foreground">俄语 → 中文 · 固定示例，麦克风未启用</p>
        </header>

        <div className="preview-controls">
          <label>
            示例
            <select value={sample.id} onChange={(event) => setSample(getSubtitleSample(event.target.value))}>
              {subtitleSamples.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
          <label>
            尺寸
            <select value={compact ? "compact" : "default"} onChange={(event) => setCompact(event.target.value === "compact")}>
              <option value="default">680 × 140</option>
              <option value="compact">420 × 108</option>
            </select>
          </label>
          <label>
            预览背景
            <select value={backdrop} onChange={(event) => setBackdrop(event.target.value)}>
              <option value="blue">蓝色</option>
              <option value="mono">灰阶</option>
              <option value="warm">绿色 / 暖色</option>
            </select>
          </label>
          <label>
            模拟状态
            <select value={session.status} onChange={(event) => session.setStatus(event.target.value as SubtitleStatus)}>
              {subtitleStatuses.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
          </label>
        </div>

        <div className="preview-actions">
          <button type="button" onClick={() => {
            pendingUpdates.current.forEach(clearTimeout)
            pendingUpdates.current = [1, 2, 1, 3, 2].map((index, step) => setTimeout(() => setSample(subtitleSamples[index]), step * 40))
          }}>快速更新 ×5</button>
          <label><input type="checkbox" checked={reduceMotion} onChange={(event) => setReduceMotion(event.target.checked)} />减少动画（验证）</label>
        </div>

        <div className="preview-viewport" style={{ width, height }}>
          <MotionConfig reducedMotion={reduceMotion ? "always" : "user"}>
            <SubtitleCard {...sample} status={session.status} onToggleSession={session.toggleSession} style={{ width: "100%", height: "100%" }} />
          </MotionConfig>
        </div>

        <p className="text-xs leading-5 text-muted-foreground">
          背景与示例选择仅用于开发预览。<a className="underline underline-offset-4" href={`/subtitle.html?sample=${sample.id}`}>打开纯字幕界面</a>
          <br />玻璃效果仅作用于当前网页背景；Windows 桌面透明合成尚未接入。
          <br />悬停或聚焦显示工具栏；双击空白 / F2 切换显示许可，Escape 收起。
        </p>
      </div>
    </main>
  )
}
