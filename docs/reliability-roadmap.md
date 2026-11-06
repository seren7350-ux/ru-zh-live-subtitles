# 老师反馈修复目标

本轮从 v0.3.0 源码开始。2026-11-04 完成目标 1、2、3，2026-11-05 完成目标 4 的源码修改及回归验证。四个目标均已完成源码交付，现有发布安装包仍为 v0.3.0，尚未重建。

| 目标 | 范围 | 验收重点 |
|---|---|---|
| 1：诊断与异常恢复 | 持久化脱敏错误堆栈、引擎异常退出检测、GUI 状态恢复、退出超时清理 | 引擎意外退出后可再次 Start；日志记录错误详情和退出码；回调异常后仍处理停止事件；关窗前确认后台已结束 |
| 2：窗口可找回 | 无边框保留任务栏、单实例与再次启动唤回 | 普通/无边框切换、Alt+Tab、全屏演示切换、重复启动 |
| 3：字幕显示和保存 | 单行显示、仅溢出时横向跑马灯、SRT 增量保存 | 不出现半行裁切；SRT 使用语音起止时间，不使用翻译完成时间 |
| 4：操作和视觉 | 字幕区任意位置拖动、双击工具栏、独立背景/文字透明度、黑色描边 | 缩放/拖动/按钮不冲突；透明度到零仍能找回设置 |

目标 3 的显示规则已由用户确认：保留双语，俄文和中文各占一行。

## 目标 1 的实现

- 源码 GUI 与无控制台入口都启用轮转诊断日志。日志保存完整异常链和堆栈，带进程、线程和会话信息；格式化后统一脱敏用户路径、令牌和调用方已知的字幕文本，不收集局部变量或录音。
- GUI 日志为 `application.log`；工作进程使用 `worker-<父进程PID>.log`，同一次应用运行中的多次 Start 复用该文件，避免父子进程竞争同一轮转文件。每个日志族为当前文件和两份备份，每份上限约 1 MiB。不同应用运行的工作日志会保留，供排查旧会话。
- 工作进程通过单向管道传递事件。父进程专用接收线程把完整消息放入有界本地队列，Tk 只消费本地队列；强制结束引擎时，半条管道消息不会阻塞 Tk。
- 父进程监测引擎退出，并在接收线程收齐尾部事件后记录退出码。没有正常结束事件的退出也视为异常。下一次 Start 使用新的进程和通信通道。
- 致命错误不会被后续积压字幕或普通停止事件清掉。工作进程实际退出后恢复 Start；明确点击 Start 重试时允许显示新的模型或麦克风检查错误。
- GUI 轮询在回调失败时仍安排下一次执行。Exit 先请求正常停止；35 秒后仍未退出则 terminate，再等 3 秒仍存活则 kill。界面继续轮询，确认引擎退出和尾部事件处理完毕后才销毁窗口。

## 目标 1 的验证边界

Windows 上运行全套 pytest，572 项通过。一个使用 PyTorch 的识别模型测试因验证环境未安装 torch 而跳过。回归用例涵盖无控制台日志、异常链脱敏、多个工作线程同时写入管道、GUI 回调失败、意外退出、重启、退出超时和最后一批事件处理。

另用真实 Tk 8.6 窗口和 Windows spawn 子进程演练故障，在隐藏窗口中操作实际按钮。第一个测试进程以退出码 17 意外退出，界面显示该退出码并恢复 Start。再次点击 Start 后，第二个进程送达合成字幕。点击 Exit 后，第二个进程以 0 退出，主循环结束时活动子进程和管道接收线程均为 0。应用整次运行返回 2，保留首次故障记录。

目标 1 的验证使用合成输入；当时将真实麦克风和模型测试、安装包重建以及老师报告的任务栏切换场景留给后续验证。目标 2 的窗口验证结果续在下文。

原生库崩溃可由父进程记录非正常退出码，但当前不生成 Windows 崩溃转储；日志不能保证还原所有原生故障的调用栈。

## 目标 1 留存清单

2026-11-04 只读复核了上轮任务目录 `%USERPROFILE%\.codex\cache\agent-temp\subtitle-goal1-20261104`。自动安全审查对下表三个目录涉及的 PowerShell 清理命令返回 `blocked by policy`。路径均相对于上轮任务目录。

| 明确被拒绝清理的目录 | 用途 | 普通文件 | 目录 | 重解析点 | 普通文件字节数 |
|---|---|---:|---:|---:|---:|
| `process-concurrency/ba482f06e3ff4862b9cf4fde3ae35289` | 并发测试、pytest 链接和两份去除写锁的反证副本 | 16 | 71 | 38 | 52,319 |
| `verify-venv` | 全套回归测试使用的临时 Python 虚拟环境 | 2,349 | 262 | 0 | 47,108,347 |
| `final-verification` | 首次最终验证留下的空目录 | 0 | 1 | 0 | 0 |
| **合计** | **2,737 个目录项** | **2,365** | **334** | **38** | **47,160,666** |

另外七个测试目录也继续留存：`final-verification-b`、`full-verification-a`、`lifecycle-resume-1`、`logging-resume-1`、`logging-test-1`、`root-resume-1` 和 `root-resume-2`。它们合计 3,680 个普通文件、3,320 个目录和 465 个重解析点，上轮没有对这些目录重新申请清理。`tk-e2e` 中的 4 个普通文件和 5 个目录作为 Windows 窗口冒烟测试证据保留。

逐项清单保存在项目的 `output/maintenance/goal1-retained-inventory.json`。其中 `retention = denied_target_tree` 标识上表三个目录及其内容。完整清单覆盖 10,212 个目录项，包括容纳并发测试的 `process-concurrency` 父目录。目录数含各组根目录，普通文件按逻辑长度计数。重解析点记录自身路径和类型，不遍历其目标。

## 目标 2 的实现

- Windows 主字幕窗口在普通和无边框模式下都注册为任务栏应用窗口。每次映射及切换边框后重新取得 Tk 当前的原生窗口句柄，保留透明度、置顶等已有样式，并补齐无边框窗口的最小化能力；不增加标题栏或边框。设置面板仍属于主窗口。
- 同一 Windows 用户、同一登录会话内，重复启动实时字幕界面会请求原窗口显示。选举发生在创建控制器前，第二次启动不会创建第二个 GUI 或启动另一套引擎。演示模式使用独立实例，方便调试。
- 唤回请求由原窗口的 Tk 线程处理。第二个启动进程收到对应实例的接收确认后退出；原实例在确认前关闭或崩溃时，等待中的启动可以接替。GUI 检查请求时不等待其他进程持有的锁。
- 唤回会恢复隐藏或最小化的窗口，保留当前字幕、设置和引擎会话；Windows 拒绝切换前台时请求任务栏按钮闪烁。日常字幕渲染不会主动切换前台或恢复最小化窗口。

## 目标 2 的验证与交付边界

Windows 全套 pytest：**593 项通过、1 项跳过**。跳过项仍为验证环境未安装 PyTorch 的识别模型测试。回归覆盖多进程同时启动、主实例关闭/崩溃、启动超时、唤回失败后继续轮询、边框切换时使用当前原生句柄，以及保留窗口原有样式和最小化状态。

真实 Tk/Windows 验证包含 30 个原生状态快照、5 轮模式状态和 4 次边框切换：同一 GUI 进程和 Tk 内容窗口持续存在；通过原生系统命令最小化/恢复，窗口位置和尺寸保持，设置面板继续归属于当前主窗口，普通字幕更新不会恢复已最小化窗口。

使用实际 CLI、跨进程实例选举和 GUI 轮询，分别验证隐藏、最小化、全屏窗口覆盖和前台切换被拒绝的场景。第二次启动在原 GUI 确认请求后返回，未初始化第二个 Tk、控制器或工作进程；原字幕会话继续产生合成字幕。覆盖场景使用本次创建的全屏测试窗口。焦点拒绝场景注入 `SetForegroundWindow` 失败，观察到实际 `FlashWindowEx` 调用。测试进程均已退出。

Explorer UIA 记录确认，在初始无边框、设置面板开关和边框切换的可见阶段，任务栏只有一个运行窗口入口。该记录早于补齐最小化样式的最后补丁；补丁后验证了原生最小化/恢复命令，**尚未复测直接点击 Explorer 任务栏按钮或键盘 Alt+Tab**，也未验证任务栏闪烁的视觉动画。

验证摘要、原生窗口快照、两组重复启动结果、Explorer 记录以及完整 pytest 输出保存在项目 `output/verification/goal2/`；`evidence-manifest.json` 记录证据来源和文件 SHA-256。测试脚本及诊断原始记录继续保留在本轮任务目录，上轮被拒绝清理的内容保持留存，本轮未再次尝试删除。

目标 2 完成源码交付；现有 v0.3.0 安装包尚未重建。本轮使用合成字幕，未加载真实麦克风或模型。安装版、实际演示软件及上文明确列出的桌面交互仍需交付时实测。目标 3、4 尚未开始。

## 目标 3 新增留存清单

2026-11-04，本轮两次显示测试生成了空的模型设置测试目录和 pytest 链接。对这些已核对归属的目录项执行非递归 PowerShell 清理时，自动安全审查返回 `blocked by policy`。没有删除成功，也没有更换工具或再次尝试删除。

以下路径相对于 `%USERPROFILE%\.codex\cache\agent-temp\pytest-of-seren`：

| 被拒绝清理而保留的路径 | 目录 | 重解析点 | 普通文件/字节 |
|---|---:|---:|---:|
| `pytest-2` 及其内部测试目录/链接 | 3 | 2 | 0 / 0 |
| `pytest-3` 及其内部测试目录/链接 | 3 | 2 | 0 / 0 |
| `pytest-current`（指向 `pytest-3`） | 0 | 1 | 0 / 0 |
| **合计 11 个目录项** | **6** | **5** | **0 / 0** |

逐项清单为 `output/maintenance/goal3-display-retained-inventory.json`，记录各目录项和链接目标。此前目标 1 的留存内容和清单保持不变。本轮后续测试使用专用任务目录及 pytest 自动清理策略；测试脚本、输出和验证快照作为诊断证据保留。

## 目标 3 的实现

- 字幕区域显示最新一条双语字幕，俄文、中文各占一行；输入中的换行和连续空白折叠为空格，取消纵向历史滚动。短句静止，只有超出实际可用宽度的语言行才横向移动，首尾各停留 1.2 秒。新字幕、字号或窗口尺寸变化时重新测量，普通 GUI 轮询不会重置动画。
- 根据 Tk 实际文字边界及 DPI 适配字号，保证两行完整显示。窗口高度增加后恢复设置字号；最小字号仍放不下时调整窗口最小高度，不绘制半行文字。Clear 或销毁窗口时取消动画。
- 每次成功 Start 新建唯一 UTF-8 SRT，按俄文、中文顺序逐条写入并关闭文件。保存路径默认是 `%USERPROFILE%\ru-zh-live-subtitles\subtitles`，位于现有卸载程序的清理范围之外。Settings 显示当前文件并提供 `Open subtitles folder`；命令行可用 `--srt-dir` 指定目录。
- SRT 起止时间来自音频片段采样位置，保留开头静音、句间间隔及片段重叠，完全独立于识别或翻译完成时间。时间轴以本次采集的第一个采样点为零，包含 VAD 的预滚和补白；不是逐词强制对齐。
- Clear、隐藏俄文、停止及异常退出不删除已保存字幕。重启前处理上一会话的尾部事件，再建立新文件和新编号。保存失败时保留已有完整内容、尽可能撤回未完成的一条，并持续显示提示；字幕继续运行，Stop/Start 新建文件后重试。正常进程退出或崩溃后已关闭文件中的内容可保留，不承诺断电或文件系统故障下的数据持久性。

## 目标 3 的验证与交付边界

Windows 最终全套 pytest：**625 项通过、1 项跳过**。唯一跳过项仍是验证环境没有安装 PyTorch 的识别模型测试。

自动回归覆盖单行空白规范化、临界宽度、独立语言溢出、动画取消、窗口缩放与字号变化、双语 SRT 精确时间、去重、快速重启尾部事件、保存失败及清空显示后的文件保留。另用子进程在写入后立即 `os._exit(17)`，确认无需正常关闭流程也能读取已完成的字幕条目。

真实 Tk 验证包含 13 个窗口快照、9 组场景，以及 3 档 Tk 缩放下的 9 组布局压力场景。确认短句静止、仅溢出行移动、加宽后停止动画、最小窗口和最大字号下两行完整显示、俄文开关、边框往返、Clear/去重、按音频时间保存及重启保留旧文件。加入保存失败提示、模拟麦克风和模型控件后，当前 1440 像素高桌面上的设置按钮均可见，包括 Exit。

验证摘要、窗口/布局快照、完整 pytest 输出和两份合成 SRT 示例保存在 `output/verification/goal3/`；`evidence-manifest.json` 记录来源和 SHA-256。10 个生产文件在真实窗口验证前后哈希一致，并与最终源码匹配。Computer Use 截图已目视检查双语单行及完整设置面板；截图仅在工具内展示，没有保存图片文件。所有测试窗口和进程均已退出。

本轮使用合成字幕和模拟设备/模型状态，未加载真实麦克风或识别模型，未重建安装包。设置布局结果限于所测桌面尺寸；现有发布安装包仍为 v0.3.0。目标 4 的任意位置拖动、工具栏双击、独立透明度和描边尚未实施。

## 2026-11-05：测试窗口遗留反馈的澄清

用户反馈上一轮结束后屏幕上仍有跑马灯测试窗口，原意是关闭遗留测试窗口。助手曾误解为取消功能，随后用户重申老师要求，现以该要求为准：保留“仅文字溢出时跑马灯”，取消纵向历史滚动；每种语言各占一行，完整内容保存 SRT。

目标 4 继续实施拖动、双击工具栏、独立透明度及描边，并在最终验收中复核跑马灯条件和测试窗口退出。前述临时删除跑马灯的修改不作为交付行为。

## 目标 4 的实现

- 字幕文字、空白区、状态文字和工具栏非按钮区域都可拖动窗口，移动超过 4 像素才开始改变位置。无边框边缘和四角优先缩放；按钮、滑块和选择框保留原来的操作。
- 双击字幕区域或工具栏空白处隐藏/恢复底部工具栏；Settings 和 Ctrl+H 也提供开关。会话开始、停止和普通字幕更新不重置该选择。
- Windows 背景与文字使用分别控制的原生透明度，范围均为 0–100%。主窗口承载背景与工具栏，所属的透明文字窗口承载字幕；文字层不增加任务栏入口，不主动激活前台。Settings 始终保持不透明。
- 黑色描边可在 Settings 开关，与文字共用透明度并同步参加跑马灯移动。短句保持静止，只有超宽语言行横向移动；保留双语每种语言一行及 SRT 增量保存。
- 完全透明或工具栏隐藏时，再次启动、重新显示窗口或后续主窗口激活可打开 Settings；恢复入口不重置用户的透明度选择。关闭 Settings 后，返回主窗口的那一次焦点事件不会立即重开面板。
- 文字层随主窗口移动、缩放、最小化、置顶和边框切换。边框变化前解除旧原生窗口的所属关系，随后绑定当前窗口；主窗口关闭时销毁文字层并取消字幕计时器。

## 目标 4 的验证与交付边界

原生验证发现并修复了两个窗口问题。首先，`SetWindowPos` 同步触发的 Tk 生命周期回调可能以 `PyEval_RestoreThread` 错误直接终止 Python；独立最小复现确认 `WinDLL` 和 `PyDLL` 均会触发。现在由 Tcl 合并事件并在空闲阶段进入 Python，销毁时取消未执行的回调，同时保留原有字幕动画清理绑定。其次，文字层即使已正确归属于主窗口，也可能在初次映射时排到背景下面；现在检查实际层级，仅在需要时将文字层放到其背景上方。原始失败记录、最小复现及修复后的对照证据均保留。

最终 Windows 全套 pytest：**662 项通过、1 项跳过**。唯一跳过仍因验证环境未安装 PyTorch。首次重跑曾因测试临时目录布局不满足安装器 TestMode 的防护而失败；调整测试环境路径后通过，未因此修改安装器代码，失败日志仍保留。

真实 Tk/Windows 验证包含 **15 组通过场景、16 个原生快照**，覆盖字幕/空白/状态区域拖动、按钮排除、边缘缩放优先、双击工具栏、两组透明度的 0/50/100% 组合、黑色描边、仅溢出行移动、边框往返、最小化恢复、负坐标及全透明时重复启动唤回不透明 Settings。15 个可见文字层快照均位于背景上方，最小化快照不绘制文字层。首次显示字幕保留原来的前台窗口；文字层不增加任务栏入口。跨进程唤回只启动一次模拟控制器。

加入模拟麦克风、模型状态及 SRT 失败提示后，3 档 Tk 缩放下的 **9 组布局场景**通过：双语完整显示，当前 2560×1440 桌面上的设置按钮（含 Exit）均可见。Computer Use 截图目视确认完整设置面板、半透明和全透明背景下的双语单行及黑色描边；实际鼠标拖动使窗口从 `+50+80` 移至 `+130+120`，双击成功隐藏及恢复工具栏。截图仅在工具内展示，没有保存图片文件。

原生验证的拖动/缩放多数使用 Tk 合成输入；实际鼠标已补测空白区拖动和双击。本轮没有重测 Explorer 任务栏点击、Alt+Tab 或真实演示软件切换，目标 2 中对应的验证边界仍适用。使用合成字幕与模拟设备/模型，没有加载真实麦克风或识别模型，也没有重建安装包。

最终测试输出、原生和布局快照、鼠标交互记录、崩溃对照记录、合成 SRT 与 SHA-256 清单保存在 `output/verification/goal4/`。原生验证前后 8 个源码文件哈希一致并与最终源码匹配。所有本轮测试窗口和 Python/Tk 测试进程均已退出，桌面窗口清单中没有遗留字幕窗口。

此前被安全审查拒绝清理的目录和两份清单全部继续保留，本轮没有重试删除。清理与留存记录继续追加在下文；测试脚本、失败日志、原生快照和合成 SRT 作为诊断记录保留。

## 目标 4 新增留存清单

2026-11-05，已核对本轮测试临时目录的物理路径、归属、符号链接目标和测试进程退出情况。随后清理以下 9 个目录的 PowerShell 命令被自动安全审查拒绝，返回 `blocked by policy`。命令未执行，删除数量为零；没有重试，也没有更换工具或编码绕过。以下路径相对于 `%USERPROFILE%\.codex\cache\agent-temp\subtitle-goal4-20261105`。

| 本轮被拒绝清理而保留的目录 | 普通文件 | 目录（含根） | 重解析点 | 普通文件逻辑字节 |
|---|---:|---:|---:|---:|
| `controls-tests` | 0 | 10 | 6 | 0 |
| `marquee-tests` | 0 | 3 | 2 | 0 |
| `review-tests` | 0 | 1 | 0 | 0 |
| `root-tests/full-final-1105-env-corrected` | 1,876 | 1,667 | 229 | 3,140,794 |
| `root-tests/full-final-zorder` | 1,876 | 1,668 | 229 | 3,140,634 |
| `root-tests/resume-focused` | 25 | 75 | 48 | 14,702 |
| `root-tests/state-cli` | 25 | 73 | 46 | 14,703 |
| `root-tests/runtime-temp` | 0 | 1 | 0 | 0 |
| `root-tests/runtime-localappdata` | 0 | 1 | 0 | 0 |
| **合计 7,861 个目录项** | **3,802** | **3,499** | **560** | **6,310,833** |

完整逐项清单为 `output/maintenance/goal4-retained-inventory.json`；拒绝结果为 `goal4-cleanup-result.json`；删除前只读盘点为 `goal4-test-temp-inventory.json`。符号链接只记录链接自身及目标，不遍历目标。另保留 `alpha-probe`、`native-validation`、4 份 pytest 日志、环境布局失败现场 `root-tests/full-final-1105` 和中断现场 `root-tests/full-resumed` 作为诊断资料。目标 1、3 的拒绝清理清单与对应内容保持不变。

## 2026-11-05：暂停源码启动准备后的下载留存

用户要求暂停启动准备，随后要求清理中断下载并自行下载。已停止本次 PyTorch 安装进程；项目新建的 `.venv` 仅包含 pip、setuptools，没有安装 Torch 或开始下载识别模型。现有 NLLB 模型缓存未改动。

本次唯一下载暂存根目录为 `%USERPROFILE%\.codex\cache\agent-temp\subtitle-launch-20261105`。Python 严格解析确认物理路径，目录及祖先没有重解析点；盘点为 21 个普通文件、25 个目录（含根）、0 个重解析点，合计 51,711,332 字节。其中未完成的 Torch wheel 为 51,537,920 字节，其余为 pip 元数据。相关下载进程为零。

删除这个已核对的专用目录的 PowerShell 命令被自动安全审查以 `blocked by policy` 拒绝，命令未执行，删除数量为零。没有重试或改用其他工具，不能声称下载已无残留。逐项留存清单为 `output/maintenance/launch-20261105-retained-inventory.json`；下载日志、原始盘点及拒绝结果保留在 `output/launch-20261105/`。此前目标 1、3、4 被拒绝清理的内容保持不动。

## 2026-11-05：CPU 运行环境与真实模型准备完成

用户授权由助手继续下载后，已在项目 `.venv` 安装 CPU 运行环境。Torch/TorchAudio 为 `2.10.0+cpu`，Transformers 为 `5.14.1`，ONNX Runtime 为 `1.28.0`。49 份官方下载文件逐个校验 SHA-256 后离线安装；`pip check`、运行依赖导入和 CPU 张量计算均通过，editable 安装指向当前项目源码。

GigaAM Multilingual Large CTC 的固定版本 `3905cd51c3ed4e88c8edf33f3302969ba480a327` 下载完成，5 个文件合计 2,341,674,025 字节。权重 2,341,592,643 字节的完整 SHA-256 与官方 LFS 值一致，模型代码也通过固定哈希检查。Silero VAD 6.2.1 下载并校验成功；原有 NLLB 缓存复用，未重新下载。

`model-doctor` 的三个必需模型全部 READY；`vad-doctor` 成功加载 ONNX 模型。真实 GigaAM 模型加载约 6.13 秒，一秒合成静音推理约 0.51 秒，返回空文本；这只验证运行链路，不表示测试了语音识别准确率。NLLB 加载约 6.01 秒，将“Здравствуйте!”译为“您好!”。全部检查使用 CPU，未打开麦克风。

已通过 `output/launch-20261105/start_project.cmd` 对应的源码入口启动 GUI，确认标题为 Russian–Chinese Live Subtitles、窗口响应正常。默认离线、CPU、`--no-auto-start`，由用户点击 Start 后开始采集。字幕输出至项目 `output/subtitles`，诊断日志在 `output/runtime/ru-zh-live-subtitles/logs`。真实麦克风会话留给用户测试；没有重建或替换旧发布安装包。完整安装、模型校验及推理记录保存在 `output/launch-20261105/`。

## 本轮下载完成后的新增留存清单

以下记录续在前轮清单之后。清理前已使用 Python 严格解析物理路径，核对允许范围、全部祖先和目录内容无重解析点，且下载、安装和模型检查进程均已退出。PyPI 元数据另存入项目诊断目录，ASR 的 HTTP headers/stderr 继续保留。随后删除已核对下载暂存的 PowerShell 命令被自动安全审查以 `blocked by policy` 拒绝；命令未执行，删除数量为零，没有重试或绕过。

| 本轮保留对象 | 普通文件 | 字节 |
|---|---:|---:|
| `C:\Users\seren\.codex\cache\agent-temp\subtitle-download-20261105-deps` | 139 | 195,168,577 |
| `C:\Users\seren\.codex\cache\agent-temp\subtitle-download-20261105-vad` | 1 | 9,146,242 |
| `C:\Users\seren\.codex\cache\agent-temp\subtitle-download-20261105-validation` | 1 | 32,044 |
| 本次 antlr wheel 的精确 pip 缓存叶目录（完整路径见清单） | 2 | 144,938 |
| `subtitle-download-20261105-asr` 中 4 个 range 分块和 1 个探测文件 | 5 | 1,395,999,275 |
| GigaAM 模型 blobs 中本轮产生的 3 个未完成下载文件 | 3 | 1,564,254,208 |
| **合计** | **151** | **3,164,745,284** |

完整 12 个目标及逐文件物理路径见 `output/maintenance/runtime-download-20261105-cleanup-inventory.json`，拒绝记录见 `runtime-download-20261105-cleanup-result.json`。ASR 的正式 blob 与 snapshot 权重为同一文件的两个硬链接，均作为运行时保留，不在清理目标中。此前所有被拒绝清理的目录及清单仍保持不变。

## 2026-11-06：修复字幕脱离窗口与重叠闪烁

用户实际测试发现字幕不随主窗口移动，主窗口、字幕与 Settings 重叠时持续闪烁。此前目标 4 的验证没有覆盖持续事件速率，也只记录 Tk geometry 而未断言原生窗口坐标；不能据此认为这两项行为已经可靠。

本次真实 Tk mainloop 复现中，4 秒触发约 3,950 次相对 lift/Configure，移动请求也未落实。直接触发源是 Windows Tk 8.6 单属性 `attributes('-topmost')` 查询会调用 SetWindowPos：每次同步读取都重新抬升主窗口，继而触发字幕层级修复和下一次 Configure。另一个错误是 override-redirect 与 transient 组合生成 WS_CHILD，但代码将其作为顶层 popup 设置 owner。

修复集中在 `src/live_subtitles/gui/caption_layer.py`：以只读原生窗口标志查询置顶状态；使用真正的 WS_POPUP 并拒绝 WS_CHILD；显示前设置 NOACTIVATE/owner；必要时只调整字幕窗口的层级，不使用 Tk 相对 lift 交换两个窗口。补查还发现 Settings 已显示时 Clear 后的下一条字幕会覆盖 Settings，现确保字幕位于主窗口之上、可见的所属对话框之下。

最终相关 GUI 回归 **183 项通过**。真实 mainloop **37 组原生检查通过**，包括连续移动、Settings 重叠、Clear 后新字幕、两种透明度、置顶切换、边框往返、负坐标、最小化恢复及仅溢出跑马灯；通过 GetWindowRect 断言字幕矩形与主窗口字幕区完全一致。静止重叠两秒期间 Configure/sync 计数保持不变；跑马灯运行也不反复调整窗口层级。

Computer Use 实际鼠标验证覆盖空白区拖动、字幕文字拖动、Settings 穿过字幕、边缘缩放、双击隐藏/恢复工具栏，以及有边框原生标题栏拖动。无边框验证 420 个采样、有边框验证 127 个采样的字幕矩形全部与字幕区一致，Settings 始终高于字幕，未记录回调异常。持续重叠时事件计数保持稳定。截图目视检查完成，图片未另行保存。所有测试窗口退出，桌面会话已 reset 释放；重新启动的是修复后的实际项目，仍为 `--no-auto-start`，等待用户自行开始麦克风测试。

复现、失败对照、最终 native JSON、鼠标采样和 pytest 日志均在 `output/verification/window-sync-20261105/`（保留复现时创建的目录名）。最终生产文件 SHA-256 为 `b8a2806237dfebab2051826a1e5ef47bcac8699cc7c99220f1dde692b4c8ef13`，与原生验证记录一致。本轮没有改动识别、翻译或 SRT 管线，也没有重建安装包。

### 本轮新增被拒绝清理的测试文件

继续追加留存记录：`C:\Users\seren\.codex\cache\agent-temp\subtitle-window-sync-20261106-tests` 包含两个专用回归临时目录 `focused`、`focused-final`，共 50 个普通文件、29,405 字节和 96 个 pytest current 链接。已用 Python 严格解析物理根路径，检查祖先无重解析点、链接目标均在该专用根内，且 pytest/IPC 子进程已退出。清理该目录的 PowerShell 命令被自动安全审查以 `blocked by policy` 拒绝，未执行，删除数量为零，全部原样保留；没有重试或绕过。

完整清单：`output/maintenance/window-sync-20261106-retained-inventory.json`。拒绝记录：`output/maintenance/window-sync-20261106-cleanup-result.json`。此前所有被拒绝清理的内容和记录保持不变。

## 2026-11-07：应用化改进的新增清理留存

按用户要求继续追加，不覆盖之前的清单。以下两处为本轮创建的测试暂存与第一次中间构建；原生/单测/打包UI证据已另存项目 output/verification/application-improvement，测试程序均已退出。Python已严格解析物理根路径，并确认777个pytest链接的目标均在本轮专用临时根内。

| 留存路径 | 普通文件 | 字节 | 重解析点 |
|---|---:|---:|---:|
| `C:\Users\seren\.codex\cache\agent-temp\subtitle-app-improvement-20261106` | 5807 | 321296554 | 777 |
| `C:\Users\seren\Documents\ru-zh-live-subtitles\dist\cpu-application-20261106` | 5581 | 600812360 | 0 |
| 合计 | 11388 | 922108914 | 777 |

包含祖先路径和活动进程引用检查的 PowerShell 清理命令被自动安全审查以 `blocked by policy` 拒绝，命令未执行、删除数为零。两处全部保留，未换工具、语言或编码重试。

完整逐项清单：`output/maintenance/application-improvement-cleanup-inventory.json`；拒绝记录：`output/maintenance/application-improvement-cleanup-result.json`。新的最终程序位于 `dist/cpu-application-20261107`，不在此次清理目标中。

安装包完成后另行检查本轮模型打包副本 `C:\Users\seren\Documents\ru-zh-live-subtitles\output\application-build-20261106\model-assets`：18文件，4,826,654,800字节，无重解析点；模型清单已保存到同级 `model-manifest-evidence.json`。编译器及测试程序退出后，对这个独立目标的清理也被自动安全审查以 `blocked by policy` 拒绝。命令未执行，删除数为零，全部保留且不重试。详见 `output/maintenance/application-model-staging-cleanup-inventory.json` 和 `application-model-staging-cleanup-result.json`。

本轮两次被拒绝清理合计 **11,406个普通文件、5,748,763,714字节及777个重解析点**，全部续在此前记录后面。正式运行模型、旧安装包、最终验收包和诊断证据均保留。


### 2026-11-07 Windows acceptance repair: retained cleanup (append)

Automatic approval review rejected removal of this task's pytest temporary directory (`blocked by policy`). No alternate deletion method was attempted. All files remain.

- Root: `C:\Users\seren\.codex\cache\agent-temp\subtitle-windows-fixes-20261107`
- Inventory: 1910 files, 3540570 bytes, 231 reparse points.
- Evidence: `output/verification/windows-fixes-20261107/temp-inventory.json` and `cleanup.json`. Earlier denied cleanup entries remain unchanged.
- Old distribution retained for rollback; new distribution and build provenance retained for delivery/reproducibility; model assets and diagnostic records retained.


### 单文件 EXE 压缩中止后保留项（2026-11-07）

按用户指令中止压缩。构建及压缩进程已停止，等待成品的验证任务已退出。未生成最终 EXE，没有删除以下文件。逐文件清单位于 output/verification/single-exe/interrupted-inventory.json（写入清单前的快照）。

- C:\Users\seren\Documents\ru-zh-live-subtitles\build\single-offline：1 个文件，2,865,545,156 字节。
- C:\Users\seren\Documents\ru-zh-live-subtitles\build\single-smoke：7 个文件，26,016 字节。
- C:\Users\seren\Documents\ru-zh-live-subtitles\dist\single-offline：0 个文件，0 字节。
- C:\Users\seren\Documents\ru-zh-live-subtitles\output\verification\single-exe：5 个文件，1,996 字节。
- C:\Users\seren\Documents\ru-zh-live-subtitles\packaging\single_file：3 个文件，10,027 字节。
- C:\Users\seren\AppData\Local\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\RuZhOffline\be6efdfe48939e1ae18c：5 个文件，84 字节。

未完成的 payload.tar.xz 不是可交付文件；packaging/single_file 为原型源码，verification 为诊断材料。以前保留的安装器、运行时和模型不属于本次残余。

### 2026-11-07：用户请求全项目盘点与清理（追加）

本轮项目盘点（不含 .git 与既有 maintenance 诊断）普通文件逻辑总量 30,713,825,067 字节，不跟随重解析点。已通过同一 PowerShell 脚本核对物理路径、祖先及子项重解析点、活动进程引用和文件计数/大小后，成功删除 3,790,656,861 字节：.pytest_cache、build/cpu-provenance、build/refactor-cpu-20261107、build/refactor-final-cpu-20261107、build/single-offline、build/single-smoke、build/windows-fixes-20261107。中断的 payload.tar.xz 此时已删除，不再属于当前残留；此前清单作为历史快照保留。构建诊断 txt/html/json 另存后再清理。

旧发行与回滚目录合计 17,004,456,988 字节按既有要求保留；tmp 中 23,176,945 字节为文档生成脚本/翻译缓存/渲染预览，未按目录名推断可删。.venv、当前最终程序/安装包、SRT、日志、源码、诊断和模型保留。取消的 single_file 原型已在 README 明确标注并归档到 Git。

本轮没有再次执行历史被拒绝的删除。项目内旧中间程序 dist/cpu-application-20261106（600,812,360 字节）和可选模型打包副本 output/application-build-20261106/model-assets（4,826,654,800 字节）的用户手动脚本仅运行了预览，未删除；删除模型副本会使后续离线打包需要重建暂存。项目外历史缓存没有重新扫描，其旧清单仍保留。

本轮完整目录统计 inventory.json、删除后状态 result.json、说明 REPORT.md、构建诊断与两份清理脚本均在 output/maintenance/project-cleanup-20261107。manual-retained.ps1 默认只预览，-Execute 才删除；-IncludeModelStaging 才包括模型打包副本。脚本遇到路径重定向、活动项目进程、重解析点或盘点变化会停止。
