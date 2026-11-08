# REFACTOR.md — Windows 11 Raycast 风格 UI 迁移执行计划

> **状态：计划已确定，尚未开始执行 Phase 0。**
> 本文是本次迁移的**唯一活跃总计划与进度记录**，由 Codex 在各阶段结束时维护。
> 长期行为约束见根目录 `AGENTS.md`。不要新建第二份计划或重复的进度日志。

## A. 项目基线与真实现状

| 项目 | 基线 |
| --- | --- |
| 仓库 | `seren7350-ux/ru-zh-live-subtitles` |
| 开发基线分支 | `main` |
| 已核对源码提交 | `a5feb50d97581f8d13f1596255ff9f93a6b03d24` |
| 已核对版本 | `v0.4.0`（`pyproject.toml`） |
| 重构工作分支 | `feature/raycast-ui-rewrite`（**待创建；不得在 main 直接重构**） |
| 目标平台 | Windows 11 x64，单用户，完全离线 |
| 模型管线 | Silero ONNX VAD → GigaAM → NLLB |
| 现有 GUI | Tkinter；带有会话控制、事件消费、SRT 等业务职责 |
| 本文件初始状态 | **仅计划；未执行命令、未通过任何新测试、未生成新 UI** |

已有 `docs/architecture.md`、`docs/gui-boundaries.md`、`docs/windows-refactor-baseline.md`、`docs/refactor-release-acceptance.md` 和 `docs/ui-redesign-goals.md` 记录旧版行为与历史证据。**它们是迁移输入，不可把旧版测试记录直接写成新版通过。**

## B. 不可变的产品与技术决定

### B1. 唯一目标架构

```text
Russian–Chinese Live Subtitles
├── Desktop Host: C# / WPF
│   ├── SubtitleWindow + SettingsWindow
│   ├── WebView2 views（React UI）
│   ├── Windows 11 taskbar / tray / global hotkeys
│   ├── native window hit testing, size, drag, activation
│   └── UI state & preferences adapter
├── Frontend: React + TypeScript
│   ├── Tailwind CSS + shadcn/ui
│   ├── Motion for React
│   ├── subtitle overlay and settings pages
│   └── zh / en / ru UI translations
├── IPC: Windows Named Pipes
│   └── length-prefixed UTF-8 JSON, versioned messages
└── Resident Python Engine
    ├── Silero VAD + GigaAM + NLLB (reuse existing code)
    ├── one reusable prepared model pipeline
    ├── a fresh capture/VAD/subtitle session per Start
    ├── SRT ownership independent from windows
    └── existing diagnostic logging and model assets
```

不更换技术栈，不引入 Electron/Tauri/Qt/WinUI 或 HTTP 服务。不为了“更通用”扩张本地 IPC。**现有 Python 识别/翻译核心不整体重写。**

### B2. 工作范围与工程风格

- 此工程只服务个人 Windows 11 使用场景：可放弃跨平台、多人、组织权限、插件和云端需求。
- UI 是完整技术迁移，而非 Tkinter 换肤；但是核心 VAD/ASR/翻译/SRT/日志尽量保留。
- 保留旧版软件直到 Phase 6 通过；阶段中保证旧入口可用，禁止在早期批量删除 `gui/`。
- 只为本次迁移增加必要代码和依赖。既有测试优先复用，按风险验证，禁止无意义大规模测试与文档堆积。
- Codex 可以独立完成已授权阶段内的实现；**不允许自动跨阶段**。

### B3. 锁定的字幕窗体验

| 属性 | 目标规格 / 行为 |
| --- | --- |
| 初始窗口 | 680 × 140 **WPF 逻辑单位（DIP）**；用户可拖动、自由缩放；小尺寸仍可操作 |
| 主题 | Raycast 风格的克制深色视觉；不仿制 macOS 标题栏/交通灯 |
| 圆角 | 目标 16–20 DIP，实际与 Windows 11 合成能力协同验证 |
| 背景 | 深色半透明；优先原生窗口背景材质 + WebView2 透明合成；目标中高模糊，但真实性须经 Windows 实测 |
| 语言布局 | **中文在上，俄文在下**；每种语言最多显示一行，俄文可在设置中隐藏 |
| 字号 | 中、俄文字号分别固定且可设置，不因每次字幕变化随机缩放 |
| 长字幕 | 文本溢出才水平跑马灯；短字幕不移动；不裁掉用于保存的原文 |
| 字幕切换 | 克制的淡入淡出；无持续无意义动画，不遮蔽新字幕 |
| 工具栏 | 默认鼠标悬停才出现；提供双击切换工具栏显示许可的行为，避免与拖动/按钮冲突 |
| 状态 | 小型清楚的 Ready / Loading / Listening / Stopping / Error 反馈 |
| 拖动/缩放 | 字幕非交互区域可拖动；边缘/角落缩放；按钮、滑块不被拖动事件劫持 |
| 置顶/恢复 | 可置顶，可从任务栏/托盘/快捷键唤回；透明到 0% 仍可恢复 |
| 透明/描边 | 背景与文字独立 0–100%；可启用黑色文字描边 |

**关键合成限制：** WebView2 内部 CSS 的 `backdrop-filter` 只能模糊它自己可见的页面内容，**不能承诺**透过 WebView2 直接模糊后方的桌面应用。Phase 3 必须做真实 Windows 11 合成实验（WPF 分层、WebView2/CompositionControl、DWM 背景材质、点击和拖动命中测试）。**不允许用假截图宣称毛玻璃已实现；失败时暂停报告，不擅自换技术栈。**

### B4. 锁定的设置体验

四个导航页：

1. **Input**：麦克风选择/刷新、模型就绪或缺失、Start / Stop / 取消加载、错误状态。
2. **Subtitles**：显示俄文、中文/俄文字号、背景透明度、文字透明度、黑描边。
3. **Window**：置顶、无边框、工具栏可见性、位置/尺寸、全局快捷键、SRT 目录与保存。
4. **Diagnostics**：版本/模型信息、日志目录、错误摘要与诊断导出（优先复用已有日志能力）。

- 中文 / English / Русский **即时切换 UI 语言**；不会改变实际识别俄语和翻译中文的管线。
- 设置变化即时反馈在真正的字幕窗口，**不做冗余的设置内预览窗**。
- 每页独立重置，确认默认“否”；重置不清空其他页、界面语言、字幕文件或模型。
- 调整麦克风等会话相关项必须遵守运行状态；不能在采集中偷偷重建模型或麦克风。
- 设置窗口关闭仅隐藏设置，不终止识别；字幕窗隐藏也不停止采集和 SRT。

### B5. 引擎与退出语义

```text
App launched
  └─ start resident Python service
       ├─ offline preflight / load model assets
       ├─ prepare VAD + ASR + translation once
       └─ READY（未打开麦克风）

Start → new session ID → fresh microphone/VAD/segment workers → LISTENING
Stop  → stop capture → flush completed tail results / SRT → release microphone/workers
      → READY（模型仍在内存，进程不退出）
Start → another fresh session, same model pipeline (no reload)
Exit  → graceful service shutdown; fallback bounded cleanup; release model/process
```

- 不复用已经停止的 `LiveTerminalSession` 对象。**复用模型 pipeline，重建每次会话对象**。
- 同时最多一个 active live session，防双击 Start / Stop、会话交叉和过期事件覆盖。
- 冷启动模型加载属于 app 启动时的后台准备；不能阻塞 WPF UI 线程；失败要有可见的可重试错误。
- 默认完全离线：任何未准备模型都报告本地资源缺失，不能自动联网下载。
- `SrtSession` 每次 Start 独立创建新文件；去重使用会话边界/片段索引；基于音频时间轴保存完整中俄文本及时间戳。
- 无论窗体隐藏与否，服务仍处理 SRT；发生写盘失败应保留已成功保存内容并显示独立错误。
- 引擎崩溃后 UI 不能假装仍在 Listening；允许有限次数恢复，不进入无限崩溃重启循环；重启后必须重新加载模型并如实显示。

## C. 当前模块迁移映射（已核对基线）

| 现有路径/组件 | 新版处理 | 严格边界 |
| --- | --- | --- |
| `asr/`、`translation/` | 保留 | 不更换模型算法；仅修真实兼容问题 |
| `realtime/` | 保留核心 | 复用麦克风/VAD/分段；会话对象每轮重建 |
| `pipeline/offline_file.py` | 保留 | 复用 `OfflineAudioTranslationPipeline.prepare()` 和实例缓存 |
| `realtime/live_subtitles.py` | 适配 | `LiveTerminalSession(pipeline=...)` 可注入已准备实例 |
| `subtitles.py` | 保留，转移调用方 | SRT 文件生命周期与 UI 解耦 |
| `diagnostic_logging.py`、`model_assets.py` | 保留 | 日志、离线模型校验不重新设计 |
| `gui/state.py`、`gui/session_view.py` | 迁移或复用语义 | 已有无 Tk 的状态处理，禁止盲目重写 |
| `gui/events.py` | 迁移协议语义 | 事件字段在 JSON 合同中明确化 |
| `gui/process_controller.py` | 替换旧路径 | 旧版每次 Start spawn worker；新版需常驻 service |
| `gui/app.py` | 拆出业务职责 | SRT、事件尾部处理、配置及退出必须另有归属 |
| `gui/overlay.py`、`settings_panel.py`、`settings_pages.py` | 由 React 取代 | 旧 Tk 版本留到 Phase 6 通过 |
| `gui/settings_theme.py`、`caption_layer.py`、`single_line.py` | 新前端/原生层重做 | 单行、描边、透明、窗口合成保留行为 |
| `gui/window_coordinator.py`、`windows_taskbar.py`、`single_instance.py` | C# WPF 接管 | 单实例、任务栏和窗口恢复属于宿主 |
| `gui/i18n.py` | 翻译表迁入 React i18n | 延续中英俄，保留动态文案语义 |
| `preferences.py` | 兼容旧版读取与迁移 | v1 的 `preferences.json` 不得被静默覆盖 |
| `packaging/` | 扩展/替换入口 | 保留现有 CPU 离线打包资产与证据 |

### C1. 不可丢失的旧版细节

- `gui/app.py` 的 `start()` 在创建新 SRT 前先消费上一会话的队列尾部；新版要保证同等结果，不得丢掉 Stop 后晚到的字幕。
- `subtitles.py` 当前每个 SRT cue 追加后关闭文件，并有重复索引和部分写入保护；不要因迁移改成 UI 内存缓存到退出才保存。
- `preferences.py` 当前文件路径取自 `user_data_directory() / "preferences.json"`，格式 `{ "version": 1, "preferences": {...} }`；包括 `ui_language`、`microphone_name`、独立透明度与窗口信息。**首次运行新宿主必须安全读取旧偏好、映射至新设置，并保留原文件作为回退。**
- `gui/single_instance.py` 负责现有同用户单实例唤回；WPF 不能因第二次启动出现另一套独立引擎。
- 当前字幕默认路径为 `%USERPROFILE%\ru-zh-live-subtitles\subtitles`；模型/偏好/日志主要位于 `%LOCALAPPDATA%\ru-zh-live-subtitles`。不要随意改路径或搬走用户文件。
- `packaging/installer/cpu-only.iss` 当前 `[UninstallDelete]` 删除 `{localappdata}\ru-zh-live-subtitles`；必须在 Phase 6 前修复，以防正常卸载删掉模型缓存、偏好、日志等用户数据。保留稳定 `AppId` 的升级兼容性，除非有实际证据要求改变。

## D. 建议的最小目录结构（是目标，不是 Phase 0 必须创建的空目录）

```text
AGENTS.md
REFACTOR.md
contracts/
  protocol.json              # 可选：只有真正用于跨语言生成/验证才创建
  README.md                  # 仅当现有消息结构需要说明时创建
frontend/
  package.json
  src/
    components/
    windows/
    settings/
    styles/
    i18n/
desktop/
  RuZh.Subtitles.Host/
src/live_subtitles/
  service/
  asr/                       # 既有
  translation/               # 既有
  realtime/                  # 既有
  pipeline/                  # 既有
packaging/                   # 既有；按 Phase 6 扩展
tests/                       # 既有；按风险补最少的定向测试
```

创建目录/文件的原则：**需求出现时再创建；不为目录树漂亮而填充空模块、模板、样板或无用文档。** 具体内部文件名由对应阶段实现时最小化确定。

## E. 7 个阶段及硬性停止点

| Phase | 内容 | 状态 | 主要交付/停止点 |
| --- | --- | --- | --- |
| **0** | 只读审计、隔离分支、旧版基线 | **未开始** | 源码映射、一次基线、后续切片计划；停止 |
| **1** | React 字幕悬浮窗 + 最小设计系统 | 未授权 | 本地真正运行的字幕 UI，模拟状态验收；停止 |
| **2** | React 四页设置 + 三语 + 状态联动 | 未授权 | React 独立完整 UI；停止 |
| **3** | WPF + WebView2 双窗宿主 | 未授权 | 原生窗口交互、透明合成实测；停止 |
| **4** | Named Pipes + JSON 合同 | 未授权 | C# ↔ 模拟 Python 服务可靠通信；停止 |
| **5** | 常驻 Python 引擎 + 业务迁移 | 未授权 | Start/Stop 模型复用 + SRT + 异常恢复；停止 |
| **6** | 端到端集成、用户验收、离线安装 | 未授权 | 在干净 Windows 离线运行的正式可交付包；停止 |

### Phase 0 — 保护基线与工程审计（唯一当前授权阶段）

**允许：** 读取/分析已有代码、建独立 Git 分支、在本文件中更新真实审计结果、记录基线、执行一次合理的基线测试；必要时添加极少量只读验证脚本，但应优先使用现有命令。

**禁止：** 删除/迁移旧 GUI；改现有音频、模型、翻译、SRT；安装新 UI 栈；创建 UI 样板；顺手修 unrelated bugs；提前进入 Phase 1。

待办清单（未完成的项一律保持 `[ ]`）：

- [ ] 检查 `git status`、确认 main HEAD 与基线提交；如有用户工作区改动，先避让。
- [ ] 从当前 HEAD 创建/切换 `feature/raycast-ui-rewrite`；在该分支工作，不触碰 main。
- [ ] 只读检查 GUI 事件/业务边界：`app.py`、`state.py`、`session_view.py`、`events.py`、`process_controller.py`、`shutdown.py`。
- [ ] 检查模型与会话复用点：`OfflineAudioTranslationPipeline`、`LiveTerminalSession`、`LiveVadSession`、`SegmentProcessor`。
- [ ] 检查模型资源预检、偏好 v1、SRT 保存、日志和用户数据路径。
- [ ] 检查现有 `.github/workflows/tests.yml`、`tests/` 与打包/安装脚本，确定真正有用的回归集合。
- [ ] 记录 Python 环境、Windows 运行条件、可实际执行的命令；**基线完整测试最多一次**，如成本/环境不允许则说明，不能声称已通过。
- [ ] 给 Phase 1 写出最多 3–6 个连续任务切片，每个含完成标准和最小验证；不得在本阶段实施。
- [ ] 更新本文「执行记录」及「当前执行窗口」；完成 Phase 0 后停止。

**通过条件：** main 保持原样；旧 Tk 版入口及功能不被本阶段修改；证据与缺口分开陈述；下阶段执行范围明确；可从 Git 找到安全回滚点。

### Phase 1 — React 字幕窗口（只模拟，未授权）

**范围：** 构建 `frontend/` 的 React/TS/Tailwind/shadcn/ui/Motion 最小工程；一个能独立运行的字幕悬浮窗页面和同一套设计 tokens（不要建立庞大组件库）。

**模拟状态：** Ready、Loading、Listening、中俄正常字幕、超长字幕、错误、隐藏俄文、背景/文字 0%、描边、工具栏 hover、窗口尺寸变化。使用固定可复现 mock data；不联网、不读麦克风、不导入 Python。

**验收：** 真正的浏览器运行效果（不是概念图）；中文在上俄文在下；短句无滚动、长句仅横向滚动；过渡自然、交互状态有反馈；可在开发环境重复启动并演示。浏览器级模拟缩放**不等于** Windows 窗口拖动/透明合成验收。

**禁止：** 建 WPF 宿主、真正的 Named Pipes 或 Python 模型接入；无边界扩展设置页。

### Phase 2 — React 设置窗口（仅模拟，未授权）

**范围：** Input、Subtitles、Window、Diagnostics 四页；复用 Phase 1 的视觉 tokens 和 UI 组件，做即时状态联动与中/英/俄翻译字典。

**验收：** 状态改变能在真实渲染的模拟字幕窗看到；三语切换后导航、按钮、状态、错误、动态字段不漏翻；键盘焦点与小尺寸滚动可用；无需设置内重复预览；重置仅影响当前页。模拟持久化/跨进程能力不得宣称已完成。

**禁止：** 提前重做 Python 偏好、引擎或系统级快捷键。

### Phase 3 — WPF + WebView2 Windows 11 宿主（未授权）

**范围：** `SubtitleWindow` + `SettingsWindow`；WebView2 挂载 Phase 1–2 React 资源；单实例唤回、托盘、任务栏、显示/隐藏、窗口位置/缩放/置顶、快捷键。进程可先由模拟状态驱动。

**必须先做的最小技术实验：**

- WPF WebView2 透明背景与系统材料是否真正组合成功；必要时验证 `WebView2CompositionControl`。
- Windows DWM/背景材质在当前部署方式的可用性及实际限制。
- 无边框拖动、边缘缩放、DPI、鼠标命中、透明到 0 的可恢复性。
- 设置窗、字幕窗、其他程序之间的激活/层级与任务栏唤回，避免闪烁、隐藏后无法找到。

**验收：** 真实 Win11 桌面录像或截图加可复现的操作说明；可从任务栏/托盘唤回；透明合成真实有效（无法实现时记录实测限制，停止报告用户决定，不能换技术栈）；主机关闭和隐藏语义正确。

**禁止：** 在未证实透明合成的情况下堆叠多个神秘 Win32 hack；用 CSS 截图替代原生验证。

### Phase 4 — Named Pipes 合同与模拟服务（未授权）

**范围：** C# 宿主与 Python mock service 使用**本机 Windows Named Pipes** 双向通信；JSON 协议小而确定，不引入网络服务器。

**协议初始最小约定（同一阶段核实并实现，避免双端自由发挥）：**

```text
framing: uint32 little-endian byte length + UTF-8 JSON body
maximum JSON frame: 1 MiB (oversize => reject with diagnostic)
protocol_version: 1
request: {type:"request", version:1, request_id:"...", command:"...", payload:{...}}
reply:   {type:"reply",   version:1, request_id:"...", ok:true, payload:{...}}
event:   {type:"event",   version:1, event:"...", session_id:"...", payload:{...}}
```

- 最小命令：`hello`、`get_snapshot`、`get_devices`、`start`、`stop`、`shutdown`；参数与错误结构只实现确有使用者的字段。
- 最小事件：`engine_status`、`session_status`、`subtitle`、`session_finished`、`error`；字段对应现有 event 数据，字幕必须携带会话 ID、片段序号、音频时间戳及完整俄中原文。
- 服务端根据实际 Win11 用户权限配置**仅同用户**的 Pipe 访问控制；只允许本机通信，不增加认证服务器。
- 所有消息必须有版本；request 与 reply 有 `request_id`；字幕事件有 `session_id` 防过期更新。
- 启动时握手、明确的失败/超时、异常关闭检测；断线后 UI 显示失联状态并提供恢复；重连时 `get_snapshot` 恢复权威状态，不假定旧会话仍有效。

**验收：** 真实 C# ↔ mock Python 两进程测试 Start/Stop/字幕/错误/断开/重连/无响应；独立确认帧边界与非 ASCII（中俄文）无乱码。

**禁止：** 加入通用 RPC 框架、数据库、消息中间件、HTTP/WebSocket 或提前加载 AI 模型。

### Phase 5 — Python 常驻引擎与业务解耦（未授权）

**范围：** 新增 `src/live_subtitles/service/` 的最小常驻服务；从 `gui/app.py` 分离必要业务逻辑；Host 通过 Pipe 管理引擎；重用现有 VAD/ASR/翻译实现。

**关键设计约束：**

- 常驻 service 保留 `OfflineAudioTranslationPipeline` 的**同一个已 prepare 实例**；一次 Start 构造新的 `LiveTerminalSession(pipeline=...)` 和必要的 VAD/采集状态。
- 同时只允许一个 active session，重入 Start 应明确返回当前状态或拒绝，不得偷偷启动第二个麦克风。
- Stop 应有有限时间的清理、尾部结果交付与麦克风关闭；即使 UI 不见仍持续保存 SRT。
- **SRT 的权威写入方仅为 Python service**；每次 Start 新建一份，避免 GUI 和引擎双写；沿用 `SrtSession` 的去重与失败保护。
- **新版设置持久化的唯一写入方为 WPF Host**；从现有 `preferences.json` v1 安全迁移，迁移需幂等且保留原文件；service 接收运行所需配置，不和 Host 双写同一配置。正式路径/格式在本阶段固定并记录。
- 引擎的模型、设备与日志错误区分显示；加载失败保持 UI 可关闭或重试；不用为了恢复崩溃无限循环。
- 不改变当前推理模型、实时分段算法或 SRT 时间戳含义。

**验收：** 真实离线模型成功 prepare；连续至少 3 次 Start/Stop，每次可重新监听并释放麦克风，同时 VAD/ASR/NLLB 模型不因为 Stop 重载；非零字幕样本的中文、俄文、时间戳和尾部写盘通过；模拟引擎崩溃与重启后宿主显示正确；旧配置迁移可用。**只有无语音时进入 Listening 不等于识别/翻译通过。**

**禁止：** 将模型重新实现为 C# 服务或重写全部 Python core；一次性清除旧 GUI。

### Phase 6 — Windows 集成、离线安装与替换旧 GUI（未授权）

**范围：** 将宿主、React 构建产物、常驻 Python 服务及已验证的模型资源装入 Inno Setup；在真实 Win11 上验证安装/升级/卸载与完整用户流程。

**安装关注点：**

- 继续复用 `packaging/` 现有 CPU 离线资源/模型清单/分卷机制；无必要不重新下载或重新打包模型。
- WebView2 Runtime 要么使用已安装且验证可用的系统版本，要么在需要时通过**随包离线**的 Evergreen Standalone 安装器部署；不得要求首次联网。
- 明确宿主的 .NET 桌面运行时交付方式；所有真实依赖都应可离线满足。
- 不卸载用户字幕：默认 `%USERPROFILE%\ru-zh-live-subtitles\subtitles`；保护 `%LOCALAPPDATA%\ru-zh-live-subtitles` 中的用户设置、日志、模型缓存。**修正旧版 `[UninstallDelete]` 清空整个应用数据目录的问题。**
- 明确升级旧 v0.4.0 的偏好迁移与共存期；不破坏现有安装位置、资源或用户文件。

**最低验收矩阵：**

- [ ] 断网新 Windows 11 用户安装并启动，机器不需要开发环境、Python 或 Node。
- [ ] 软件启动时模型准备完成但麦克风未打开，Start 后实际 Listening。
- [ ] 俄语音频真实生成俄中字幕与完整时间戳 SRT。
- [ ] Stop 后麦克风释放、模型保留，重复 Start/Stop 不重复加载模型。
- [ ] 隐藏字幕、关闭设置、切换应用均不影响识别/SRT。
- [ ] 从托盘/任务栏/快捷键唤回；单实例与真正退出无残留进程。
- [ ] 正常/长字幕、中俄各一行、溢出跑马灯、字号、描边、独立 0% 透明度。
- [ ] 最小尺寸、DPI 缩放与真实窗口拖动/缩放/置顶；多屏若无环境，必须标为未验证。
- [ ] 引擎异常结束后的明确状态与可恢复行为；正常退出释放资源。
- [ ] 老用户偏好升级并保留旧文件；卸载不删除字幕/模型缓存/用户偏好。
- [ ] 新版确认可取代旧 Tk 后，才删除失效 GUI、旧构建入口及相关旧 GUI 测试（保留必要回归）；更新当前 README 与发行入口。

**验收标准：** 真实 Win11 和真实发行包已验证的行为才可勾选；最终一个可回滚 Git 提交 + 实际安装产物。不能把“编译通过”“700+ tests passed”当成全部完成。

## F. 避免工作偏离的操作规程

每次任务开始：

```text
1) 读 AGENTS.md + 本文件的 G（当前执行窗口）
2) git status；只查当期相关文件和既有实现
3) 只执行当期阶段中的一个任务切片
4) 最小改动 + 最小有效验证
5) 更新真实结果，必要时提交 Git
6) 阶段完成时停止，等待用户验收授权
```

遇到重复设计：优先复用或删去旧路径，不增加第三条实现。遇到不必要测试：停止并说明为何不需要。遇到无法原生实现的视觉效果：提交实际证据与最小备选，不自行改变既定路线。

## G. 当前执行窗口（只修改此处即可续接会话）

```yaml
plan_version: 1
baseline_commit: a5feb50d97581f8d13f1596255ff9f93a6b03d24
branch: feature/raycast-ui-rewrite  # 待创建
current_phase: 0
phase_status: not_started        # not_started | in_progress | blocked | awaiting_approval | accepted
approved_scope: phase_0_only
active_task: "确认工作区与分支；只读审计现有边界并记录一次可靠基线"
next_task: "在 Phase 0 内，整理 Phase 1 的 3–6 个任务切片；随后停止"
verified: []                    # 只填实际执行并有证据的结果
blockers: []
last_commit: null               # 仅填实际创建的本分支提交
```

> Codex 修改本段时保持简短、准确，不附会不存在的通过情况。完成 Phase 0 后应把 `phase_status` 置为 `awaiting_approval`，而不是自动把 `current_phase` 改成 1。

## H. 执行记录（仅保留阶段级事实）

| 日期 | 阶段 | 事实/证据 | 结论 |
| --- | --- | --- | --- |
| 2026-11-08 | 规划 | 按 `main@a5feb50d...` 核对仓库结构及关键源码，生成执行文件；未在仓库实施重构、未运行测试 | **仅规划完成，Phase 0 未开始** |

每个阶段最多补一条精简记录，必要证据引用 Git SHA、测试日志或截图实际路径；不复制大量输出到本文。

## I. 下一次发给 Codex 的唯一启动指令

> 阅读根目录 `AGENTS.md` 与 `REFACTOR.md`，严格执行 `REFACTOR.md` 的 Phase 0。先检查分支与未提交改动，保护 `main` 和旧 Tk 版本；核对源码真实行为、最小回归与迁移风险；只记录实际验证结果。在现有 `REFACTOR.md` 更新进度和 Phase 1 的 3–6 个任务切片。**禁止实施 Phase 1–6，禁止为了审计改动核心功能，完成 Phase 0 后停止等待我验收。**
