package com.psyche.kelivo.shell

import android.util.Log
import java.util.concurrent.atomic.AtomicReference

/**
 * Root 通道。
 *
 * 判定「有没有 root」的唯一可靠方式是**真的执行一次 `su -c id` 并看返回的 uid**：
 * Magisk / KernelSU / APatch 都会隐藏 su 的真实路径，靠查文件存在性判断必然误判。
 *
 * 关于状态管理（这里踩过坑，写清楚免得再犯）：
 *  - **不持久化探测结果。** 之前把结果落盘，结果出现「用户撤掉 root 之后界面
 *    仍然显示已授权」—— 因为落盘的旧值被当成了事实、而且不再复核。
 *    现在的策略是：结果只留在内存里，需要知道时**当场探测**，永远反映当前真实情况。
 *  - 探测失败后 30 秒内不重复探测，避免在没有 root 的设备上反复空等超时、
 *    或反复弹出 Root 管理器授权框。
 *  - 单次探测最长 12 秒（从未授权过时会弹授权框，用户不点就会挂住）。
 */
object RootShell {

    private const val TAG = "KelivoRootShell"
    private const val PROBE_TIMEOUT_MS = 12_000L

    /** 探测失败后的冷却时间。 */
    private const val FAILED_PROBE_COOLDOWN_MS = 30_000L

    /** 只有 uid 正好是 0 才算 root；顺带避开 "uid=1000" 这种包含关系。 */
    private val rootedPattern = Regex("(^|\\s)uid=0(\\s|\\()")

    @Volatile
    private var cachedAvailability: Boolean? = null

    @Volatile
    private var lastFailedProbeAt = 0L

    /** 最近一次探测结果；null 表示本次进程内还没探测过。 */
    fun cached(): Boolean? = cachedAvailability

    /**
     * 是否值得再探测一次。
     *
     * 已知可用就跳过；已知不可用则等冷却过去再试（这样用户中途去授权，
     * 最多 30 秒后就会被自动识别到，不需要手点）。
     */
    fun shouldProbe(): Boolean {
        if (cachedAvailability == true) return false
        return System.currentTimeMillis() - lastFailedProbeAt > FAILED_PROBE_COOLDOWN_MS
    }

    /** 当场探测。结果只留在内存里，不落盘。 */
    fun probe(): Boolean {
        val result = execute("id", PROBE_TIMEOUT_MS)
        val available = result != null &&
            !result.timedOut &&
            result.exitCode == 0 &&
            rootedPattern.containsMatchIn(result.output)
        cachedAvailability = available
        if (!available) lastFailedProbeAt = System.currentTimeMillis()
        Log.i(TAG, "root probe -> $available")
        return available
    }

    /**
     * 执行命令。
     *
     * 成功执行即确认通道可用；而「明确的权限失败」要能反向改判为不可用 ——
     * 否则用户撤掉 root 后，内存里的旧状态会一直骗着我们。
     */
    fun run(command: String, timeoutMs: Long): ShellCommandResult? {
        val result = execute(command, timeoutMs)
        when {
            result == null -> {
                cachedAvailability = false
                lastFailedProbeAt = System.currentTimeMillis()
            }

            result.timedOut -> {
                // 超时可能只是这条命令卡住，不据此改判 root 状态。
            }

            result.exitCode == 0 -> {
                cachedAvailability = true
            }

            looksLikePermissionDenied(result.output) -> {
                cachedAvailability = false
                lastFailedProbeAt = System.currentTimeMillis()
                Log.i(TAG, "root command denied -> mark unavailable")
            }
        }
        return result
    }

    private fun looksLikePermissionDenied(output: String): Boolean {
        val lower = output.lowercase()
        return lower.contains("permission denied") ||
            lower.contains("not allowed") ||
            lower.contains("access denied") ||
            lower.contains("no su program")
    }

    private fun execute(command: String, timeoutMs: Long): ShellCommandResult? {
        val started = System.currentTimeMillis()
        val holder = AtomicReference<ShellCommandResult?>()
        val processRef = AtomicReference<Process?>(null)

        val worker = Thread {
            try {
                val builder = ProcessBuilder("su", "-c", command)
                builder.redirectErrorStream(true)
                val process = builder.start()
                processRef.set(process)
                val output = readCapped(process.inputStream)
                val code = process.waitFor()
                holder.set(
                    ShellCommandResult(
                        channel = "root",
                        command = command,
                        exitCode = code,
                        output = output.text,
                        durationMs = System.currentTimeMillis() - started,
                        timedOut = false,
                        truncated = output.truncated,
                    ),
                )
            } catch (t: Throwable) {
                Log.w(TAG, "root exec failed", t)
                holder.set(
                    ShellCommandResult(
                        channel = "root",
                        command = command,
                        exitCode = -1,
                        output = "执行失败：" + (t.message ?: t.javaClass.simpleName),
                        durationMs = System.currentTimeMillis() - started,
                        timedOut = false,
                        truncated = false,
                    ),
                )
            }
        }
        worker.isDaemon = true
        worker.start()
        worker.join(timeoutMs)

        if (worker.isAlive) {
            // 超时：杀掉子进程让阻塞的读操作返回，避免线程永久挂着。
            try {
                processRef.get()?.destroy()
            } catch (_: Throwable) {
            }
            return ShellCommandResult(
                channel = "root",
                command = command,
                exitCode = -1,
                output = "命令超时（" + timeoutMs + "ms）已被中止。如果是首次使用，" +
                    "请确认 Root 管理器里的授权弹窗已经允许。",
                durationMs = System.currentTimeMillis() - started,
                timedOut = true,
                truncated = false,
            )
        }
        return holder.get()
    }
}
