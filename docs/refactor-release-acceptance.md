# 重构发行验收记录

发行代码提交：5263df05c3f29606b1d1ac23a885ec56e2ea10b4。应用显示版本为 0.3.0，区分本轮包请核对 CPU_BUILD_METADATA.json 或 build-report.json 的 git_commit。

## 交付

dist/refactor-final-installer-20261107：一个 setup.exe 与两个 .bin 必须放在同一目录。压缩后合计 3,494,465,599 字节，安装内容约 5.43 GB，含 17 个模型文件和 CPU 运行时。来自干净源码克隆，源码与 EXE provenance 一致。

output/refactor-release/final-payload-check.json 是重新计算全部三个文件 SHA-256 后的结果；与发行清单一致。旧版与中间回滚包保留。

## 已验证

| 范围 | 证据 | 结论 |
|---|---|---|
| 全量源码回归 | pytest-window-refactor.log | 693 通过、1 个 torch 环境用例跳过；该用例此前实际运行环境单独通过 |
| 默认启动、重复启动、退出、演示 SRT | final-frozen-smoke.json | 新版实际 EXE 通过，重复启动保留原 HWND |
| F8 加载中取消、重试、开始／停止 | final-live-gui.json、final-live-gui.log | 新版实际窗口操作通过 |
| 模型与资源释放 | final-live-gui.log | VAD/ASR/翻译加载成功；239 个音频块处理完成，零片段；麦克风关闭，两个线程退出，引擎与应用退出码 0。没有测试真实俄语识别质量 |
| 文字／空白拖动、边界缩放、双击底栏 | Windows 实操及 final-live-gui.json | 通过 |
| 双语各一行、黑描边、独立透明度至 0 | 新版演示 Windows 实操 | 通过；背景为 0 时文字可见，文字为 0 时背景可见，两者为 0 时设置仍可用 |
| 位置、owner、层级、越界、装饰切换 | output/verification/refactor-windows | 默认与 144 DPI 原生验证各 38 项无错误；这是源码原生测试 |
| 新版干净 Windows 离线部署 | 用户本轮明确回复“测试了已经通过” | 按本轮请求测试新版：另一台无 Python／项目依赖的电脑断网安装，从开始菜单启动，F8 至 Listening，停止并退出。用户实测通过，未取得该机器日志 |

## 尚未证明完成

- 跨显示器 DPI：用户确认当前只有一台显示器；144 DPI 单屏通过不能替代跨屏验证。
- 点击无边框窗口任务栏按钮恢复：已有 APPWINDOW 样式及重复启动唤回验证，但没有真实任务栏点击证据。
- 最终 EXE 长时间重叠无闪烁及仅溢出时横向跑马灯的连续视觉时序：已有源码原生／单元测试和演示静态观察，尚不能当作最终 EXE 完整时序验收。

Goal 保持进行中。本文件记录真实覆盖范围，不将环境限制写成已通过。
