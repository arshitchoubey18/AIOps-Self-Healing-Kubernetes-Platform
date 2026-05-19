import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from github import Github
from kubernetes import client, config
from kubernetes.client import ApiException

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
AI_AGENT_URL = os.getenv("AI_AGENT_URL", "http://aio-self-healing-ai-agent:8080")
HEALING_MODE = os.getenv("HEALING_MODE", "dry-run")
CRASHLOOP_ACTION = os.getenv("CRASHLOOP_ACTION", "rollback")
WATCH_NAMESPACES = [item.strip() for item in os.getenv("WATCH_NAMESPACES", "default").split(",")]
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")


@dataclass(frozen=True)
class Incident:
    namespace: str
    pod: str
    reason: str
    message: str


def main() -> None:
    load_kube_config()
    core = client.CoreV1Api()
    apps = client.AppsV1Api()
    seen: set[str] = set()

    while True:
        for namespace in WATCH_NAMESPACES:
            for incident in detect_incidents(core, namespace):
                key = f"{incident.namespace}/{incident.pod}/{incident.reason}"
                if key in seen:
                    continue
                seen.add(key)
                handle_incident(core, apps, incident)
        time.sleep(POLL_INTERVAL_SECONDS)


def load_kube_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def detect_incidents(core: client.CoreV1Api, namespace: str) -> list[Incident]:
    incidents: list[Incident] = []
    pods = core.list_namespaced_pod(namespace=namespace)
    for pod in pods.items:
        statuses = pod.status.container_statuses or []
        for status in statuses:
            waiting = status.state.waiting
            terminated = status.last_state.terminated
            if waiting and waiting.reason == "CrashLoopBackOff":
                incidents.append(
                    Incident(namespace, pod.metadata.name, waiting.reason, waiting.message or "")
                )
            if terminated and terminated.reason == "OOMKilled":
                incidents.append(
                    Incident(
                        namespace,
                        pod.metadata.name,
                        terminated.reason,
                        terminated.message or "",
                    )
                )
        if pod.status.phase == "Failed":
            incidents.append(
                Incident(namespace, pod.metadata.name, "Failed", pod.status.message or "")
            )
    return incidents


def handle_incident(core: client.CoreV1Api, apps: client.AppsV1Api, incident: Incident) -> None:
    logs = read_logs(core, incident)
    rca = analyze_incident(incident, logs)
    print(f"[{timestamp()}] incident={incident} rca={rca}", flush=True)
    create_github_issue(incident, rca)

    if HEALING_MODE != "active":
        print(f"[{timestamp()}] dry-run mode, skipping healing action", flush=True)
        return

    if incident.reason == "OOMKilled":
        restart_parent_deployment(core, apps, incident)
    elif incident.reason == "CrashLoopBackOff" and CRASHLOOP_ACTION == "rollback":
        rollback_parent_deployment(core, apps, incident)
    elif incident.reason in {"CrashLoopBackOff", "Failed"}:
        delete_pod(core, incident)


def read_logs(core: client.CoreV1Api, incident: Incident) -> str:
    try:
        return core.read_namespaced_pod_log(
            name=incident.pod,
            namespace=incident.namespace,
            tail_lines=300,
            previous=True,
        )
    except ApiException:
        try:
            return core.read_namespaced_pod_log(
                name=incident.pod,
                namespace=incident.namespace,
                tail_lines=300,
            )
        except ApiException as exc:
            return f"Unable to read logs: {exc}"


def analyze_incident(incident: Incident, logs: str) -> dict:
    try:
        response = httpx.post(
            f"{AI_AGENT_URL}/analyze",
            json={
                "namespace": incident.namespace,
                "pod": incident.pod,
                "logs": logs,
                "events": f"{incident.reason}: {incident.message}",
            },
            timeout=90,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {
            "severity": "medium",
            "summary": f"AI agent unavailable: {type(exc).__name__}",
            "suspected_root_cause": incident.reason,
            "fix_steps": ["Inspect pod logs and Kubernetes events."],
            "prevention_tips": ["Validate AI agent service connectivity."],
            "confidence": 0.2,
        }


def delete_pod(core: client.CoreV1Api, incident: Incident) -> None:
    print(f"[{timestamp()}] deleting pod {incident.namespace}/{incident.pod}", flush=True)
    core.delete_namespaced_pod(name=incident.pod, namespace=incident.namespace)


def restart_parent_deployment(
    core: client.CoreV1Api, apps: client.AppsV1Api, incident: Incident
) -> None:
    deployment = find_parent_deployment(core, apps, incident)
    if not deployment:
        delete_pod(core, incident)
        return

    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "aiops.dev/restartedAt": timestamp(),
                    }
                }
            }
        }
    }
    print(
        f"[{timestamp()}] restarting deployment {incident.namespace}/{deployment.metadata.name}",
        flush=True,
    )
    apps.patch_namespaced_deployment(
        name=deployment.metadata.name,
        namespace=incident.namespace,
        body=body,
    )


def rollback_parent_deployment(
    core: client.CoreV1Api, apps: client.AppsV1Api, incident: Incident
) -> None:
    deployment = find_parent_deployment(core, apps, incident)
    if not deployment:
        delete_pod(core, incident)
        return

    replica_sets = apps.list_namespaced_replica_set(namespace=incident.namespace).items
    owned_sets = [
        rs
        for rs in replica_sets
        for owner in rs.metadata.owner_references or []
        if owner.kind == "Deployment" and owner.uid == deployment.metadata.uid
    ]
    ranked_sets = sorted(owned_sets, key=replica_set_revision, reverse=True)
    if len(ranked_sets) < 2:
        print(f"[{timestamp()}] no previous ReplicaSet found, deleting pod instead", flush=True)
        delete_pod(core, incident)
        return

    previous = ranked_sets[1]
    template = client.ApiClient().sanitize_for_serialization(previous.spec.template)
    template.setdefault("metadata", {}).setdefault("annotations", {})
    template["metadata"]["annotations"]["aiops.dev/rolledBackAt"] = timestamp()

    print(
        f"[{timestamp()}] rolling back deployment {incident.namespace}/{deployment.metadata.name} "
        f"to ReplicaSet {previous.metadata.name}",
        flush=True,
    )
    apps.patch_namespaced_deployment(
        name=deployment.metadata.name,
        namespace=incident.namespace,
        body={"spec": {"template": template}},
    )


def find_parent_deployment(
    core: client.CoreV1Api, apps: client.AppsV1Api, incident: Incident
) -> client.V1Deployment | None:
    pod = core.read_namespaced_pod(name=incident.pod, namespace=incident.namespace)
    owners = pod.metadata.owner_references or []
    replica_set_owner = next((owner for owner in owners if owner.kind == "ReplicaSet"), None)
    if not replica_set_owner:
        return None

    replica_set = apps.read_namespaced_replica_set(
        name=replica_set_owner.name,
        namespace=incident.namespace,
    )
    deployment_owner = next(
        (
            owner
            for owner in replica_set.metadata.owner_references or []
            if owner.kind == "Deployment"
        ),
        None,
    )
    if not deployment_owner:
        return None

    return apps.read_namespaced_deployment(
        name=deployment_owner.name,
        namespace=incident.namespace,
    )


def replica_set_revision(replica_set: client.V1ReplicaSet) -> int:
    annotations = replica_set.metadata.annotations or {}
    return int(annotations.get("deployment.kubernetes.io/revision", "0"))


def create_github_issue(incident: Incident, rca: dict) -> None:
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        return

    repo = Github(GITHUB_TOKEN).get_repo(GITHUB_REPOSITORY)
    title = f"[AIOps] {incident.reason} in {incident.namespace}/{incident.pod}"
    body = f"""## Incident

- Namespace: `{incident.namespace}`
- Pod: `{incident.pod}`
- Reason: `{incident.reason}`
- Message: `{incident.message}`
- Time: `{timestamp()}`

## AI RCA

- Severity: `{rca.get("severity")}`
- Confidence: `{rca.get("confidence")}`
- Summary: {rca.get("summary")}
- Suspected root cause: {rca.get("suspected_root_cause")}

## Fix Steps

{format_list(rca.get("fix_steps", []))}

## Prevention Tips

{format_list(rca.get("prevention_tips", []))}
"""
    repo.create_issue(title=title, body=body, labels=["aiops", "incident", incident.reason])


def format_list(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) or "- No recommendation returned."


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    main()
