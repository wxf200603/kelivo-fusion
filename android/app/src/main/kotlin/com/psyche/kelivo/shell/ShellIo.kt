package com.psyche.kelivo.shell

/** 一条 shell 执行记录，同时也是写进执行日志的条目。 */
data class ShellCommandResult(
    /** 实际使用的通道：root / shizuku。 */
    val channel: String,
    /** 执行的命令原文。审批框里给用户看的就是它。 */
    val command: String,
    val exitCode: Int,
    /** stdout 与 stderr 合并后的输出。 */
    val output: String,
    val durationMs: Long,
    val timedOut: Boolean,
    val truncated: Boolean,
)

/** 输出读取上限，避免一条命令把内存打满。 */
internal const val MAX_OUTPUT_BYTES = 256 * 1024

internal class CappedOutput(val text: String, val truncated: Boolean)

internal fun readCapped(
    stream: java.io.InputStream,
    maxBytes: Int = MAX_OUTPUT_BYTES,
): CappedOutput {
    val buffer = ByteArray(8192)
    val builder = StringBuilder()
    var total = 0
    while (true) {
        val read = try {
            stream.read(buffer)
        } catch (t: Throwable) {
            break
        }
        if (read <= 0) break
        if (total + read > maxBytes) {
            val keep = (maxBytes - total).coerceAtLeast(0)
            if (keep > 0) {
                builder.append(String(buffer, 0, keep, Charsets.UTF_8))
            }
            return CappedOutput(builder.toString(), true)
        }
        builder.append(String(buffer, 0, read, Charsets.UTF_8))
        total += read
    }
    return CappedOutput(builder.toString(), false)
}
