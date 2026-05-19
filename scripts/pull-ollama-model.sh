#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-aiops}"
MODEL="${OLLAMA_MODEL:-smollm2:135m}"

POD="$(kubectl -n "${NAMESPACE}" get pod -l app.kubernetes.io/name=ollama -o jsonpath='{.items[0].metadata.name}')"
kubectl -n "${NAMESPACE}" exec "${POD}" -- ollama pull "${MODEL}"
