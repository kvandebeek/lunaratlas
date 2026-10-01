#!/bin/sh
# Rewrite the lock files (hashes for every wheel, one file for all platforms): sh packaging/lock.sh
# Needs uv (https://docs.astral.sh/uv/). Read the diff before committing it.
set -e
cd "$(dirname "$0")/.."
for spec in "requirements.txt requirements.lock" "requirements-ci.in requirements-ci.lock" \
            "packaging/requirements-build.txt packaging/requirements-build.lock"; do
  set -- $spec
  uv pip compile "$1" --universal --generate-hashes --python-version 3.14 -o "$2"
done
