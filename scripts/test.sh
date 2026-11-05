#!/bin/bash
set -e -o pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -p 'test_*.py' -v
