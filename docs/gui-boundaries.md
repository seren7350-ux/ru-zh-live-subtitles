# GUI 职责边界

日常入口保持为安装器创建的开始菜单快捷方式。源码入口与打包入口最终进入同一个 GuiRuntime；不要再增加独立启动逻辑。

## 窗口与显示

- overlay.py 构建主界面、处理鼠标命中与用户命令，持有窗口协调器。
- settings_panel.py 构建设置页并维护设置窗显隐；关闭设置只隐藏，不停止会话。
- commands.py 为主窗与设置窗绑定同一开始／取消／停止命令。
- window_coordinator.py 协调主窗、文字层、设置窗的置顶，负责任务栏注册、显式唤回以及无边框切换。切换装饰前文字层释放原生 owner，idle 后恢复几何与 owner；关闭中不再重新映射窗口。
- caption_layer.py 封装 Win32 文字窗口的 owner、样式与位置同步；single_line.py 管理单行排版和溢出跑马灯。普通渲染不重新注册任务栏或不断抬高窗口。
- workarea.py 提供统一工作区定位规则。设置窗显示后的 idle 和 100ms 二次校正继续保留；单次 idle 尚不能保证 Windows 已完成异步几何更新。

## 会话与退出

- app.py 负责组合依赖、命令入口、事件队列消费、SRT 与日志副作用，以及安排 Tk tick。
- session_progress.py 保存一次会话的准备／取消计时。
- session_view.py 将 worker 事件映射到 SubtitleViewState，不接触 Tk、模型或文件；返回是否收到需要保存的新字幕。
- shutdown.py 保存退出超时与升级状态。请求 terminate/kill 不代表释放完成；只有 controller.shutdown_complete 后才能 dispose 并销毁 GUI。
- process_controller.py 保持工作进程与 IPC 资源所有权。晚到的 Listening 不能覆盖取消状态，尾部字幕仍保存，错误诊断持续到用户显式重试。

修改这些边界时先运行对应单元测试，再运行 output/verification/refactor-windows 的原生窗口验证。原生样式断言不能代替任务栏点击，单屏 144 DPI 不能代替跨屏移动，源码测试不能代替最终 EXE 验收。
