package com.psyche.kelivo.workspace

import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.EventChannel
import java.util.ArrayDeque
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Broadcast sink for `app.workspace/events`. Events are always posted to the
 * main looper. Until a listener attaches, payloads are queued so a late
 * Dart subscription does not drop the first extract/exec chunks.
 *
 * Two kinds of consumer exist:
 *
 * 1. Dart, through the event channel (the workspace UI).
 * 2. In-process subscribers registered with [addListener] — the ported QuickJS
 *    host uses this to capture PTY output synchronously, because
 *    `terminal.exec` must *return* its output rather than stream it.
 *
 * @param queueWhenIdle when false, payloads with no channel subscriber are
 *   dropped instead of queued. The QuickJS host passes false: nobody ever
 *   attaches a sink to its instance, so queueing every PTY chunk would grow
 *   without bound.
 */
class WorkspaceEvents(
    private val queueWhenIdle: Boolean = true,
) : EventChannel.StreamHandler {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val lock = Any()
    private var sink: EventChannel.EventSink? = null
    private val pending = ArrayDeque<Map<String, Any?>>()
    private val listeners = CopyOnWriteArrayList<(Map<String, Any?>) -> Unit>()

    /** Registers an in-process subscriber; it is called on the emitting thread. */
    fun addListener(listener: (Map<String, Any?>) -> Unit) {
        listeners.add(listener)
    }

    fun removeListener(listener: (Map<String, Any?>) -> Unit) {
        listeners.remove(listener)
    }

    fun emit(event: Map<String, Any?>) {
        // In-process subscribers run inline so a PTY read loop is never held up
        // by UI work, and their byte order cannot be reordered.
        for (listener in listeners) {
            runCatching { listener(event) }
        }
        mainHandler.post {
            synchronized(lock) {
                val current = sink
                if (current != null) {
                    current.success(event)
                } else if (queueWhenIdle) {
                    pending.addLast(event)
                }
            }
        }
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        synchronized(lock) {
            sink = events
            while (pending.isNotEmpty()) {
                events?.success(pending.removeFirst())
            }
        }
    }

    override fun onCancel(arguments: Any?) {
        synchronized(lock) {
            sink = null
        }
    }
}
