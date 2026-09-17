package com.psyche.kelivo.quickjs

/**
 * Assembles a QuickJS runtime capable of running Operit tool packages.
 *
 * Wiring was verified against the ported Operit sources
 * (`QuickJsNativeRuntime.kt`, `QuickJsNativeHostDispatcher.kt`):
 *
 *  - [QuickJsNativeHostDispatcher] already implements `HostBridge` and serves
 *    `console.*`, `scheduleTimer` and `cancelTimer` itself;
 *  - every other call is forwarded via its `forwardCall` lambda — which is
 *    exactly where [OperitHostDispatcher] plugs in;
 *  - `QuickJsNativeRuntime.create(hostBridge)` is a *static* factory while
 *    `dispatchTimer` is an *instance* method, hence the nullable back-reference.
 *
 * Usage (stage 2):
 * ```
 * val (runtime, _) = QuickJsHostEnvironment.create(host = WorkspaceKelivoHost(...))
 * runtime.installCompatLayerOrThrow()          // injects the NativeInterface Proxy
 * runtime.eval(jsSourceOfSuperAdmin).let { ... } // load the Operit package
 * ```
 */
object QuickJsHostEnvironment {

    /** @return the runtime, paired with the dispatcher that backs it. */
    fun create(host: KelivoHost): Pair<QuickJsNativeRuntime, OperitHostDispatcher> {
        val operitDispatcher = OperitHostDispatcher(host = host)

        var runtimeRef: QuickJsNativeRuntime? = null
        val jsDispatcher = QuickJsNativeHostDispatcher(
            dispatchTimer = { timerId -> runtimeRef?.dispatchTimer(timerId) },
            forwardCall = { method, argsJson -> operitDispatcher.call(method, argsJson) },
        )

        val runtime = QuickJsNativeRuntime.create(jsDispatcher)
        runtimeRef = runtime

        return runtime to operitDispatcher
    }
}