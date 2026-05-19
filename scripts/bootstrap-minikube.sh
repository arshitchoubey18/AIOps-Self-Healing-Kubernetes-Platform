#!/usr/bin/env bash
set -euo pipefail

PROFILE="${MINIKUBE_PROFILE:-aiops}"
CPUS="${MINIKUBE_CPUS:-2}"
MEMORY="${MINIKUBE_MEMORY:-4096}"

minikube start -p "${PROFILE}" --cpus "${CPUS}" --memory "${MEMORY}" --driver=docker
minikube -p "${PROFILE}" addons enable metrics-server

kubectl config use-context "${PROFILE}"
kubectl get nodes
