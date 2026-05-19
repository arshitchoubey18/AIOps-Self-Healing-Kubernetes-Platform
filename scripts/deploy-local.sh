#!/usr/bin/env bash
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-aiops}"
TAG="${IMAGE_TAG:-dev}"
REGISTRY="${IMAGE_REGISTRY:-local/aiops-self-healing}"

eval "$(minikube -p "${PROFILE}" docker-env)"

docker build -t "${REGISTRY}/ai-agent:${TAG}" services/ai-agent
docker build -t "${REGISTRY}/healer-controller:${TAG}" services/healer-controller
docker build -t "${REGISTRY}/discord-bot:${TAG}" services/discord-bot

kubectl create namespace aiops --dry-run=client -o yaml | kubectl apply -f -
kubectl -n aiops create secret generic aiops-secrets \
  --from-literal=GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
  --from-literal=DISCORD_TOKEN="${DISCORD_TOKEN:-}" \
  --dry-run=client -o yaml | kubectl apply -f -

helm upgrade --install aio-self-healing charts/aio-self-healing \
  --namespace aiops \
  --set global.imageRegistry="${REGISTRY}" \
  --set global.imageTag="${TAG}" \
  --set global.imagePullPolicy=IfNotPresent \
  --set namespace.create=false

kubectl -n aiops rollout status deploy/aio-self-healing-ai-agent --timeout=180s
kubectl -n aiops rollout status deploy/aio-self-healing-healer-controller --timeout=180s
