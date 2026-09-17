package com.psyche.kelivo.shell

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import moe.shizuku.server.IShizukuService
import rikka.shizuku.Shizuku
import java.util.concurrent.atomic.AtomicReference

/**
 * Shizuku 通道（ADB 级权限，不需要 root）。
 *
 * 13.x 的 API 面和旧文档不一样，这里按实际 AAR 的签名写：
 *  - **不存在** `Shizuku.newProcess`，跑命令必须自己拿 `IShizukuService`：
 *    `Shizuku.getBinder()` → `IShizukuService.Stub.asInterface(...)`
 *    → `newProcess(...)` → `IRemoteProcess`
 *  - 输出通过 `getInputStream()` 返回的 `ParcelFileDescriptor` 读取
 */
object ShizukuShell {

    private const val TAG = "KelivoShizukuShell"
    const val REQUEST_CODE = 4213

    /** Shizuku 管理器（App 形态）的包名；Sui 是它的 root 版替代品，包名不同。 */
    private const val SHIZUKU_PACKAGE = "moe.shizuku.manager"
    private const val SHIZUKU_MAIN_ACTIVITY = "moe.shizuku.manager.MainActivity"

    /** 已知的 Shizuku/Sui 相关包名（覆盖各种安装方式）。 */
    private val KNOWN_SHIZUKU_PACKAGES = setOf(
        "moe.shizuku.manager",           // 官方 Shizuku App
        "moe.shizuku.privileged.api",    // Shizuku 特权 API
        "rikka.shizuku.provider",        // Shizuku provider
        "rikka.sui",                     // Sui（root 版替代品）
        "me.weishu.kernelsu",            // KernelSU（部分设备用这个）
        "com.topjohnwu.magisk",          // Magisk（部分 Shizuku 通过 Magisk 启动）
    )

    /** Shizuku 服务是否活着（未启动时为 false）。 */
    fun binderAlive(): Boolean = try {
        Shizuku.pingBinder()
    } catch (t: Throwable) {
        Log.w(TAG, "pingBinder failed", t)
        false
    }

    /**
     * Shizuku 管理器是否已安装。
     *
     * 之前只用 getPackageInfo / getLaunchIntentForPackage，在 Android 11+ 上会因为
     * 包可见性（package visibility）限制而返回 null，导致明明装了却显示"未安装"。
     *
     * 现在改为直接枚举已安装应用列表（getInstalledApplications 不需要 <queries>），
     * 并匹配已知的 Shizuku/Sui 包名。
     */
    fun isManagerInstalled(context: Context): Boolean {
        // binder 活着就一定装了（这条最可靠，且不受包可见性策略影响）。
        if (binderAlive()) return true

        // 方法 1：直接枚举已安装应用（不需要 <queries>，不受包可见性限制）。
        try {
            val pm = context.packageManager
            @Suppress("DEPRECATION")
            val installed = pm.getInstalledApplications(PackageManager.GET_META_DATA)
            for (app in installed) {
                if (KNOWN_SHIZUKU_PACKAGES.contains(app.packageName)) {
                    Log.i(TAG, "found shizuku package: ${app.packageName}")
                    return true
                }
            }
        } catch (t: Throwable) {
            Log.w(TAG, "getInstalledApplications failed", t)
        }

        // 方法 2：getPackageInfo（部分 ROM 可能仍然可用）。
        for (pkg in KNOWN_SHIZUKU_PACKAGES) {
            try {
                @Suppress("DEPRECATION")
                context.packageManager.getPackageInfo(pkg, 0)
                Log.i(TAG, "getPackageInfo found: $pkg")
                return true
            } catch (_: Throwable) {
                // 继续下一个包名。
            }
        }

        // 方法 3：getLaunchIntentForPackage。
        for (pkg in KNOWN_SHIZUKU_PACKAGES) {
            try {
                if (context.packageManager.getLaunchIntentForPackage(pkg) != null) {
                    Log.i(TAG, "getLaunchIntentForPackage found: $pkg")
                    return true
                }
            } catch (_: Throwable) {
                // 继续下一个包名。
            }
        }

        return false
    }

    /**
     * 打开 Shizuku 管理器界面（已安装但没启动时，用户需要进去用
     * "通过 root 启动" 或 ADB 把它拉起来）。
     *
     * @return true 表示成功拉起；false 表示没装上，调用方应改为引导下载。
     */
    fun launchManager(context: Context, activity: Activity?): Boolean {
        val target: Context = activity ?: context
        val pm = context.packageManager

        // 找到第一个已安装的 Shizuku 包。
        val installedPkg = findInstalledPackage(pm) ?: return false

        try {
            val launch = pm.getLaunchIntentForPackage(installedPkg)
            if (launch != null) {
                launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                target.startActivity(launch)
                return true
            }
        } catch (t: Throwable) {
            Log.w(TAG, "launch intent failed for $installedPkg", t)
        }

        // 显式组件兜底。
        try {
            val explicit = Intent()
                .setClassName(installedPkg, "$installedPkg.MainActivity")
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            target.startActivity(explicit)
            return true
        } catch (t: Throwable) {
            Log.w(TAG, "explicit activity failed for $installedPkg", t)
        }
        return false
    }

    /** 找到第一个已安装的 Shizuku 相关包。 */
    private fun findInstalledPackage(pm: PackageManager): String? {
        for (pkg in KNOWN_SHIZUKU_PACKAGES) {
            try {
                @Suppress("DEPRECATION")
                pm.getPackageInfo(pkg, 0)
                return pkg
            } catch (_: Throwable) {
                // 继续。
            }
        }
        return null
    }

    /** 本应用是否已获得 Shizuku 授权。 */
    fun permissionGranted(): Boolean = try {
        if (!binderAlive()) false
        else if (Shizuku.isPreV11()) false
        else Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    } catch (t: Throwable) {
        Log.w(TAG, "checkSelfPermission failed", t)
        false
    }

    /** Shizuku 服务进程的 uid（ADB 级通常是 2000）。 */
    fun serviceUid(): Int = try {
        Shizuku.getUid()
    } catch (_: Throwable) {
        -1
    }

    fun requestPermission(): Boolean = try {
        Shizuku.requestPermission(REQUEST_CODE)
        true
    } catch (t: Throwable) {
        Log.w(TAG, "requestPermission failed", t)
        false
    }

    fun run(command: String, timeoutMs: Long): ShellCommandResult? {
        if (!permissionGranted()) return null

        val started = System.currentTimeMillis()
        val holder = AtomicReference<ShellCommandResult?>()
        val processRef = AtomicReference<moe.shizuku.server.IRemoteProcess?>(null)

        val worker = Thread {
            try {
                val binder = Shizuku.getBinder()
                    ?: throw IllegalStateException("Shizuku binder 不可用")
                val service = IShizukuService.Stub.asInterface(binder)
                val process = service.newProcess(arrayOf("sh", "-c", command), null, null)
                processRef.set(process)

                val stream = android.os.ParcelFileDescriptor
                    .AutoCloseInputStream(process.inputStream)
                val output = stream.use { readCapped(it) }
                val code = process.waitFor()

                holder.set(
                    ShellCommandResult(
                        channel = "shizuku",
                        command = command,
                        exitCode = code,
                        output = output.text,
                        durationMs = System.currentTimeMillis() - started,
                        timedOut = false,
                        truncated = output.truncated,
                    ),
                )
            } catch (t: Throwable) {
                Log.w(TAG, "shizuku exec failed", t)
                holder.set(
                    ShellCommandResult(
                        channel = "shizuku",
                        command = command,
                        exitCode = -1,
                        output = "执行失败：${t.message ?: t.javaClass.simpleName}",
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
            try {
                processRef.get()?.destroy()
            } catch (_: Throwable) {
            }
            return ShellCommandResult(
                channel = "shizuku",
                command = command,
                exitCode = -1,
                output = "命令超时（${timeoutMs}ms）已被中止。",
                durationMs = System.currentTimeMillis() - started,
                timedOut = true,
                truncated = false,
            )
        }
        return holder.get()
    }
}
