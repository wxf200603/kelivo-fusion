# Host API 映射表（Operit JS 包 → Kelivo 能力）

> 数据来源：对 `assets/packages/*.js`（31 个包）做 `grep -oh 'Tools\.[A-Za-z]*\.[A-Za-z_]*'` 全量统计。
> 这张表就是「要让 Operit 的 JS 包在 Kelivo 里跑起来」需要实现的**完整接口清单**。

## 一、总览

共 **20 个命名空间、约 140 个方法**。按调用频次排序：

| 命名空间 | 调用次数 | Kelivo 现状 | 落地方式 |
|---|---|---|---|
| `Tools.System` | 78 | 部分 | terminal→已有 proot；其余需新增 |
| `Tools.Files` | 76 | ✅ 大部分 | 映射到 workspace 文件 API |
| `Tools.SoftwareSettings` | 32 | ❌ Operit 专属 | **重映射或裁剪** |
| `Tools.Net` | 28 | 部分 | visit✓；browser*❌ |
| `Tools.bluetooth` | 14 | ❌ | 需新增 |
| `Tools.Chat` | 14 | ✅ | 重映射到 Kelivo 会话 |
| `Tools.UI` | 13 | ❌ | **需移植无障碍服务** |
| `Tools.Workflow` | 12 | ✅ 已有(前序移植) | 重映射 |
| `Tools.Memory` | 8 | ✅ | 重映射 |
| `Tools.FFmpeg` | 3 | ❌ | 需新增 |

## 二、逐项映射明细

### ✅ 绿色：Kelivo 已有等价能力，实现 dispatch 即可

| Operit API | 调用次数 | Kelivo 对应 | 说明 |
|---|---|---|---|
| `Tools.System.terminal.create` | 18 | `workspace/PtySession.kt` | 会话管理 |
| `Tools.System.terminal.exec` | 18 | `workspace/ProotCommand.kt` | 命令执行 |
| `Tools.System.terminal.screen` | 1 | `terminal_getscreen` | 取屏幕 |
| `Tools.System.terminal.input` | 1 | `PtySession.write` | 写输入 |
| `Tools.Files.mkdir` | 14 | `WorkspaceDocumentsStore` | |
| `Tools.Files.exists` | 10 | 同上 | |
| `Tools.Files.download` | 9 | `extended_http_tools` 链路 | |
| `Tools.Files.write` | 6 | 同上 | |
| `Tools.Files.apply` | 6 | `WorkspacePlugin` | |
| `Tools.Files.deleteFile` | 5 | 同上 | |
| `Tools.Files.readBinary/read/writeBinary` | 10 | 同上 | |
| `Tools.Files.copy/move/zip/unzip/list/info` | 14 | 同上 | |
| `Tools.Files.open/share` | 2 | Kelivo 已有分享链路 | |
| `Tools.System.sleep` | 11 | Dart 侧直接实现 | |
| `Tools.System.getLocation` | 1 | `LocationToolHandler.kt` | ✅ 已有 |
| `Tools.Chat.*` | 14 | Kelivo 会话系统 | 名称需重映射 |
| `Tools.Memory.*` | 8 | Kelivo 记忆系统 | |
| `Tools.Workflow.*` | 12 | 前序会话已移植 | `lib/features/workflow/` |

### 🟡 黄色：需要新写 Kotlin 实现

| Operit API | 调用次数 | 说明 | 依赖 |
|---|---|---|---|
| `Tools.System.shell` | 4 | Android 系统命令 | **需 Shizuku/Root** |
| `Tools.System.setSetting/getSetting` | 6 | 系统设置读写 | Shizuku |
| `Tools.System.listApps/startApp/stopApp/installApp/uninstallApp` | 10 | 应用管理 | pm/am |
| `Tools.System.sendBroadcast/intent` | 3 | 广播/Intent | Android API |
| `Tools.System.getDeviceInfo` | 2 | 设备信息 | Android API |
| `Tools.System.getNotifications` | 1 | 通知读取 | NotificationListener |
| `Tools.System.getAppUsageTime` | 1 | 使用时长 | UsageStats |
| `Tools.System.usePackage` | 3 | 包系统内部调用 | dispatch 内部 |
| `Tools.bluetooth.*` | 14 | 蓝牙会话 | Bluetooth API |
| `Tools.FFmpeg.*` | 3 | 多媒体处理 | ffmpeg-kit |
| `Tools.Net.visit/uploadFile` | 7 | HTTP | Dart 侧 http |

### 🔴 红色：依赖 Operit 独有架构，无法直接映射

| Operit API | 调用次数 | 为什么不行 | 替代方案 |
|---|---|---|---|
| `Tools.UI.tap/swipe/pressKey/setText/longPress/clickElement` | 10 | 依赖 **AccessibilityService + UI 树** | 移植无障碍服务，或降级为「仅截图」 |
| `Tools.UI.captureScreenshot` | 1 | 需 MediaProjection | 可移植 |
| `Tools.UI.runSubAgent` | 2 | Operit 子代理架构 | 用 Kelivo 工具体系替代 |
| `Tools.Net.browser*` | 23 | 需 Playwright 级浏览器 | 用 webview 简化，或裁剪 `browser.js` |
| `Tools.SoftwareSettings.*` | 32 | **全是 Operit 专属**：角色卡、模型配置、TTS 服务、沙箱包、Tavern 导入导出 | **建议整体裁剪**，只保留 Kelivo 自有配置 |

## 三、实践建议

1. **不要试图 100% 覆盖**。优先实现绿区（覆盖 `super_admin` / `daily_life` / `extended_file_tools` / `code_runner` / `workflow` 等高频包）。
2. **红区按需裁剪**。加载 JS 包时若某个 `Tools.*` 未实现，dispatch 返回明确的 `NotSupportedError`，让 AI 得到可读错误而非崩溃。
3. **`Tools.SoftwareSettings` 建议整体删除**，并把 `operit_editor.js`（166KB，最大的包）排除——它操作的是 Operit 的设置体系，与 Kelivo 无对应关系。
4. **桥接层统一走 JSON-RPC**，与 compat script 的 `__call(method, argsJson)` 对齐，避免二次协议设计。
