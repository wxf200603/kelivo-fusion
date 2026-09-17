-dontwarn com.gemalto.jp2.**
-dontwarn com.tom_roush.pdfbox.filter.JPXFilter

# ---------------------------------------------------------------------------
# Ported QuickJS bridge (Operit JS tool packages)
#
# The C++ side resolves these *by name* through JNI:
#   GetMethodID(hostBridgeClass, "onCall", "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;")
# Flutter's default rules already keep `native <methods>`, which is why the
# extern declarations survive — but `onCall` is an ordinary interface method,
# so R8 happily renamed it and every configure() call died with
#   NoSuchMethodError: no non-static method "...onCall(...)"
# Keep the names below intact.
# ---------------------------------------------------------------------------
-keep interface com.psyche.kelivo.quickjs.QuickJsNativeRuntime$HostBridge { *; }

-keepclassmembers class * implements com.psyche.kelivo.quickjs.QuickJsNativeRuntime$HostBridge {
    <methods>;
}

-keep class com.psyche.kelivo.quickjs.QuickJsNativeHostDispatcher { *; }
-keep class com.psyche.kelivo.quickjs.QuickJsNativeRuntime { *; }
-keep class com.psyche.kelivo.quickjs.QuickJsNativeCompatScriptBuilder { *; }
-keep class com.psyche.kelivo.quickjs.OperitQuickJsEngine { *; }

# Defensive: anything held from native must survive shrinking.
-keepclasseswithmembernames class * {
    native <methods>;
}
