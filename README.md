# 俄语–中文字幕（Russian–Chinese Live Subtitles）

一个面向 Windows 的本地离线俄语讲座字幕工具。程序从麦克风采集语音，使用
Silero VAD 分段，通过 GigaAM Multilingual Large CTC 识别俄语，再用 NLLB
翻译成中文，并在可置顶、可调整大小的字幕窗口中显示结果。

当前版本为 **0.3.0**，正式发布了面向 Windows x64 的 **CPU-only 完全离线安装包**：

- [下载 course-final-v0.3.0](https://github.com/seren7350-ux/ru-zh-live-subtitles/releases/tag/course-final-v0.3.0)
- v0.3.0 Release 源码提交：`102dd9d97d3ac72d1d5c3936da0fc5bc490aef96`
- 仓库状态：公开（PUBLIC）
- 运行方式：CPU-only，不包含 CUDA/GPU 运行时
- 使用范围：课程、学习和非商业用途

> 本项目是课程交付成果，不是生产级字幕系统。安装器未进行代码签名，最终
> v0.3.0 修订也没有在 VMware 或另一台洁净 Windows 机器上重新验证。

## 快速安装

在 Release 页面下载以下 5 个附件：

```text
ru-zh-live-subtitles-cpu-offline-0.3.0-setup.exe
ru-zh-live-subtitles-cpu-offline-0.3.0-setup-1.bin
ru-zh-live-subtitles-cpu-offline-0.3.0-setup-2.bin
README_INSTALL.txt
SHA256SUMS.txt
```

安装步骤：

1. 将 `setup.exe` 和两个编号 `.bin` 文件放在同一目录，不要重命名。
2. 建议使用 `SHA256SUMS.txt` 校验三个安装载荷。
3. 双击 `ru-zh-live-subtitles-cpu-offline-0.3.0-setup.exe`。
4. Windows 可能因为安装器未签名而显示“未知发布者”提醒，请确认文件来源和
   SHA-256 后再继续。
5. 从开始菜单启动应用，选择麦克风并点击 Start。

安装不需要管理员权限、Python、Hugging Face Token、联网下载模型或手动复制
模型。安装前至少预留 12 GiB 磁盘空间；最低支持 8 GiB 内存，建议 16 GiB。
GigaAM 和 NLLB 首次从磁盘加载会比后续会话慢。

PowerShell 校验示例：

```powershell
Get-Content .\SHA256SUMS.txt
Get-FileHash .\ru-zh-live-subtitles-cpu-offline-0.3.0-setup.exe -Algorithm SHA256
Get-FileHash .\ru-zh-live-subtitles-cpu-offline-0.3.0-setup-1.bin -Algorithm SHA256
Get-FileHash .\ru-zh-live-subtitles-cpu-offline-0.3.0-setup-2.bin -Algorithm SHA256
```

默认安装位置：

```text
程序：%LOCALAPPDATA%\Programs\RuZhLiveSubtitles
模型：%LOCALAPPDATA%\ru-zh-live-subtitles\models
```

卸载会删除程序、离线模型、日志、缓存、快捷方式及
`%LOCALAPPDATA%\ru-zh-live-subtitles` 下的其他应用自有数据。需要保留诊断材料时，
请在卸载前自行备份。

## 当前功能

### 离线字幕流水线

```text
麦克风
  → 有界音频队列
  → Silero VAD 6.2.1
  → 完整语音分段
  → GigaAM Multilingual Large CTC（俄语识别）
  → NLLB-200 distilled 600M（俄中翻译）
  → 俄语/中文字幕窗口
```

这是“VAD 完成分段后识别整段短音频”的近实时字幕，不是原生逐词流式 ASR。
说话过程中会等待分段闭合，识别和翻译完成后一次显示该条最终结果。

### 字幕窗口

- 主控制条始终保留 Start/Stop、Pinned/Unpinned、Settings 和 Exit；
- 支持普通窗口原生缩放，以及 borderless 模式八方向缩放；
- 支持 top、bottom 和 floating 位置预设；
- 可调整透明度、俄语字号、中文字幕号和是否显示俄语；
- 每条俄语/中文结果完整保留，不截断、不使用省略号；
- 历史字幕可滚动查看，并保持用户设置的字号；
- 空间不足时只有最新一条字幕会临时缩小；新字幕到来或窗口增高后，旧条目恢复
  设置字号；
- 超长最新字幕达到最小字号后仍可在内部滚动区域完整查看，不会自行撑大窗口；
- 置顶只改变窗口层级，不持续抢占 PowerPoint 等应用的键盘焦点；
- Settings 是可复用窗口，关闭它不会停止实时字幕会话。

### 麦克风选择

Settings 可选择 `System default` 或明确的 PortAudio 输入设备编号。设备只能在
会话完全停止后修改，新选择会在下一次 Start 时生效。当前不支持运行中热切换，
也不跨应用重启保存设备选择。

### 诊断和命令行工具

项目同时保留录音、设备枚举、模型检查、单文件识别、VAD、终端字幕和翻译基准
等开发者命令。安装版开始菜单默认使用：

```text
live-overlay --translation-device cpu --offline --no-auto-start
```

## 从源码运行

支持 Python 3.10–3.14，推荐 Python 3.11。依赖必须安装在项目虚拟环境中，不要
全局安装。

```powershell
git clone https://github.com/seren7350-ux/ru-zh-live-subtitles.git
cd ru-zh-live-subtitles
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.10.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e ".[asr-multilingual,dev,translation]"
```

> 上述 PowerShell 路径应为 `.\.venv\Scripts\python.exe`。如果激活脚本被执行策略
> 阻止，直接使用该解释器即可，无需修改全局 PowerShell 策略。

源码运行不会自动获得完整的 GigaAM 和 NLLB 缓存。模型身份、固定 revision、
目录结构和离线检查方法见[模型资源设置](docs/model-assets-setup.md)。正式 0.3.0
安装包已经包含所有必需模型。

## 常用命令

下面的命令均在项目根目录执行：

```powershell
# 总帮助、运行环境和音频设备
.\.venv\Scripts\python.exe -m live_subtitles --help
.\.venv\Scripts\python.exe -m live_subtitles doctor
.\.venv\Scripts\python.exe -m live_subtitles devices
.\.venv\Scripts\python.exe -m live_subtitles model-doctor
.\.venv\Scripts\python.exe -m live_subtitles translation-doctor

# 录制 8 秒 PCM16/16 kHz/单声道 WAV
.\.venv\Scripts\python.exe -m live_subtitles record --seconds 8 --output data/sample.wav

# 单文件俄语识别和俄中翻译
.\.venv\Scripts\python.exe -m live_subtitles transcribe-file data/sample.wav
.\.venv\Scripts\python.exe -m live_subtitles translate-audio data/sample.wav --translation-engine nllb --device cpu --num-beams 1

# VAD 和实时终端字幕
.\.venv\Scripts\python.exe -m live_subtitles vad-prepare
.\.venv\Scripts\python.exe -m live_subtitles vad-doctor
.\.venv\Scripts\python.exe -m live_subtitles vad-file data/sample.wav
.\.venv\Scripts\python.exe -m live_subtitles live-vad --device 1 --duration 60
.\.venv\Scripts\python.exe -m live_subtitles live-terminal --device 1 --duration 60 --translation-engine nllb --translation-device cpu --num-beams 1

# GUI：无模型演示和真实离线字幕
.\.venv\Scripts\python.exe -m live_subtitles overlay-demo --duration 0
.\.venv\Scripts\python.exe -m live_subtitles live-overlay --device 1 --duration 0 --translation-engine nllb --translation-device cpu --num-beams 1 --offline
```

`--device 1` 只是示例；请先运行 `devices`，根据本机输出选择设备。`duration 0`
表示持续运行，直到通过 Stop、Exit 或 Ctrl+C 结束。

### 强制离线复测

模型缓存完整后，可在当前 PowerShell 会话临时启用 Hugging Face 和 Transformers
离线模式：

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
.\.venv\Scripts\python.exe -m live_subtitles model-doctor
.\.venv\Scripts\python.exe -m live_subtitles translate-audio data/sample.wav --translation-engine nllb --device cpu --num-beams 1
Remove-Item Env:HF_HUB_OFFLINE
Remove-Item Env:TRANSFORMERS_OFFLINE
```

音频和识别文本留在本机进程内。项目的 `.venv`、`data`、模型缓存、WAV、日志、
构建目录和生成制品均被 Git 忽略，不应强制提交。

## 开发与测试

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m pytest --cov=live_subtitles --cov-report=term-missing
.\.venv\Scripts\python.exe -m compileall -q src tests packaging
git diff --check
```

最终 v0.3.0 修订的记录结果：

- 源码环境：537 项测试通过；
- CPU 打包环境：537 项测试通过；
- 总覆盖率：80%，`gui/overlay.py` 为 75%；
- 最终 CPU onedir：5,616 个文件、613,281,639 字节；
- CPU onedir 中 CUDA DLL 和产品模型权重均为 0；
- 最终安装器：1 个 setup 和 2 个分片，共 3,499,769,523 字节；
- Inno Setup 7.0.2 编译警告为 0；
- Defender 对最终 CPU onedir 和安装器扫描后新增检测为 0；
- 最终安装版真实会话显示 2 条 RU/ZH 字幕、0 条失败，丢块/间隙/PortAudio
  状态/backlog 均为 0；
- 完全卸载验证通过，没有误删相邻 LOCALAPPDATA 数据。

完整的时间线、失败记录和测量证据见[开发记录](docs/development.md)。

## 打包与发布

CPU onedir 使用 `.venv-packaging-cpu` 和
`packaging/combined_cpu.spec` 构建，包含两个共享依赖的启动器，不包含模型权重。
离线安装器在构建阶段将经过校验的 Silero、GigaAM Large CTC 和 NLLB 模型载荷
与 onedir 合并，并用 Inno Setup 原生分片，保证每个 GitHub Release 附件小于
2,000,000,000 字节。

当前公开版本：

- [v0.3.0：CPU 完全离线课程交付版](https://github.com/seren7350-ux/ru-zh-live-subtitles/releases/tag/course-final-v0.3.0)
- [v0.2.0：GigaAM Large CTC 版本](https://github.com/seren7350-ux/ru-zh-live-subtitles/releases/tag/course-final-v0.2.0)
- [v0.1.0：历史 RNNT 版本](https://github.com/seren7350-ux/ru-zh-live-subtitles/releases/tag/course-final-v0.1.0)

详细构建边界见[打包说明](packaging/README.md)、
[CPU-only 分发策略](docs/cpu-only-distribution.md)和
[完整离线安装器](docs/self-contained-offline-installer.md)。

## 已知限制

- 识别在 VAD 分段结束后输出，不支持原生逐词增量显示；
- 当前正式分发仅支持 CPU，不提供 GPU/CUDA 安装包；
- NLLB 翻译质量不是人工同传或专业翻译质量保证；
- NLLB-200 distilled 600M 采用 CC-BY-NC-4.0，不允许商业使用；
- 不支持系统音频采集、PowerPoint/Acrobat 插件、点击穿透、全局快捷键、自动更新
  或代码签名；
- 字幕历史不会跨应用重启保存；
- 最终 v0.3.0 修订在开发机完成 onedir、安装、真实字幕和完全卸载验证，但没有
  重新执行 VMware/Windows Sandbox 洁净机验证；
- PowerPoint 幻灯片交互已进行过人工验证；本机没有 Acrobat，因此未声明
  Acrobat 兼容性已验证；
- 本项目不应被描述为 production ready、signed 或适用于所有 Windows 机器。

## 模型、许可与第三方组件

- Silero VAD 6.2.1：MIT；
- `ai-sage/GigaAM-Multilingual` `large_ctc`：MIT；
- `facebook/nllb-200-distilled-600M`：CC-BY-NC-4.0，仅限非商业使用；
- 其他 Python 和本机运行时组件的许可见
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)及安装后的
  `MODEL_LICENSES.txt`。

在重新分发、商业使用或更换模型前，请自行复核所有上游许可证。本仓库没有把
模型权重提交到 Git；权重只存在于本地缓存、忽略的 staging 或 Release 安装载荷中。

## 文档导航

- [文档总览](docs/README.md)
- [系统架构](docs/architecture.md)
- [仓库结构](docs/repository-layout.md)
- [模型资源设置](docs/model-assets-setup.md)
- [实时麦克风 VAD](docs/live-microphone-vad.md)
- [终端实时字幕](docs/live-terminal-subtitles.md)
- [置顶字幕窗口](docs/always-on-top-subtitle-overlay.md)
- [CPU-only 安装器验证](docs/cpu-only-installer-validation.md)
- [CPU 洁净机恢复验证](docs/cpu-clean-machine-recovery-validation.md)
- [Windows Sandbox 验证工具](docs/windows-sandbox-clean-machine-validation.md)
