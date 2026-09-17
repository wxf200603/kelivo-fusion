# super_admin.js 宿主契约验证报告（实测）

> 方法：在本机用 Node 24 真实加载 `super_admin.js`，注入 mock 宿主拦截全部 `Tools.*` 调用。
> 脚本：`scripts/mock_host_test.js`（可重复运行：`node scripts/mock_host_test.js`）
> 结论：**契约验证全部通过，dispatch 层设计成立。**

## 一、验证结果

| 验证项 | 结果 |
|---|---|
| METADATA 注释块解析 | ✅ `JSON.parse` 成功 |
| CommonJS 导出 | ✅ `terminal, bash, terminal_wait, terminal_getscreen, terminal_input, shell` |
| 前台命令执行链 | ✅ create → exec → 组装返回 |
| 后台执行分支 | ✅ 走独立会话名 |
| `terminal_wait` marker 机制 | ✅ 注入 `printf '__OPERIT_TERMINAL_WAIT_DONE_...'` 并轮询 |
| `terminal_getscreen` | ✅ 返回 rows/cols/content |
| `terminal_input` | ✅ 传 `{input, control}` |
| `shell`（Shizuku/Root） | ✅ |
| 大输出持久化 (>12000 字符) | ✅ 落盘 + 返回 `(saved_to_file)` |

## 二、dispatch 表必须实现的方法（实测全集）

`super_admin` 一个包就只需要 **7 个宿主方法**：

```
Tools.System.terminal.create(sessionName)          → { sessionId }
Tools.System.terminal.exec(sessionId, cmd, timeout?) → { output, exitCode, sessionId, timedOut }
Tools.System.terminal.screen(sessionId)            → { sessionId, rows, cols, content }
Tools.System.terminal.input(sessionId, {input, control}) → { ... }
Tools.System.shell(command)                        → { output, exitCode }
Tools.Files.mkdir(path, recursive)
Tools.Files.write(path, content, append)
```

**返回值字段名必须完全一致**（JS 侧直接读 `result.output` / `result.exitCode` / `result.timedOut`）。

## 三、宿主必须注入的全局（容易漏）

```js
global.OPERIT_CLEAN_ON_EXIT_DIR   // 大输出落盘目录，实测: /sdcard/Download/Operit/cleanOnExit
global.getChatId()                // 返回当前会话 ID，用于隔离终端会话
```

**会话命名规则（实测输出）：**
```
默认:  super_admin_default_session_<chatId>        // chatId 会先做 [^a-zA-Z0-9._-] → _ 清洗
后台:  super_admin_background_<chatId>_<Date.now()>
无 chatId 时: super_admin_default_session
```

这正是你要的「**所有会话共用一套容器环境**」的天然实现点——
把 `getChatId()` 恒定返回同一个值，即可让全部对话共用同一个终端会话。

## 四、Kotlin 侧实现骨架（对齐 Operit 的 `HostBridge`）

```kotlin
class OperitHostDispatcher(
    private val workspace: KelivoWorkspaceBridge,  // 对接 ProotCommand / PtySession
) {
    /** 与 compat script 的 NativeInterface.__call(method, argsJson) 对齐 */
    fun call(method: String, argsJson: String?): String? {
        val args = argsJson?.let { JsonArray().also { a -> JsonParser.parseArray(it, a) } }
        return when (method) {
            "Tools.System.terminal.create" -> {
                val name = args?.get(0)?.asString
                """{"sessionId":"${workspace.createSession(name)}"}"""
            }
            "Tools.System.terminal.exec" -> {
                val id = args!![0].asString
                val cmd = args[1].asString
                val timeout = if (args.size() > 2 && !args[2].isJsonNull) args[2].asLong else 15_000L
                workspace.exec(id, cmd, timeout).toJson()   // {output,exitCode,sessionId,timedOut}
            }
            "Tools.System.terminal.screen" -> workspace.screen(args!![0].asString)
            "Tools.System.terminal.input"  -> workspace.input(args!![0].asString, args[1])
            "Tools.System.shell"           -> ShizukuShell.exec(args!![0].asString)
            "Tools.Files.mkdir"            -> workspace.mkdir(args!![0].asString, args[1].asBoolean)
            "Tools.Files.write"            -> workspace.write(args!![0].asString, args[1].asString, args[2].asBoolean)
            else -> """{"error":"NotSupported: $method"}"""   // 红区统一降级
        }
    }
}
```

## 五、这条路径为什么省事

由于 compat script 是 `Proxy` + 方法名字符串：

- ✅ **31 个 JS 包一行都不用改**
- ✅ 新增一个包 = 往 `assets/packages/` 丢一个 `.js` + 补几个 dispatch 分支
- ✅ 未实现的 API 可返回 `NotSupported`，AI 收到可读错误而非崩溃
- ✅ 升级 Operit 的 JS 包只需覆盖文件

## 六、本验证的边界（诚实声明）

- 验证的是**接口契约**，不是真实执行。mock 的 `exec` 不跑真终端。
- 真正的终端执行需要 Kelivo 的 `PtySession` / `ProotCommand`（上游已有，但**未编译验证**）。
- Node 与 QuickJS 存在差异（`Proxy` 支持、异步调度）；QuickJS 的 `Proxy` 在 compat script 里已被使用，说明可行，但**仍需真机确认**。