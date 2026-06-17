#!/usr/bin/env bash
set -euo pipefail

export no_proxy="${no_proxy:-127.0.0.1,localhost,::1}"

exec codex \
  --sandbox danger-full-access \
  --ask-for-approval on-request \
  "$@"
