#!/usr/bin/env python3
"""Patch the CI workflow after the first run failed with 'No space left on device'.

Root cause (from run 35218526961):
  - Kelivo depends on Rust-based plugins (super_native_extensions /
    irondash_engine_context) built via cargokit, once per ABI.
  - Building all three ABIs (arm64-v8a + armeabi-v7a + x86_64) plus three
    copies of the Flutter engine exhausted the runner's ~14 GB.

Fixes applied here:
  1. default ABI -> arm64 (matches the target phone, far less disk + time)
  2. push trigger now builds arm64 only (was --split-per-abi = all three)
  3. free disk space before building
"""
from pathlib import Path

p = Path('.github/workflows/build-merged-apk.yml')
s = p.read_text()
before = s

# 1. default ABI choice -> arm64
s = s.replace("        default: 'all'", "        default: 'arm64'")

# 2. push-trigger fallback -> arm64 only (was --split-per-abi)
s = s.replace(
    '*)           TARGET="--split-per-abi" ;;',
    '*)           TARGET="--target-platform android-arm64" ;;',
)

# 3. insert a disk-cleanup step right after checkout
anchor = "          fetch-depth: 0\n"
insert = (
    "          fetch-depth: 0\n"
    "\n"
    "      - name: Free disk space\n"
    "        uses: jlumbroso/free-disk-space@main\n"
    "        with:\n"
    "          tool-cache: true\n"
    "          android: false\n"
    "          large-packages: true\n"
    "          swap-storage: true\n"
)
if anchor in s and 'free-disk-space' not in s:
    s = s.replace(anchor, insert, 1)

p.write_text(s)

print('patched:', s != before)
for line in s.splitlines():
    if 'default:' in line or 'TARGET=' in line or 'free-disk' in line or 'Free disk' in line:
        print('   ', line.strip())
