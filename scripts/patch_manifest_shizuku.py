#!/usr/bin/env python3
"""Add Shizuku support to android/app/src/main/AndroidManifest.xml.

Ported from the `ops` branch of the previous fusion repo (verified working):

  1. ShizukuProvider — without this registration `Shizuku.pingBinder()` is
     always false and the manager shows as "not installed" no matter what the
     user installed or granted. This is an explicit requirement in Shizuku's
     own README.
  2. queries entries — Android 11+ package visibility, needed to detect the
     Shizuku manager app.
  3. QUERY_ALL_PACKAGES — needed by the app-management tools.

Deliberately NOT adding the accessibility / notification <service> blocks:
those Kotlin classes were not ported in this step, and declaring a service
without its class fails at build/runtime.
"""
from pathlib import Path

p = Path('android/app/src/main/AndroidManifest.xml')
s = p.read_text()
before = s

PERMISSION = """    <!-- Device automation (ported from Operit): enumerate / launch apps by name -->
    <uses-permission
        android:name="android.permission.QUERY_ALL_PACKAGES"
        tools:ignore="QueryAllPackagesPermission" />

"""

PROVIDER = """        <!-- System command channel: Shizuku ContentProvider.
             Without this registration Shizuku.pingBinder() is always false and
             the manager shows as "not installed" regardless of user setup. -->
        <provider
            android:name="rikka.shizuku.ShizukuProvider"
            android:authorities="${applicationId}.shizuku"
            android:multiprocess="false"
            android:enabled="true"
            android:exported="true"
            android:permission="android.permission.INTERACT_ACROSS_USERS_FULL" />

"""

QUERIES = """        <!-- Shizuku: allow detecting the manager app (Android 11+ visibility) -->
        <package android:name="moe.shizuku.manager" />
        <package android:name="rikka.shizuku.provider" />
"""

if 'QUERY_ALL_PACKAGES' not in s:
    anchor = '    <application'
    i = s.index(anchor)
    s = s[:i] + PERMISSION + s[i:]
    print('  + QUERY_ALL_PACKAGES permission')

if 'ShizukuProvider' not in s:
    anchor = '    </application>'
    i = s.index(anchor)
    s = s[:i] + PROVIDER + s[i:]
    print('  + ShizukuProvider')

if 'moe.shizuku.manager' not in s:
    anchor = '    </queries>'
    i = s.index(anchor)
    s = s[:i] + QUERIES + s[i:]
    print('  + queries entries')

p.write_text(s)
print('manifest patched:', s != before)