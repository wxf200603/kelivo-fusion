package com.psyche.kelivo.workspace

import android.content.Context
import java.io.File

/**
 * The one working directory every terminal session shares.
 *
 * `cd` used to die with the shell that made it: the next session, the next
 * conversation, or the next launch all started back at the default. The fused
 * app is meant to behave like a single computer, so the directory the user last
 * worked in belongs to the workspace rather than to one PTY.
 *
 * The stored value is a *guest* path (what the shell inside proot sees). It is
 * verified before use, because a guest path can be real in two ways: it exists
 * inside the rootfs, or it is covered by a bind mount (`/sdcard` is bound in, so
 * the rootfs has no such directory while the shell does). Anything else falls
 * back to [ROOT] and says so in the diagnostic log.
 */
class GlobalWorkspace(
    private val context: Context,
    private val rootfsDir: File,
    private val binds: () -> List<BindMount>,
    private val defaultCwd: String,
    private val log: (String) -> Unit,
) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** The shared directory. Always absolute, always verified to exist. */
    @Volatile
    var cwd: String = restore()
        private set

    /**
     * The directory a session must start in.
     *
     * Re-verified here rather than only at construction, because a directory can
     * be deleted while the app runs.
     */
    fun sessionCwd(): String {
        val usable = usableOrNull(cwd)
        if (usable == null) {
            fallback(cwd)
            return ROOT
        }
        log("workspace: loaded global cwd = $usable")
        return usable
    }

    /**
     * Adopts a directory a shell has already moved to.
     *
     * Called with the shell's own `pwd` after every command, so a change made by
     * any means (`cd x`, `cd x && ...`, a sourced script) is followed - not just
     * the single-command case.
     */
    fun follow(path: String) {
        val next = usableOrNull(path) ?: return
        if (next == cwd) return
        cwd = next
        persist(next)
        log("workspace: update global cwd from cd command, new = $next")
    }

    // --------------------------------------------------------------- internals

    /** The stored directory, or the default, or the root; never throws. */
    private fun restore(): String {
        val stored = prefs.getString(KEY_CWD, null)?.takeIf { it.isNotBlank() } ?: defaultCwd
        val usable = usableOrNull(stored)
        if (usable == null) {
            // Reported here instead of stored: what gets written is ROOT, and
            // saying so once at startup is what makes a stale path debuggable.
            log("workspace: fallback to root, target directory missing ($stored)")
            persist(ROOT)
            return ROOT
        }
        return usable
    }

    private fun fallback(requested: String) {
        log("workspace: fallback to root, target directory missing ($requested)")
        cwd = ROOT
        persist(ROOT)
    }

    private fun persist(value: String) {
        runCatching { prefs.edit().putString(KEY_CWD, value).apply() }
    }

    /** [guest] if it names a directory, otherwise null. */
    private fun usableOrNull(guest: String): String? {
        val path = runCatching { ProotCommand.validateGuestCwd(guest) }.getOrNull() ?: return null
        return if (exists(path)) path else null
    }

    /**
     * True when the rootfs holds the directory, or when a bind mount covers it.
     *
     * The bind case is not optional: `/sdcard` is a bind target, so a plain
     * rootfs check would discard a perfectly good directory.
     */
    private fun exists(guest: String): Boolean {
        val covered = binds().any { mount ->
            val target = mount.guest.trimEnd('/')
            guest == target || guest.startsWith("$target/")
        }
        if (covered) return true
        return File(rootfsDir, guest.trimStart('/')).isDirectory
    }

    companion object {
        private const val PREFS = "kelivo_workspace"
        private const val KEY_CWD = "global_cwd"

        /** The container's home, and the one directory that always exists. */
        const val ROOT = "/root"
    }
}
