import os

import discord
import httpx
from discord.ext import commands
from kubernetes import client, config

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
AI_AGENT_URL = os.getenv("AI_AGENT_URL", "http://aio-self-healing-ai-agent:8080")
HEALER_SERVICE_URL = os.getenv("HEALER_SERVICE_URL", "")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def load_kube_config() -> None:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user}", flush=True)


@bot.command(name="health")
async def health(ctx: commands.Context) -> None:
    async with httpx.AsyncClient(timeout=10) as http:
        response = await http.get(f"{AI_AGENT_URL}/healthz")
    await ctx.reply(f"AI agent: `{response.json().get('status', 'unknown')}`")


@bot.command(name="pods")
async def pods(ctx: commands.Context, namespace: str = "default") -> None:
    core = client.CoreV1Api()
    items = core.list_namespaced_pod(namespace=namespace).items
    lines = [f"{pod.metadata.name}: {pod.status.phase}" for pod in items[:20]]
    await ctx.reply("```text\n" + ("\n".join(lines) or "No pods found.") + "\n```")


@bot.command(name="analyze")
async def analyze(ctx: commands.Context, namespace: str, pod: str) -> None:
    core = client.CoreV1Api()
    logs = core.read_namespaced_pod_log(name=pod, namespace=namespace, tail_lines=300)
    async with httpx.AsyncClient(timeout=90) as http:
        response = await http.post(
            f"{AI_AGENT_URL}/analyze",
            json={"namespace": namespace, "pod": pod, "logs": logs},
        )
    rca = response.json()
    await ctx.reply(
        f"**Severity:** `{rca['severity']}`\n"
        f"**Summary:** {rca['summary']}\n"
        f"**Root cause:** {rca['suspected_root_cause']}\n"
        f"**Fix:** {rca['fix_steps'][0] if rca['fix_steps'] else 'Review logs.'}"
    )


@bot.command(name="heal")
async def heal(ctx: commands.Context, namespace: str, deployment: str) -> None:
    apps = client.AppsV1Api()
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "aiops.dev/chatopsRestart": str(discord.utils.utcnow().timestamp())
                    }
                }
            }
        }
    }
    apps.patch_namespaced_deployment(name=deployment, namespace=namespace, body=body)
    await ctx.reply(f"Restart requested for `{namespace}/{deployment}`.")


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is required")
    load_kube_config()
    bot.run(DISCORD_TOKEN)
