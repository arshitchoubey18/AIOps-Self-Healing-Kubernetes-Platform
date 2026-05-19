# AIOps Self-Healing Kubernetes Platform

Production-shaped, local-first AIOps platform for Kubernetes using only open-source runtime components.

This repo walks from zero to a working minikube demo across six practical phases:

1. GitHub Actions CI/CD builds Docker images and updates Helm values.
2. Argo CD GitOps auto-sync deploys Helm charts with self-heal enabled.
3. Observability stack: Prometheus, Grafana, Loki, Promtail.
4. FastAPI AI agent calls Ollama for structured RCA.
5. Self-healing controller detects incidents and restarts or rolls back workloads.
6. Discord ChatOps bot exposes health, pod, analyze, and heal commands.

## Architecture

```text
GitHub Actions
   -> Docker image tags
   -> charts/aio-self-healing/values.yaml
   -> Argo CD auto-sync
   -> minikube cluster

Kubernetes logs/events
   -> ai-agent FastAPI
   -> Ollama local LLM
   -> healer controller
   -> GitHub Issues + Discord commands

Prometheus + Grafana + Loki + Promtail
   -> metrics, dashboards, logs
```

## Prerequisites

- Docker
- kubectl
- minikube
- Helm 3
- Argo CD CLI
- Python 3.11+
- Ollama with a local model. The minikube default is `smollm2:135m`; use `mistral` only when your node has enough free memory.
- A GitHub repository for CI/CD and incident issues
- A Discord bot token for ChatOps

## Quick Start

```bash
./scripts/bootstrap-minikube.sh
./scripts/install-observability.sh
./scripts/install-argocd.sh
./scripts/deploy-local.sh
```

The minikube script defaults to `2` CPUs and `4096` MB memory. Override only if your machine has room:

```bash
MINIKUBE_CPUS=4 MINIKUBE_MEMORY=8192 ./scripts/bootstrap-minikube.sh
```

Port-forward the AI agent:

```bash
kubectl -n aiops port-forward svc/aio-self-healing-ai-agent 8080:8080
curl http://localhost:8080/healthz
```

Generate an RCA from logs:

```bash
curl -X POST http://localhost:8080/analyze \
  -H 'content-type: application/json' \
  -d '{"namespace":"demo","pod":"crashy","logs":"Traceback: connection refused"}'
```

## Phase 1: GitHub Actions CI/CD

The workflow at `.github/workflows/ci.yml`:

- runs Python lint checks,
- builds/pushes Docker images for `ai-agent`, `healer-controller`, and `discord-bot`,
- updates `charts/aio-self-healing/values.yaml` with the new image tag on merges to `main`.

Default registry is GitHub Container Registry and the workflow uses GitHub's built-in `GITHUB_TOKEN`.
Change `IMAGE_REGISTRY` in the workflow if you want Docker Hub or another registry.

## Phase 2: Argo CD GitOps

Install Argo CD:

```bash
./scripts/install-argocd.sh
```

Create the app:

```bash
kubectl apply -f gitops/applications/aio-self-healing.yaml
```

The Argo CD application uses automated sync, prune, and self-heal.

## Phase 3: Observability

Install kube-prometheus-stack, Loki, and Promtail:

```bash
./scripts/install-observability.sh
```

Open Grafana:

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
```

Default local credentials are `admin` / `admin`.

## Phase 4: FastAPI AI Agent

Run locally:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r services/ai-agent/requirements.txt
uvicorn app.main:app --app-dir services/ai-agent --reload --port 8080
```

Run Ollama locally:

```bash
ollama pull smollm2:135m
ollama serve
```

For larger machines, switch the Helm value `aiAgent.env.OLLAMA_MODEL` to `mistral` and pull that model instead. On small 2-core minikube clusters, `mistral` can fail to load with an Ollama memory error.

## Phase 5: Self-Healing Controller

The controller polls every 30 seconds by default and detects:

- `CrashLoopBackOff`
- `OOMKilled`
- failed pods

Default mode is dry-run:

```yaml
healerController:
  env:
    HEALING_MODE: dry-run
```

Switch to `active` only after validating RBAC and rollback behavior.

Crash loops use `CRASHLOOP_ACTION=rollback` by default. OOM kills restart the parent deployment.

GitHub issue creation requires:

- `GITHUB_TOKEN`
- `GITHUB_REPOSITORY`, for example `owner/repo`

## Phase 6: Discord ChatOps

Commands:

- `!health`
- `!pods [namespace]`
- `!analyze <namespace> <pod>`
- `!heal <namespace> <deployment>`

Create a Kubernetes secret:

```bash
kubectl -n aiops create secret generic aiops-secrets \
  --from-literal=DISCORD_TOKEN='replace-me' \
  --from-literal=GITHUB_TOKEN='replace-me'
```

## Demo Failure

Deploy a crashy workload:

```bash
kubectl apply -f examples/crashy-app.yaml
```

Watch the controller:

```bash
kubectl -n aiops logs deploy/aio-self-healing-healer-controller -f
```

## Repository Layout

```text
.github/workflows/       CI/CD
charts/                  Helm chart for platform services
gitops/                  Argo CD Application manifests
observability/           Helm values for monitoring/logging stack
services/ai-agent/       FastAPI RCA service
services/healer-controller/ Kubernetes self-healing loop
services/discord-bot/    Discord ChatOps bot
scripts/                 Bootstrap/deploy helpers
examples/                Demo failing workloads
```

## Safety Notes

- Start with `HEALING_MODE=dry-run`.
- Use a non-production cluster until you understand all RBAC permissions.
- Keep GitHub and Discord tokens in Kubernetes Secrets or CI secrets.
- Review generated GitHub issues before making incident automation noisy.
