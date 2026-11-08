# REFACTOR.md — Windows 11 Raycast 风格 UI 迁移执行计划

> **状态：Phase 0、Phase 1 及 Phase 2 切片 1–3 已获用户验收；本轮仅授权切片 4，Diagnostics 模拟页面已完成，停止等待验收。切片 5–6 未实施，Phase 3–6 未授权。**
> 本文是本次迁移的**唯一活跃总计划与进度记录**，由 Codex 在各阶段结束时维护。
> 长期行为约束见根目录 `AGENTS.md`。不要新建第二份计划或重复的进度日志。

## A. 项目基线与真实现状

| 项目 | 基线 |
| --- | --- |
| 仓库 | `seren7350-ux/ru-zh-live-subtitles` |
| 开发基线分支 | `main` |
| 已核对源码提交 | `a5feb50d97581f8d13f1596255ff9f93a6b03d24` |
| 已核对版本 | `v0.4.0`（`pyproject.toml`） |
| 重构工作分支 | `feature/raycast-ui-rewrite`（已从上述基线创建；main 未改动） |
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
| 主题 | 以用户提供的四张设计参考图为最终视觉目标，尤其两张字幕悬浮窗；**中性、低色彩、半透明磨砂玻璃**，环境色来自背后内容，参考图中的蓝色主要来自壁纸，不是卡片自身的固定色偏；不仿制 macOS 标题栏/交通灯 |
| 圆角 | 目标 16–20 DIP，实际与 Windows 11 合成能力协同验证 |
| 背景 | 中性深灰或近黑半透明底，保留白色透明细边和柔和阴影；不得用高不透明度遮盖来假装磨砂。最终原生窗口背景材质 + WebView2 透明合成与真实桌面模糊仍须 Phase 3 在 Windows 实测 |
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
| **0** | 只读审计、隔离分支、旧版基线 | **已验收** | 用户于 2026-11-08 验收通过；既有基线缺口保留 |
| **1** | React 字幕悬浮窗 + 最小设计系统 | **已验收** | 用户最终验收通过（`96fc85f`）；不代表 Windows 原生宿主/引擎验收 |
| **2** | React 四页设置 + 三语 + 状态联动 | **切片 4/6 完成，待验收** | 切片 1–3 已验收，Diagnostics 固定模拟诊断展示完成，不继续下一切片 |
| **3** | WPF + WebView2 双窗宿主 | 未授权 | 原生窗口交互、透明合成实测；停止 |
| **4** | Named Pipes + JSON 合同 | 未授权 | C# ↔ 模拟 Python 服务可靠通信；停止 |
| **5** | 常驻 Python 引擎 + 业务迁移 | 未授权 | Start/Stop 模型复用 + SRT + 异常恢复；停止 |
| **6** | 端到端集成、用户验收、离线安装 | 未授权 | 在干净 Windows 离线运行的正式可交付包；停止 |

### Phase 0 — 保护基线与工程审计（已验收）

**允许：** 读取/分析已有代码、建独立 Git 分支、在本文件中更新真实审计结果、记录基线、执行一次合理的基线测试；必要时添加极少量只读验证脚本，但应优先使用现有命令。

**禁止：** 删除/迁移旧 GUI；改现有音频、模型、翻译、SRT；安装新 UI 栈；创建 UI 样板；顺手修 unrelated bugs；提前进入 Phase 1。

待办清单（未完成的项一律保持 `[ ]`）：

- [x] 检查 `git status`、确认 main HEAD 与基线提交；如有用户工作区改动，先避让。
- [x] 从当前 HEAD 创建/切换 `feature/raycast-ui-rewrite`；在该分支工作，不触碰 main。
- [x] 只读检查 GUI 事件/业务边界：`app.py`、`state.py`、`session_view.py`、`events.py`、`process_controller.py`、`shutdown.py`。
- [x] 检查模型与会话复用点：`OfflineAudioTranslationPipeline`、`LiveTerminalSession`、`LiveVadSession`、`SegmentProcessor`。
- [x] 检查模型资源预检、偏好 v1、SRT 保存、日志和用户数据路径。
- [x] 检查现有 `.github/workflows/tests.yml`、`tests/` 与打包/安装脚本，确定真正有用的回归集合。
- [x] 记录 Python 环境、Windows 运行条件、可实际执行的命令；**基线完整测试最多一次**，如成本/环境不允许则说明，不能声称已通过。
- [x] 给 Phase 1 写出最多 3–6 个连续任务切片，每个含完成标准和最小验证；不得在本阶段实施。
- [x] 更新本文「执行记录」及「当前执行窗口」；完成 Phase 0 后停止。

**通过条件：** main 保持原样；旧 Tk 版入口及功能不被本阶段修改；证据与缺口分开陈述；下阶段执行范围明确；可从 Git 找到安全回滚点。

#### Phase 0 实际审计与基线（2026-11-08）

- **保护与范围：** 初始工作区干净，HEAD 与 main 均为 `a5feb50d97581f8d13f1596255ff9f93a6b03d24`。两个 Downloads 文件已原样剪切至根目录并核对 SHA-256；规则导入提交为 `72200dd6abc1fa7ca1067888c1adbed31fb44b4d`。本阶段仅新增规则/计划及更新本文，未改 `src/`、`tests/`、`packaging/`、旧入口或历史文档；未安装依赖、下载模型、重建发行包。
- **GUI 边界：** `gui/app.py:502` 的 Start 先消费前一会话尾部，再创建新 SRT；`:646` / `:689` 负责事件、日志及写盘副作用。`state.py` 的有界历史与索引去重、`session_view.py` 的取消/晚到事件/错误保持、`events.py` 的全文与音频起止时间戳均可迁移复用；现有事件没有 `session_id`，不能直接作为新版 JSON 合同。`shutdown.py` 已封装 35 秒 terminate + 3 秒 kill，`app.py:603` 仍等 `shutdown_complete` 才销毁窗口；不能把发出停止请求当成资源释放。`single_instance.py`、`i18n.py` 的单实例唤回及三语语义保留，后续由宿主/前端接管。
- **模型/会话：** `pipeline/offline_file.py:131` 的 prepare 幂等，缓存同一 recognizer/translator；`realtime/live_subtitles.py` 已接受 `pipeline` / `vad` 注入，每次构造新 processor 与 VAD session。`vad_model.py:103` 缓存 ONNX session，`reset()` 仅重置循环状态；`live_vad.py:170` 每轮重置 VAD 并冲刷分段，`:280` 关闭采集和等待 worker；`segment_processor.py:447` 消费完整尾段再结束。`gui/process_controller.py:324` / `:602` 每次 Start 新建 pipeline、VAD 和 spawn 进程，尚非模型常驻。当前真实默认为 **GigaAM Multilingual large_ctc + NLLB**（`config.py:17` / `:25`），旧 GigaAM ONNX 仅可选兼容项；不改模型。
- **文件与数据：** `preferences.py:41` 读取 v1、校验字段，`:50` 使用临时文件及原子替换；旧 `window_rect` 校验最小 520×180，与新版 680×140 DIP 的设置映射需 Phase 5 明确。`subtitles.py:53` 保留音频时间轴、完整俄中内容、每 cue 关闭文件、去重及部分写入回滚。`runtime_paths.py:38` / `:53` / `:59` 的用户数据、日志、字幕路径已只读核对实际物理路径；未改用户偏好或字幕。复用 `diagnostic_logging.py:128` 的轮转/脱敏日志和 `model_assets.py:301` / `:369` 的本地预检/离线环境。`packaging/installer/cpu-only.iss:67` 确认仍整目录卸载删除，且模型由 `[Files]` 安装到该目录；Phase 6 要同时审查安装文件自身的卸载行为，保护缓存/偏好/日志并保留 AppId，本阶段不修。
- **环境与可运行入口：** Windows x64，build 26200.9711 / 25H2；现有两个 Python 均为 3.11.9。默认 Python 有 pytest 9.1.1，但无 huggingface-hub/torch/sounddevice；`.venv` 有 Torch 2.10.0+cpu、Transformers 5.14.1、ONNX Runtime 1.28.0、sounddevice 0.5.5，但无 pytest。`.venv\Scripts\python.exe -m live_subtitles --help` 与 `model-doctor` 均退出 0，三个必需模型的本地结构预检 READY，旧可选 ONNX 模型缺失；**未加载模型、未打开麦克风，不代表真实推理通过**。
- **一次完整基线：** 默认 Python，`PYTHONPATH=<仓库>\src`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`HF_DATASETS_OFFLINE=1`；命令 `python -m pytest -q -ra -p no:cacheprovider --basetemp <本任务临时目录>\pytest`。首次 **413 passed / 1 skipped / 306 errors，16.21 秒**：306 项均因执行命令漏建临时目录父级而 setup 失败。创建父级后，仅按 `retry-nodeids.txt` 补跑这 306 项，**304 passed / 2 failed，32.10 秒**；没有第二次运行全套。合计已通过 717 个不同用例，剩余 2 失败、1 跳过，**完整基线不宣称全绿**。
- **基线缺口与证据：** `test_clean_machine.py::test_staged_cache_resolves_pinned_revision_without_network` 缺 huggingface_hub；`test_gui_app.py::test_live_overlay_passes_cli_device_to_selector` 直接调用 `_live_overlay`，绕过 `cli.main` 的 `explicit_options`，受真实 v1 `microphone_name` 影响而回退默认设备；torch 用例因默认 Python 无 torch 跳过。仅记录环境/隔离问题，不改测试、用户配置或实现。证据位于 `output/verification/phase0-20261108/` 的 `pytest.log`、`pytest-setup-retry.log`、`retry-nodeids.txt`、`environment.log`、`runtime-environment.log`、`cli-help.log`、`model-doctor.log`；该目录按既有规则忽略，不作为发行资产。
- **最小回归与打包：** 后续按改动选择现有 `test_session_view` / `test_shutdown` / `test_gui_process_controller`（尾部、取消、进程异常），`test_offline_pipeline` / `test_live_terminal` / `test_live_vad` / `test_vad_model`（模型与会话），`test_subtitles` / `test_preferences` / `test_model_assets` / `test_diagnostic_logging`（数据及离线），发行阶段才用 packaging / installer / clean_machine 集合。参照 CI，22 个 Python/spec 文件内存编译、2 个 hook 导入、5 个 PowerShell 脚本语法检查通过；默认 Python 的 hook 导入先因缺 onnx_asr 失败，改用已有 `.venv` 后通过，见 `packaging-source-checks.log`。**真实旧 GUI 桌面交互、模型推理/麦克风、安装卸载、跨屏 DPI、新 UI 均未在本阶段验证**，历史文档中的结果不冒充本次结果。
- **临时文件保留：** 自动安全审查在执行前以 `blocked by policy` 拒绝本轮测试目录的递归清理命令；未完成清理，真实路径 `C:\Users\seren\.codex\cache\agent-temp\ru-zh-phase0-20261108-7f2c` 已核对且保留，见同证据目录 `cleanup.log`。未改用其他方式删除；诊断记录继续保留在项目中。

#### Phase 1 连续任务切片（5/5 已获最终验收）

| 切片 / 目标 | 允许改动模块 / 依赖 | 可观察完成标准 | 最小验证 |
| --- | --- | --- | --- |
| [x] 1. 最小前端与视觉基础 | 仅 `frontend/`；依赖用户授权 Phase 1；使用已锁定 React/TS/Tailwind/shadcn/ui/Motion | 本地启动一个字幕页面，统一颜色/字号/间距 tokens，只引入页面实际需要的组件 | 构建、类型检查、浏览器实际打开 Ready 状态；用户已验收（`2328255`） |
| [x] 2. 双语单行字幕与溢出 | `frontend/` 的独立字幕根组件/样式/固定 mock 与双 HTML 入口；依赖切片 1；材质以中性玻璃纠正为准 | 中性半透明卡片随环境呈色，中文在上俄文在下，字号固定；短句静止，仅超宽行横向跑马灯，保留全文；680×140 默认与 420×108 缩小可读；开发背景/说明不进入纯字幕界面 | 功能及材质最终验收通过（`3e386e5` / `6170b5c`） |
| [x] 3. 状态、切换与工具栏 | 同一视图和少量 mock 状态；依赖切片 2 | Ready/Loading/Listening/Stopping/Error 可复现，单层字幕淡入淡出，hover 工具栏、双击许可及键盘操作不冲突；保留中性材质与正文布局 | 构建/类型检查及浏览器验证通过；用户已验收（`d3054b6`） |
| [x] 4. 透明度与描边展示 | 同一视图及固定场景数据；依赖切片 3；不建四页设置 | 背景/文字独立 0–100%、隐藏俄文、可选黑描边均可演示，双重 0% 可用开发场景切回；不把 CSS 背景称为桌面毛玻璃 | 构建/类型检查及浏览器验证通过；用户已验收（`037922d`） |
| [x] 5. 浏览器模拟验收 | 仅完善上述页面与必要启动说明；依赖切片 1–4 | 固定场景可重复启动；完成 Phase 1 全部模拟状态的实际浏览器检查并在本文记录结果后停止 | 最终构建/类型检查及浏览器检查通过；用户最终验收通过（`96fc85f`），未验证 WPF/原生合成/IPC/Python |

切片 1 交付（2026-11-08）：

- 已检查仓库无既有前端；复用本机 Node 26.13.0 / npm 11.20.0，在 `frontend/` 建立 Vite + React 19.3.1 / TypeScript 7.0.2 / Tailwind 4.3.5 / Motion 14.10.1 最小工程，保留精确版本及 `package-lock.json`。仅引入并适配 shadcn/ui Badge，许可见前端第三方声明；未安装全套组件或测试框架。
- `src/styles.css` 集中颜色、字号、间距、圆角与阴影 tokens；`App.tsx` 只呈现深色静态 Ready 卡片和等待字幕占位，Motion 入口已接入但没有字幕切换动画。无会话控制、双语/溢出实现、设置、宿主、IPC、麦克风或 Python 接入，原有业务代码及 Phase 0 两项失败未改动。
- 启动：在 `frontend/` 运行 `npm ci`（首次或锁文件变更后），再运行 `npm run dev`，访问 `http://127.0.0.1:5173/`；开发服务仅监听回环地址。验证命令 `npm run build` 包含 `tsc --noEmit`，通过；`npm ls --depth=0` 无缺失/冲突。浏览器实际目视 Ready 页面、中文占位、深色 tokens；HTTP 200，捕获的 console warn/error 为空。证据 `output/verification/phase1-slice1-20261108/`：`build.log`、`dependencies.log`、`preview.log`、`browser.log`、`ready.jpg`；未运行 Python 测试。
- 验证后已停止本轮开发服务；保留 `node_modules/`、`dist/` 供本地继续开发，均被前端 `.gitignore` 排除。切片 2–5 及 Windows/真实引擎行为未验证；下一切片仍需用户续接，本轮停止。

切片 2 交付（2026-11-08，功能已获验收；材质以下述纠正为准）：

- **视觉与边界：** 先前误将参考图中的壁纸环境色固化到卡片主体，现已纠正为中性低色彩的半透明磨砂玻璃；保留 20px 圆角与静态蓝色小点。`components/SubtitleCard.tsx` 是唯一字幕根组件，只接受完整俄中文本及布局样式；默认 680×140，中文 28px/600 在上、俄文 20px/400 在下，字号不随文本或尺寸变化。没有复制或硬编码 Windows 壁纸，没有增加工具栏、状态机、设置或其他库。
- **独立入口与复用：** `subtitle.html` / `src/subtitle.tsx` 直接渲染同一根组件；`App.tsx` 仅为开发画布，原生示例/尺寸选择及背景说明均留在 `preview/`，纯字幕构建不引用预览入口或画布 CSS。保留既有 React/TS/Tailwind/shadcn/ui/Motion、Badge 与锁文件，未新增依赖、布局框架或全局状态。两个入口仅用于独立渲染与开发预览，不是两套字幕实现；当前文本仍来自固定 mock，Phase 3/5 才接宿主与引擎。
- **单行与滚动：** `components/MarqueeLine.tsx` 用 ResizeObserver 观察文字及可见宽度，每种语言独立测量；只对溢出行用现有 Motion 以 28px/s 往返，首尾各停 1.5 秒。短句无持续动画/轮询，不截短文本或改写 mock。换句/缩放重测并通过 Motion 同步清零缓存位移；浏览器曾发现长转短残留位移，已修正并回归通过。系统减少动态效果时改为可聚焦的原生横向读取，该系统偏好分支本轮未切换实测。
- **实际验证：** `npm run build`（含 `tsc --noEmit`）通过；生产预览 `npm run preview` 的 `/` 与 `/subtitle.html` 均 HTTP 200。浏览器验证双语短句静止、超长两行位移变化、中文短/俄文长独立判断、长转短及放大复位、俄文空字符串，以及 420×108 时字号不变且两行不发生垂直裁切；纯字幕入口无预览标题和控件，捕获 console warn/error 为空。证据 `output/verification/phase1-slice2-20261108/`：`build.log`、`http.log`、`browser-checks.json`、`standalone-short.jpg` / `standalone-long.jpg`（均 680×140）、`short-680.jpg` / `long-680.jpg`、`compact-420.jpg`。
- **未实施与停止：** CSS blur 仅是网页内合成，未验证 Windows 桌面透明合成；工具栏、复杂状态、透明度设置、字幕淡入淡出等留给后续切片。未改 Python/旧 GUI/用户文件，未运行无关 Python 测试，Phase 0 两项失败继续保留。验证后停止生产预览服务，保留被忽略的本地构建及诊断截图；提交并推送同名重构分支后停止，等待验收。

材质理解纠正（2026-11-08，本轮唯一授权工作）：

- `styles.css` 移除高不透明度的固定着色渐变，卡片改为 `rgba(18,18,18,0.45)`，即 45% 不透明度的中性底色；保留 `blur(24px)`、20px 圆角、白色 20% 透明边框及中性柔和阴影。蓝色只保留在状态灯/强调色，主体色随背景透入；未修改 SubtitleCard 或 MarqueeLine 的功能逻辑、字号/字重/尺寸/跑马灯，未新增依赖。
- 仅开发预览的 `App.tsx` / `preview/preview.css` 增加蓝色、灰阶、绿色/暖色三个背景及用于观察模糊的细线；不进入纯字幕构建、不使用 Windows 壁纸。`npm run build`（含类型检查）通过，实际生产浏览器在三背景上呈现不同环境色，三次 computed style 均为同一中性 45% 底色、无渐变、24px 模糊，排版仍为 680×140 与 28px/600、20px/400；console warn/error 为空。证据 `output/verification/phase1-glass-correction-20261108/`：`build.log`、`http.log`、`browser-checks.json`、`blue.jpg`、`mono.jpg`、`warm.jpg`。
- 这仅验证浏览器页面内的模糊和透明混合；Windows 桌面真实合成仍属于 Phase 3，由 WPF/WebView2/原生材质协同实现。本轮未引入宿主/Win32/框架，未执行 Python 测试，Phase 0 已知失败保留；已停止本轮预览服务，提交并推送同名分支后停止等待材质验收，不开始切片 3。

切片 3 交付（2026-11-08）：

- **状态与模拟职责：** `preview/useMockSession.ts` 是两个前端入口共用的唯一临时模拟会话逻辑，提供五种状态、600ms 准备与 350ms 停止反馈；开发选择器可固定任一状态供验收。`SubtitleCard` 接收状态/回调，指示灯及简短反馈统一显示。开始/停止/取消与错误重试可操作；置顶仅切换模拟标记，设置/更多仅显示明确入口反馈，没有原生置顶或完整设置界面；后续接真实宿主/引擎时替换 mock，保留同一字幕组件。
- **字幕与工具栏：** `SubtitleText.tsx` 只保留一组双语 DOM，约 60ms 淡出后替换，再约 100ms 淡入；被新字幕取代的回调会取消，避免旧字幕迟到及重影。沿用 MarqueeLine 的单行、独立溢出滚动与复位逻辑，仅把减少动画读取改为继承现有 MotionConfig 的系统/验证策略。工具栏绝对定位，离开缓冲 140ms、显隐过渡 120ms；双击空白切换显示许可，排除按钮和字幕文字及非空文字选区；本地 F2 恢复/切换、Escape 收起，Tab/Enter 可操作全部按钮，隐藏时 inert 且退出可访问树。这不是全局快捷键实现。
- **材质与紧凑尺寸：** 已验收的 `rgba(18,18,18,0.45)`、24px 网页内模糊、白色透明边框、20px 圆角及正文 28px/600、20px/400 保持不变。窄卡片仅收紧顶部工具栏，420×108 下控件不遮挡正文；工具栏显隐时正文仍在相同坐标。浏览器发现的空白换行选区误阻双击、小尺寸顶部遮挡均已局部修正并回归通过，未扩展透明度/描边设置。
- **实际验证：** `npm run build`（含类型检查）通过，两个生产预览入口 HTTP 200。浏览器验证五态、开始/停止/取消/错误重试、四按钮反馈、悬停离开/快速重入、文字选择及空白/按钮双击、本地 F2/Escape 与 Tab/Enter、5 次快速字幕更新的最后一条和单组 DOM、逐行跑马灯、420×108 不遮挡/不位移，以及独立纯字幕入口；console warn/error 为空。减少动画使用现有 MotionConfig 的预览强制策略验证同一路径，字幕即时替换、跑马灯停止自动移动且可用方向键读取全文、工具栏无过渡；未修改操作系统偏好。证据 `output/verification/phase1-slice3-20261108/`：`build.log`、`http.log`、`browser-checks.json`、`toolbar-card.jpg`、`listening-toolbar.jpg`、`error-toolbar.jpg`、`compact-toolbar.jpg`。
- **边界与停止：** 未新增依赖/框架/状态库，未接 WPF/Python/Named Pipes，未运行 Python 全量测试、未处理 Phase 0 已知失败。未做切片 4 的透明度/描边或其他未来功能；玻璃仍仅网页内合成，Windows 桌面合成留 Phase 3。验证后停止预览服务，保留被忽略的构建及诊断文件；提交并推送同名分支后停止等待验收。

切片 4 交付（2026-11-08）：

- **独立展示参数：** `SubtitleCard` 增加 `backgroundOpacity`（默认 45）、`textOpacity`（默认 100）、`showRussian`（默认 true）、`textOutline`（默认 false）props；百分比限制在 0–100，通过 CSS variables 传递。背景填充、细边、阴影和 24px 模糊集中到独立材质层，背景 0% 时整层不绘制，无残留色块；中性 `rgb(18 18 18 / alpha)` 随页面环境呈色，状态和工具栏不受两个透明度影响。
- **文字与复用：** 独立文字外层控制双语及描边透明度，原 `SubtitleText` 内层继续负责 Motion 淡入淡出，二者不争用 opacity；仅条件移除俄文行，中文由既有居中布局重新定位。可选黑色 1.5px stroke 以 `paint-order: stroke fill` 保留原字形填充，不使用模糊阴影；文字 0% 时连同描边消失。未重写淡入淡出、MarqueeLine 或模拟会话逻辑。仅开发预览增加两个百分比输入和两个开关；纯字幕入口仍用同一组件及默认参数，无预览控件或真实设置页面。
- **实际验证：** `npm run build`（含 `tsc --noEmit`）通过，两个生产预览入口 HTTP 200；浏览器分别操作背景/文字 0、50、100%，启用描边后文字 0% 无残留，双零仍可操作模拟置顶并从外部控件恢复；俄文隐藏后仅一行，680×140 与 420×108 均合理布局。短句静止、长句滚动、长转短复位、50% 文字下快速更新最终只有一组字幕且淡入层归 1、外层仍为 0.5；状态、F2/双击和工具栏离开回归通过，显隐不移动正文。蓝色、灰阶与暖色页面仍呈不同环境色，默认材质为中性 45%；两个入口 console warn/error 为空。证据 `output/verification/phase1-slice4-20261108/`：`build.log`、`http.log`、`browser-checks.json`、`background-{0,50,100}.jpg`、`text-{0,50,100}.jpg`、`both-zero-toolbar.jpg`、`neutral-outline-short.jpg`、`compact-chinese-only.jpg`、`compact-long-outline.jpg`。
- **边界与停止：** 未新增依赖，未改原业务、锁文件或 Phase 0 基线问题，未运行 Python 测试；仅验证页面内透明/模糊，Windows 桌面合成仍未验证，留 Phase 3。已停止本轮生产预览服务，保留被忽略的构建与诊断证据；检查提交范围及敏感信息后提交并推送同名分支，停止等待切片 4 验收，不开始切片 5 或 Phase 2。

切片 5 最终浏览器模拟验收（2026-11-08）：

- **结果与成本：** 复用切片 1–4 的固定示例、预览控件和既有浏览器工具，源码保持 `037922d` 不变。仅执行一次 `npm run build`（内含一次 `tsc --noEmit`），通过；生产预览 `/` 与 `/subtitle.html?sample=long` 均 HTTP 200。未新增测试框架、脚本基础设施、依赖或设置页；检查两个入口的组件/样式/模拟会话引用，未发现确定无用的重复实现或废弃临时代码，无需清理或功能修复。
- **实际浏览器链路：** Ready → Loading → Listening → Stopping → Ready、Error → 重试 Listening；悬停工具栏、四按钮反馈、文字双击选择、空白双击、本地 F2/Escape 与 Tab/Enter 均正常，显隐不移动正文。中上俄下、短句静止、超长双行滚动、中文短/俄文长独立滚动、快速更新最终单组 DOM、淡入完成及换句复位通过；680×140、420×108 工具栏不遮挡字幕。组合操作 50% 背景/文字、俄文隐藏、黑描边、双零恢复，以及蓝/灰阶/暖色环境呈色正常；0/50/100% 完整边界沿用切片 4 未变代码的实测证据，不重复建立测试。减少动画通过现有 MotionConfig 验证策略检查：字幕立即更新、自动位移停止、方向键可读取长句、工具栏无过渡，未修改系统偏好。两个入口 console warn/error 为空；独立入口无开发画布/控件，模拟开始及重新加载恢复 Ready 通过。
- **证据与复现：** `output/verification/phase1-slice5-20261108/` 保存 `build.log`、`http.log`、`browser-checks.json`，及 `default.jpg`、`long.jpg`、`hover-toolbar.jpg`、`error.jpg`、`compact.jpg` 五类代表截图，另有 `standalone-long.jpg`；切片 1–4 原证据继续保留。启动沿用切片 1：在 `frontend/` 首次执行 `npm ci`，运行 `npm run dev`；`http://127.0.0.1:5173/` 为开发场景，`http://127.0.0.1:5173/subtitle.html` 为独立字幕，可加 `?sample=long`。生产演示使用 `npm run build` 后 `npm run preview`，端口 4173；本轮预览服务验证后已停止。
- **未验证与停止：** 以上仅是 React 浏览器模拟。Windows 11 桌面透明/真实背景模糊、WPF/WebView2 合成、原生拖动缩放/DPI、实际置顶、任务栏/托盘唤回、全局快捷键及系统透明恢复须原生宿主阶段实测；Named Pipes、真实模型/麦克风/SRT 和发行行为未接入或验证。未运行 Python 测试，Phase 0 已知两项失败保留。Phase 1 标记完成但待用户最终验收；提交并推送同名分支后立即停止，不进入 Phase 2。

### Phase 1 — React 字幕窗口（已获用户最终验收）

**范围：** 构建 `frontend/` 的 React/TS/Tailwind/shadcn/ui/Motion 最小工程；一个能独立运行的字幕悬浮窗页面和同一套设计 tokens（不要建立庞大组件库）。

**模拟状态：** Ready、Loading、Listening、中俄正常字幕、超长字幕、错误、隐藏俄文、背景/文字 0%、描边、工具栏 hover、窗口尺寸变化。使用固定可复现 mock data；不联网、不读麦克风、不导入 Python。

**验收：** 真正的浏览器运行效果（不是概念图）；中文在上俄文在下；短句无滚动、长句仅横向滚动；过渡自然、交互状态有反馈；可在开发环境重复启动并演示。浏览器级模拟缩放**不等于** Windows 窗口拖动/透明合成验收。

**禁止：** 建 WPF 宿主、真正的 Named Pipes 或 Python 模型接入；无边界扩展设置页。

### Phase 2 — React 设置窗口（仅模拟，本轮仅切片 4）

**范围：** Input、Subtitles、Window、Diagnostics 四页；复用 Phase 1 的视觉 tokens 和 UI 组件，做即时状态联动与中/英/俄翻译字典。

**验收：** 状态改变能在真实渲染的模拟字幕窗看到；三语切换后导航、按钮、状态、错误、动态字段不漏翻；键盘焦点与小尺寸滚动可用；无需设置内重复预览；重置仅影响当前页。模拟持久化/跨进程能力不得宣称已完成。

**禁止：** 提前重做 Python 偏好、引擎或系统级快捷键。

#### Phase 2 连续任务切片

以下为执行顺序，**切片 1–3 已验收，本轮仅切片 4 已授权；未来计划不构成实施许可，每个切片完成均提交、检查并推送同名分支后停止等待验收。**

| 切片 / 目标 | 允许改动模块 / 依赖 | 可观察完成标准 / 最小验证 |
| --- | --- | --- |
| [x] 1. 设置基础布局与 Input | `frontend/` 设置入口、基础导航、Input 与开发联动场景；依赖 Phase 1 已验收 | 四页导航、Input 模拟联动及浏览器验证通过；用户已验收（`033a072`） |
| [x] 2. Subtitles 页面 | 设置视图与开发联动参数；依赖切片 1 验收及新授权 | 固定字号与四项既有外观参数联动、浏览器边界/重测/紧凑布局通过；用户已验收（`aa98d4b`） |
| [x] 3. Window 页面 | 同一设置视图及必要 mock；依赖前序验收及新授权 | 既定选项模拟、反馈/保留、浏览器键盘/宽度检查通过；用户已验收（`3d4ac5d`） |
| [x] 4. Diagnostics 页面 | 同一设置视图及固定诊断数据；依赖前序验收及新授权 | 未发布演示信息、模型/日志/错误模拟及按钮反馈完成；构建、浏览器状态一致/键盘/宽度/保留检查通过，待验收；未读取真实数据 |
| [ ] 5. 三语与分页面重置 | 四页已实现字段与少量翻译字典；依赖前序验收及新授权 | 中/英/俄即时切换不漏动态字段，每页重置确认默认否且只影响当前页；构建、三语/键盘/重置联动检查 |
| [ ] 6. 设置浏览器模拟验收 | 仅必要修复与启动说明；依赖前序验收及新授权 | 两入口与全部既定场景可重复演示，复用既有证据完成关键链路、宽度/键盘/三语检查后停止；不宣称原生/跨进程/持久化已完成 |

切片 1 交付（2026-11-08）：

- **入口与视觉：** `settings.html` / `src/settings.tsx` 独立挂载 `settings/SettingsWindow.tsx`，默认 Input；左侧固定四项导航，右侧可滚动内容，其他三页仅明确占位。沿用现有字体、颜色/圆角 tokens、shadcn Badge 与 Motion，局部样式仅扩展中性 `#1b1b1c` 表面和低对比度分隔，选中项为克制的中性强调；120ms 淡入尊重减少动画偏好。未硬编码蓝色壁纸、复制字幕实现或新增依赖/路由/状态框架。
- **Input 与共享会话：** `InputPage.tsx` 提供三个固定模拟麦克风、刷新反馈、三项模型状态、开始/取消/停止/重试；运行期间锁定设备选择，切页保留当前选择与会话。`/?view=settings` 为开发联动场景，沿用 App 中唯一的 `useMockSession` 实例，将同一 status/callback 同时传给 SettingsWindow 与窗口外的原 SubtitleCard，双向控制可见；独立设置入口复用同一 hook，无第二套会话逻辑。独立窗口内没有字幕预览，其他浏览器标签页间未建立同步或持久化。
- **实际验证与修复：** 初次 `npm run build`（含类型检查）通过；浏览器发现独立入口外层 Grid 最小轨道导致窄窗横向溢出，仅修正为 `minmax(0, 1fr)`，进行一次必要的重建/类型检查与定向复测，均通过。浏览器验证四项导航及占位、麦克风选择/刷新、切页保留、开始/停止/取消/错误重试、设备锁定、设置与字幕五态一致、字幕反向停止；独立入口 360/1100px、联动预览 420/760/1100px 无横向溢出，窄屏内容纵向可读，console warn/error 为空。原字幕预览仍为 680×140、中文 28px/600、俄文 20px/400、中性 45% 材质；字幕组件/动画/样式、mock hook、锁文件和业务代码未改。四个入口/场景均 HTTP 200。
- **复现与边界：** 沿用 `frontend/` 的 `npm run dev`；`/settings.html` 是独立设置界面，`/?view=settings` 是开发联动场景，生产预览端口仍为 4173。证据 `output/verification/phase2-slice1-20261108/`：`build.log`、`build-after-layout-fix.log`、`http.log`、`browser-checks.json`、`settings-default.jpg`、`input.jpg`、`input-subtitle-listening.jpg`、`settings-narrow.jpg`。已停止预览服务；没有真实麦克风/模型/Python/IPC/WPF 接入或配置持久化，未运行 Python 测试，旧 Tk 与 Phase 0 两项基线失败保留。更新本文、检查提交后提交并推送重构分支，停止等待切片 1 验收，不实施切片 2。

切片 2 交付（2026-11-08）：

- **页面与单一参数来源：** 新增 `settings/SubtitlesPage.tsx` 与六字段 `subtitleAppearance.ts` 默认值；中文固定 18–32px（默认 28）、俄文固定 12–22px（默认 20），输入取整且限制范围，不随文本长度缩放；其余默认沿用显示俄文、背景 45%、文字 100%、描边关闭。`SettingsPreview` 共同父级持有一份展示参数，设置页和原 SubtitleCard 共用；四个既有外观 props 原样传入，字号通过既有 style/CSS variables 设置，无须扩展 SubtitleCard 接口。独立设置入口在自己的共同父级保存同一结构，仅内存保留；切换页面不重置，不跨浏览器页面同步或持久化。
- **复用与实际验证：** SubtitleCard、SubtitleText、MarqueeLine、全局字幕样式、Input 页面及模拟会话逻辑均未修改；只增加 Subtitles 作用域样式，开发场景复用固定示例和尺寸选择来验证长句与 420×108。一次 `npm run build`（含 `tsc --noEmit`）通过，四入口/场景 HTTP 200。浏览器验证中俄字号独立即时更新及上下限、俄文隐藏后居中、独立 0/50/100% 不透明度、黑描边开关、双零后从设置恢复；长句滚动中仅修改一行字号，该行文字宽度重测且归零，另一行继续滚动，换回短句静止。最大字号 32/22px 配描边与工具栏在 420×108 无新增遮挡；Input/Subtitles 往返六参数保留，独立设置入口也保留值，窄页无横向溢出，console warn/error 为空。未发现需修改字幕布局或动画的缺陷。
- **证据、截图上传与停止：** 本轮生成的全部 9 张实际界面 JPEG 放在 `docs/screenshots/phase2-slice2-20261108/`，按用户要求随本次提交上传 GitHub，后续统一处理，不改变原有产物忽略规则；其中含默认页、独立字号、背景 0%、双零恢复、最大字号紧凑工具栏、隐藏俄文、长句重测、最终联动和独立设置入口。构建/HTTP/浏览器指标保留在被忽略的 `output/verification/phase2-slice2-20261108/`。沿用 `/settings.html` 与 `/?view=settings`，验证后已停止预览服务。无新增依赖、状态框架、三语、原生/IPC/引擎接入或 Python 测试，旧 Tk 和 Phase 0 已知失败保留；Window/Diagnostics 仍占位。检查后提交并推送同名分支，停止等待切片 2 验收。

切片 3 交付（2026-11-08）：

- **Window 页面与边界：** 新增 `settings/WindowPage.tsx`，复用既有 SettingsWindow、tokens 和分组样式；SettingsWindow 局部 state 保存置顶、无边框、工具栏许可、X/Y/宽高、四项快捷键及 SRT 开关，切页保留。位置/尺寸默认 `(120,120)` / `680×140` DIP，仅记录整数模拟值；快捷键为开始停止、字幕显示隐藏、打开设置、切换置顶，各提供两种候选组合或未设置。各组反馈随值更新，明确未注册快捷键、未检查系统占用、不改变真实窗口或当前字幕工具栏。SRT 只展示固定模拟路径 `C:\Demo\Subtitles`，不读取目录或写文件；未建立假窗口管理器、第二套全局状态或扩展 SubtitleCard。
- **实际验证与修复：** 初次 `npm run build`（含类型检查）通过；浏览器发现 360px 下新页面 Grid 最小轨道被下拉框撑宽，仅在 Window 作用域设 `minmax(0,1fr)`，一次必要重建/类型检查及定向复测通过。12 个值均可修改、反馈一致，Input/Subtitles 往返全部 Window 值保留；Space 切换、方向键配置下拉框/数字和 Tab 焦点移动实测通过。修复后 360/420/760/1100px 无横向溢出，可纵向滚动。Input 模拟设备/开始停止、Subtitles 参数保留及原字号范围回归正常；修改 Window 模拟尺寸/工具栏许可后字幕仍为 680×140、中性 45% 材质。两个设置场景 console warn/error 为空，四入口/场景 HTTP 200。字幕组件、Input/Subtitles 实现与范围、共享 mock、依赖及旧业务未改；未运行 Python 测试，Phase 0 已知失败保留。
- **证据与停止：** 三张代表性截图 `docs/screenshots/phase2-slice3-20261108/01-window-options.jpg`、`02-shortcuts-srt.jpg`、`03-window-narrow.jpg` 随本轮提交上传 GitHub；构建/HTTP/浏览器指标及修复前诊断截图保留在被忽略的 `output/verification/phase2-slice3-20261108/`。已停止生产预览服务，无原生置顶/无边框/拖动缩放/任务栏/全局快捷键、SRT 写入或持久化实现；这些真实能力留给后续已规划阶段。提交并推送同名分支后停止，等待切片 3 验收，不进入 Diagnostics 切片。

**字号迁移待办（Phase 5）：** 旧 `preferences.py` / `gui/state.py` 允许中文 16–72（默认 34）、俄文 10–48（默认 20），新版当前 CSS 字号范围为中文 18–32、俄文 12–22。迁移时须明确单位/DPI、越界值与默认值的处理并保留原配置，不可静默套用新上限；本轮仅记录，不修改任一版本字号设置。

切片 4 交付（2026-11-08）：

- **范围与复用：** 新增 `settings/DiagnosticsPage.tsx`，复用 SettingsWindow、模型列表/按钮/分组样式和中性 tokens。展示应用名称、未发布 UI demo 版本说明、直接来自既有 useMockSession 的会话状态；Silero VAD、GigaAM、NLLB 的名称/用途及“未加载（模拟）”。固定目录 `C:\Demo\Logs`、两条相对时间示例记录及 Error 状态下的固定错误均明确标注模拟；不读取日志或模型服务。三个操作按钮只更新一份局部反馈，状态改变后不残留上一状态错误详情，不生成文件、打开目录或运行外部程序。
- **验证：** 一次 `npm run build`（含 `tsc --noEmit`）通过，四入口/场景 HTTP 200。实际浏览器验证 Input 开始后 Diagnostics/字幕均为 Listening、正常无错误、Error 详情与额外示例记录、回到 Ready 清除旧反馈；三个按钮 Enter 操作有反馈且焦点可见。切页后 USB 输入、中文字号 30、Window 宽度 800 均保留；360/420/760/1100px 内容无横向溢出，console warn/error 为空。未发现需修复的问题，未新增测试框架或依赖，未运行 Python 测试；Input/Subtitles/Window、字幕组件/动画/跑马灯、会话 hook、旧业务及字号范围均未改。
- **证据与停止：** `output/verification/phase2-slice4-20261108/` 保留构建/HTTP/浏览器记录；三张代表截图 `docs/screenshots/phase2-slice4-20261108/01-diagnostics-normal.jpg`、`02-diagnostics-error.jpg`、`03-diagnostics-narrow.jpg` 随提交上传 GitHub。已停止预览服务；真实日志/模型监控、错误恢复、导出、原生目录及文件系统/IPC 尚未接入。Phase 0 基线问题及字号迁移待办保留；提交并推送后停止，不实施切片 5–6 或 Phase 3–6。

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
branch: feature/raycast-ui-rewrite
current_phase: 2
phase_status: awaiting_approval  # 本轮仅完成 Phase 2 切片 4，等待验收
approved_scope: phase_2_slice_4_only
active_task: "Diagnostics 固定模拟诊断与操作反馈已完成；停止等待验收"
next_task: "等待切片 4 验收和新授权；随后才执行切片 5：三语与分页面重置"
verified: ["切片 1–3 已验收，旧 Tk、字号迁移待办及 Phase 0 已知失败保留", "一次构建/类型检查通过，四入口/场景 HTTP 200", "浏览器会话一致、正常/错误及反馈清除、三个按钮键盘响应、其他页面参数保留、360–1100px 通过，console warn/error 为空", "原字幕/Input/Subtitles/Window/mock 及依赖未改，3 张代表截图随提交上传", "无真实日志/模型/文件系统/原生/IPC 接入或 Python 测试；切片 5–6 未实施"]
blockers: [] # Phase 0 的环境/测试隔离缺口仍见上述原记录，不阻碍本切片
delivery_policy: "按用户持续授权：更新本文、提交、检查敏感信息及产物后 push 同名分支；不合并 main；每切片结束立即停止"
last_commit: 3d4ac5d2c06cf287ff598937ea67457248148673 # 本轮记录写入前提交；本轮交付提交由 git log -1 -- frontend REFACTOR.md 查询
```

> Codex 修改本段时保持简短、准确，不附会不存在的通过情况。完成 Phase 0 后应把 `phase_status` 置为 `awaiting_approval`，而不是自动把 `current_phase` 改成 1。

## H. 执行记录（仅保留阶段级事实）

| 日期 | 阶段 | 事实/证据 | 结论 |
| --- | --- | --- | --- |
| 2026-11-08 | 规划 | 按 `main@a5feb50d...` 核对仓库结构及关键源码，生成执行文件；未在仓库实施重构、未运行测试 | **仅规划完成，Phase 0 未开始** |
| 2026-11-08 | Phase 0 | 从指定基线建分支，剪切导入两文件（`72200dd`）；仅审计与更新本文。一次全量 413 通过/1 跳过/306 setup 错误，修正命令目录后仅补跑错误子集 304 通过/2 失败；证据 `output/verification/phase0-20261108/`。资源预检、CLI 及打包源检查通过，五个 Phase 1 切片未实施 | **审计完成，基线缺口已明示；停止待验收，Phase 1–6 未授权** |
| 2026-11-08 | Phase 1 | 五个切片及最终浏览器模拟检查完成，用户已最终验收（`96fc85f`）；证据 `output/verification/phase1-slice5-20261108/` 及前序切片目录保留。Windows 原生宿主/真实引擎仍未验证，Phase 0 已知失败未改 | **Phase 1 已验收** |
| 2026-11-08 | Phase 2 | 切片 1–3 已验收；本轮切片 4 完成 Diagnostics 固定模拟展示及按钮反馈，复用现有会话状态；构建/类型检查及浏览器正常/错误、键盘、参数保留、360–1100px 验证通过，指标见 `output/verification/phase2-slice4-20261108/`，3 张截图见 `docs/screenshots/phase2-slice4-20261108/`。未改已验收页面/旧业务，无真实诊断接入 | **切片 4 完成，待验收；切片 5–6 未实施，Phase 3–6 未授权** |

每个阶段最多补一条精简记录，必要证据引用 Git SHA、测试日志或截图实际路径；不复制大量输出到本文。

## I. 下一次发给 Codex 的唯一启动指令

> 当前 Phase 1 及 Phase 2 切片 1–3 已验收，切片 4 完成后已停止。仅在用户新授权后阅读规则、检查分支和改动，执行下一个获授权切片（候选为三语与分页面重置）；保护既有字幕、页面与旧业务，按范围验证、更新本文、提交并检查敏感信息/产物后 push 同名分支，再停止。**不自动执行切片 5–6，不提前进入 Phase 3–6，不合并或推送 main。**
