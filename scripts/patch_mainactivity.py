#!/usr/bin/env python3
"""Register OperitJsRuntime in MainActivity.

Anchors are matched without leading whitespace so the patch survives the
file's inconsistent indentation.
"""
from pathlib import Path

p = Path('android/app/src/main/kotlin/com/psyche/kelivo/MainActivity.kt')
s = p.read_text()
before = s

# 1) import
import_anchor = 'import com.psyche.kelivo.workspace.WorkspacePlugin'
if 'com.psyche.kelivo.quickjs.OperitJsRuntime' not in s:
    s = s.replace(
        import_anchor,
        import_anchor + '\nimport com.psyche.kelivo.quickjs.OperitJsRuntime',
        1,
    )

# 2) backing field
field_anchor = 'private var processTextChannel: MethodChannel? = null'
if 'private var operitJsRuntime' not in s:
    s = s.replace(
        field_anchor,
        'private var operitJsRuntime: OperitJsRuntime? = null\n    ' + field_anchor,
        1,
    )

# 3) register the channel right after the workspace plugin is attached
reg_anchor = 'workspacePlugin = kelivo.workspace.also { it.attachActivity(this) }'
if 'OperitJsRuntime(this' not in s:
    i = s.index(reg_anchor) + len(reg_anchor)
    s = s[:i] + (
        '\n        // Operit JS tool packages on the ported QuickJS engine (see docs/merge/)\n'
        '        operitJsRuntime = OperitJsRuntime(this, flutterEngine.dartExecutor.binaryMessenger)\n'
        '            .also { it.attach() }'
    ) + s[i:]

p.write_text(s)
print('patched:', s != before)
for line in s.splitlines():
    if 'OperitJsRuntime' in line or 'operitJsRuntime' in line:
        print('   ', line.strip())