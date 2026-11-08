import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { SubtitleCard } from "@/components/SubtitleCard"
import { getSubtitleSample, subtitleSamples } from "@/preview/subtitleSamples"
import "./preview/preview.css"

// Development canvas only. subtitle.html mounts SubtitleCard without this page.
export default function App() {
  const [sample, setSample] = useState(() =>
    getSubtitleSample(new URLSearchParams(window.location.search).get("sample")),
  )
  const [compact, setCompact] = useState(false)
  const width = compact ? 420 : 680
  const height = compact ? 108 : 140

  return (
    <main className="preview-page font-sans text-foreground">
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
        </div>

        <div className="preview-viewport" style={{ width, height }}>
          <SubtitleCard {...sample} style={{ width: "100%", height: "100%" }} />
        </div>

        <p className="text-xs leading-5 text-muted-foreground">
          背景与示例选择仅用于开发预览。<a className="underline underline-offset-4" href={`/subtitle.html?sample=${sample.id}`}>打开纯字幕界面</a>
          <br />玻璃效果仅作用于当前网页背景；Windows 桌面透明合成尚未接入。
        </p>
      </div>
    </main>
  )
}
