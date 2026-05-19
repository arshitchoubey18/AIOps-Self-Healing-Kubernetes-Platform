#!/usr/bin/env bash
set -euo pipefail

for tool in docker kubectl minikube helm python3; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "missing: ${tool}"
    exit 1
  fi
done

echo "all required local tools are available"

