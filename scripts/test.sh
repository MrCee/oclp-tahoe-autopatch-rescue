#!/bin/bash
set -e -o pipefail
cd "$(dirname "$0")/.."
xcrun clang -arch x86_64 -mmacosx-version-min=10.13 -O2 -Wall -Wextra -Werror \
  -Wno-deprecated-declarations -framework CoreFoundation kit/recovery-tool.c -o kit/recovery-tool
codesign --force --sign - kit/recovery-tool
for file in kit/*.sh; do /bin/bash -n "$file"; done
/bin/bash -n kit/finish-install.command
python3 -m unittest discover -s tests -p 'test_prepar*.py' -v
python3 -m unittest discover -s tests -p test_downloads.py -v
python3 -m unittest discover -s tests -p test_autopatch_rescue.py -v
python3 -m unittest discover -s tests -p test_finish_install.py -v
python3 -m unittest discover -s tests -p test_finish_bundle.py -v
python3 tests/test_repair.py
python3 tests/test_recovery_stage.py
