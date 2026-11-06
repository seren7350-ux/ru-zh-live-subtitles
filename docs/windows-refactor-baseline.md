# Windows 重构验收基线

参考交付为 9536f358fea65e366ed9ad732286edfd2a451a96 的 CPU EXE。用户已确认分卷安装方式可用。源码行为和最终发行包分别验收。

| 操作 | 预期 | 现有证据或缺口 |
|---|---|---|
| 默认启动，按 F8 开始、停止；加载中取消 | 离线进入 Listening，停止释放麦克风与进程 | 修复版 Windows 实测 |
| 打开设置，拖至按钮不可见，关闭重开 | 整个对话框回到工作区 | 修复版 Windows 实测 |
| 从字幕文字或空白处拖动，再拖边角缩放 | 文字随窗移动；最小尺寸仍可操作 | 前版演示实测；最终包复查 |
| 重叠三个窗口、切换应用、点击无边框任务栏按钮、重复启动 | 无持续闪烁，可唤回同一实例 | 重叠和重复启动有记录；任务栏点击需实测 |
| 送入短句及溢出的双语长句 | 俄中各一行，短句静止，长句横移，无历史纵向滚动 | 前版演示实测 |
| 双击字幕两次，调两种透明度到零并切换描边 | 工具栏隐藏和恢复，文字与背景可独立控制，黑描边可见 | 前版实测 |
| 清除显示、检查 SRT，模拟片段失败后退出 | 文件保留双语全文和时间戳；日志有失败阶段、停止原因，应用可退出 | 前版实测 |
| 移至不同 DPI 显示器并重复缩放、恢复 | 文字对齐且按钮可达 | 未覆盖 |
| 新 Windows 用户离线运行安装器及开始菜单入口 | 全部模型随分卷安装，无开发机依赖 | 用户确认打包可行；干净系统条件未确认 |

既有证据位于 output/verification/windows-acceptance-20261107 和 output/verification/windows-fixes-20261107。当前参考包保留用于对照和回滚。

## 2026-11-07 重构中间包验证

addb8b44397872319ca3045b530ea2cd16ac2889 的干净源码克隆已生成 CPU EXE 和分卷安装包，分别保存在 dist/refactor-cpu-20261107 和 dist/refactor-installer-20261107。这是中间回滚点，不代表整个重构完成。

- output/refactor-release/build.log 和 installer.log 记录成功构建；安装器报告提交一致、源码干净，模型清单含 17 个文件。
- frozen-smoke.json：实际 EXE 无参数启动、重复实例退出码 0 并保留原窗口、关闭退出码 0；无音频演示生成有时间戳的俄中双语 SRT。
- verify_payload.py 独立重算安装 EXE 与两个分卷的 SHA-256，均与清单相符。
- output/verification/refactor-windows 的原生窗口测试覆盖 38 个用例，包括重叠、位移、样式、恢复和越界；144 DPI 测试同样通过。窗口样式检查不等同于点击任务栏测试，单屏 DPI 测试不等同于跨屏移动。
- 全量源码测试 688 通过、1 跳过；跳过的 torch 用例已在实际运行环境单独通过。

随后继续拆分 session_view.py，把 worker 事件到视图状态的映射从 app.py 分离；取消/失败/尾部字幕回归及 GUI/controller/process 测试共 82 项通过。这部分晚于上述发行包，包内尚不包含它。

退出升级策略进一步移入 shutdown.py：35 秒请求 terminate，再等 3 秒请求 kill；调用抛错不记录为成功，可在后续 tick 重试。GUI 仍等待 controller.shutdown_complete 并 dispose 后才销毁。此次全量回归 692 通过、1 个 torch 环境用例跳过（output/refactor-release/pytest-session-refactor.log）。

用户于本轮明确确认：此前分卷安装测试是在另一台未安装 Python／项目依赖的 Windows 电脑完成。这是此前版本的部署证据；尚未确认该机器测试时是否断网，也不是本轮重构源码的最终包验收。

仍需完成：窗口协调职责与会话生命周期边界复核、最终版本重建后实际交互验收、干净 Windows 离线安装与模型运行、跨显示器 DPI 验证。本机尚未发现可用 Windows Sandbox 入口；准备的 .wsb 不是已执行的验收证据。

窗口协调现已提取到 window_coordinator.py，职责见 gui-boundaries.md。再次运行默认与 144 DPI 原生测试，各 38 项无错误；overlay/caption/taskbar/lifecycle 单元测试 115 项通过。补充了装饰切换中退出时不重新映射窗口的回归。100ms 设置窗校正保持不变。剩余重点为最终包重建与实际交互／目标环境验收。
