import { useState } from "react"
import type { SubtitleStatus } from "@/components/SubtitleCard"

const models = [
  { name: "Silero VAD", purpose: "语音活动检测" },
  { name: "GigaAM", purpose: "俄语识别" },
  { name: "NLLB", purpose: "中文翻译" },
]
const records = [
  "[模拟 00:00] 已打开 UI 演示，未连接模型服务。",
  "[模拟 00:01] 已准备固定诊断示例，未读取日志文件。",
]

/** Fixed demo data only; session status comes from the existing caller. */
export function DiagnosticsPage({ status }: { status: SubtitleStatus }) {
  const [feedback, setFeedback] = useState<{ status: SubtitleStatus; text: string }>()
  const error = status === "Error"
  const errorDetail = "DEMO_SERVICE_UNAVAILABLE（模拟）：示例模型服务不可用。此错误为固定演示数据，未连接真实服务。"
  function announce(text: string) { setFeedback({ status, text }) }

  return (
    <div className="settings-diagnostics">
      <section className="settings-group" aria-label="应用信息">
        <div className="settings-group-heading"><h2>应用信息</h2><span className="settings-caption">固定模拟数据</span></div>
        <dl className="settings-diagnostic-info">
          <div><dt>应用名称</dt><dd>俄中实时字幕</dd></div>
          <div><dt>UI 演示</dt><dd>独立 React UI · 模拟模式</dd></div>
          <div><dt>版本信息</dt><dd>UI demo · 未发布，无新版发行号</dd></div>
          <div><dt>当前会话</dt><dd className="diagnostic-session" role="status">{status} · 模拟</dd></div>
        </dl>
      </section>
      <section className="settings-group" aria-label="模型信息">
        <div className="settings-group-heading"><h2>模型信息</h2><span className="settings-caption">模拟 · 未连接服务</span></div>
        <ul className="settings-model-list">
          {models.map((model) => <li key={model.name}><span><strong>{model.name}</strong><small>{model.purpose}</small></span><span className="settings-caption">未加载（模拟）</span></li>)}
        </ul>
      </section>
      <section className="settings-group" aria-label="日志与错误">
        <div className="settings-group-heading"><h2>日志与错误</h2><span className="settings-caption">模拟</span></div>
        <p className="settings-description">模拟日志目录</p>
        <code className="settings-diagnostic-path">C:\Demo\Logs</code>
        <p className="settings-diagnostic-error" role="status" data-error={error}>{error ? "最近错误：DEMO_SERVICE_UNAVAILABLE（模拟）" : "最近错误：无错误（模拟）"}</p>
        <ul className="settings-diagnostic-records">{records.map((record) => <li key={record}>{record}</li>)}{error && <li>[模拟 00:02] 示例服务不可用；未执行真实错误恢复。</li>}</ul>
      </section>
      <section className="settings-group" aria-label="诊断操作（模拟）">
        <h2>诊断操作</h2>
        <div className="settings-diagnostic-actions">
          <button className="settings-button" type="button" onClick={() => announce("模拟：日志目录为 C:\\Demo\\Logs，未打开系统目录。")}>查看日志目录</button>
          <button className="settings-button" type="button" onClick={() => announce("模拟：诊断信息导出入口已响应，未创建或下载任何文件。")}>导出诊断信息</button>
          <button className="settings-button" type="button" onClick={() => announce(error ? errorDetail : "模拟：当前无错误，没有可查看的错误详情。")}>查看错误详情</button>
        </div>
        <p className="settings-diagnostic-feedback" role="status">{feedback?.status === status ? feedback.text : "所有操作仅显示模拟反馈，不访问目录、文件或外部程序。"}</p>
      </section>
    </div>
  )
}
