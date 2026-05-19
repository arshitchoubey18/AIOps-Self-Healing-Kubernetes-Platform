import json
import os
from typing import Literal

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "smollm2:135m")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "240"))


class AnalyzeRequest(BaseModel):
    namespace: str
    pod: str
    logs: str = Field(min_length=1)
    events: str | None = None


class RCA(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    summary: str
    suspected_root_cause: str
    fix_steps: list[str]
    prevention_tips: list[str]
    confidence: float = Field(ge=0, le=1)


app = FastAPI(title="AIOps RCA Agent", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "model": OLLAMA_MODEL}


@app.post("/analyze", response_model=RCA)
async def analyze(payload: AnalyzeRequest) -> RCA:
    prompt = build_prompt(payload)
    try:
        content = await call_ollama(prompt)
        parsed = json.loads(content)
        return RCA(**parsed)
    except Exception as exc:
        return fallback_rca(payload, exc)


def build_prompt(payload: AnalyzeRequest) -> str:
    events = payload.events or "No Kubernetes events were provided."
    return f"""
Return strict JSON only for this Kubernetes incident.

Use this schema:
{{
  "severity": "low|medium|high|critical",
  "summary": "...",
  "suspected_root_cause": "...",
  "fix_steps": ["...", "..."],
  "prevention_tips": ["...", "..."],
  "confidence": 0.75
}}

Namespace: {payload.namespace}
Pod: {payload.pod}
Logs:
{payload.logs[-1200:]}
Events:
{events[-800:]}
""".strip()


async def call_ollama(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,
                    "num_predict": 120,
                    "num_ctx": 512,
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["response"]


def fallback_rca(payload: AnalyzeRequest, exc: Exception) -> RCA:
    logs = payload.logs.lower()
    if "oom" in logs or "killed" in logs:
        severity = "high"
        cause = "Container likely exceeded memory limits and was killed."
        fixes = [
            "Inspect memory usage and recent deploy changes.",
            "Increase memory limits or reduce application memory pressure.",
            "Restart the affected workload after validating capacity.",
        ]
    elif "connection refused" in logs:
        severity = "medium"
        cause = "Application dependency is refusing connections."
        fixes = [
            "Verify service DNS, endpoint readiness, and network policies.",
            "Check the dependency pod status and logs.",
            "Restart only after confirming the dependency is healthy.",
        ]
    else:
        severity = "medium"
        cause = "AI analysis was unavailable and logs require manual review."
        fixes = [
            "Check pod logs, Kubernetes events, and recent deployments.",
            "Restart the pod if it is stuck and the workload is safe to recycle.",
            "Rollback if the incident started after a release.",
        ]

    return RCA(
        severity=severity,
        summary=f"Fallback RCA generated because Ollama analysis failed: {type(exc).__name__}.",
        suspected_root_cause=cause,
        fix_steps=fixes,
        prevention_tips=[
            "Add readiness and liveness probes.",
            "Set resource requests and limits based on observed usage.",
            "Alert on crash loops before customer impact.",
        ],
        confidence=0.55,
    )
