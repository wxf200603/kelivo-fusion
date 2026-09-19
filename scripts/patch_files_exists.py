#!/usr/bin/env python3
"""Record - and if needed re-apply - the `Tools.Files.exists` mapping.

The method landed in b5d29aa as three edits:

  1. `KelivoHost.kt`           - the contract line, after `fileWrite`.
  2. `KelivoWorkspaceHost.kt`  - the implementation, in the `// --- files` block.
  3. `OperitHostDispatcher.kt` - the `Tools.Files.exists` dispatch branch.

No script was written at the time, so this one exists to give the change a
replayable, auditable record. It is idempotent: when the post-state is already
present it verifies the marker and moves on; otherwise it applies the edit. Any
anchor that does not match exactly once aborts the run, the same discipline the
other `scripts/patch_*.py` files use.

Contract, measured rather than guessed: `github.js:797` and
`extended_file_tools.js:92` both call `Tools.Files.exists(path, environment)`
and read `.exists` off the result, so the returned JSON must carry that key.
`environment` is Operit's rootfs/host selector and has no Kelivo semantics; the
dispatcher reads it only to keep the argument positions aligned.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"

EDITS = [
    (
        KT / "quickjs/KelivoHost.kt",
        "    /** Writes [content] to [path], appending when [append] is true. */\n"
        "    fun fileWrite(path: String, content: String, append: Boolean)\n",
        "    /** Writes [content] to [path], appending when [append] is true. */\n"
        "    fun fileWrite(path: String, content: String, append: Boolean)\n"
        "\n"
        "    /** Checks whether a file or directory exists at [path]. */\n"
        "    fun fileExists(path: String, environment: String?): JSONObject\n",
        "fun fileExists(path: String, environment: String?): JSONObject",
    ),
    (
        KT / "workspace/KelivoWorkspaceHost.kt",
        "    override fun fileWrite(path: String, content: String, append: Boolean) {\n"
        "        val file = File(path)\n"
        "        file.parentFile?.mkdirs()\n"
        "        if (append && file.isFile) file.appendText(content) else file.writeText(content)\n"
        "    }\n",
        "    override fun fileWrite(path: String, content: String, append: Boolean) {\n"
        "        val file = File(path)\n"
        "        file.parentFile?.mkdirs()\n"
        "        if (append && file.isFile) file.appendText(content) else file.writeText(content)\n"
        "    }\n"
        "\n"
        "    override fun fileExists(path: String, environment: String?): JSONObject =\n"
        '        JSONObject().apply { put("exists", File(path).exists()) }\n',
        "override fun fileExists(path: String, environment: String?): JSONObject =",
    ),
    (
        KT / "quickjs/OperitHostDispatcher.kt",
        "                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)\n",
        '                "Tools.Files.exists" -> {\n'
        "                    host.fileExists(\n"
        "                        args?.optString(0).orEmpty(),\n"
        "                        args?.optString(1)?.takeIf { it.isNotBlank() },\n"
        "                    ).toString()\n"
        "                }\n"
        "\n"
        "                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)\n",
        '"Tools.Files.exists" ->',
    ),
]


def main() -> None:
    for path, old, new, marker in EDITS:
        src = path.read_text(encoding="utf-8")
        if marker in src:
            print(f"already applied: {path.name}")
            continue
        found = src.count(old)
        if found != 1:
            raise SystemExit(f"{path.name}: expected 1 match, found {found}")
        path.write_text(src.replace(old, new), encoding="utf-8")
        print(f"applied: {path.name}")


if __name__ == "__main__":
    main()
