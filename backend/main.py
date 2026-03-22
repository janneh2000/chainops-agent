"""
ChainOps Agent — FastAPI Backend
AI-powered Web3 infrastructure operations agent.
"""

import os
import time
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
import httpx
import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from scanner import scan_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("chainops-backend")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
RPC_URL = os.getenv("RPC_URL", "https://eth.llamarpc.com")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ─── In-memory incident log ──────────────────────────────────────────────────
incident_log = []


# ─── Lifespan: start background scanner on boot ──────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    async def _detect_wrapper():
        snapshot = await get_metrics_snapshot()
        anomalies = detect_anomalies(snapshot)
        new_incidents = []
        for anomaly in anomalies:
            report = await generate_incident_report(anomaly, snapshot)
            incident = {
                "id": len(incident_log) + 1,
                "title": report["title"],
                "severity": anomaly["severity"],
                "summary": report["summary"],
                "recommended_action": report["recommended_action"],
                "metrics_at_detection": snapshot,
                "timestamp": datetime.utcnow().isoformat(),
                "resolved": False,
            }
            incident_log.append(incident)
            new_incidents.append(incident)
        return {"detected": len(new_incidents), "incidents": new_incidents}

    task = asyncio.create_task(scan_loop(_detect_wrapper, incident_log))
    log.info("Background scanner started")
    yield
    task.cancel()
    log.info("Background scanner stopped")


app = FastAPI(title="ChainOps Agent", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Schemas ─────────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class AskRequest(BaseModel):
    question: str
    history: list[ChatMessage] = []  # full conversation history for memory
    context: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    metrics_snapshot: dict
    timestamp: str


class Incident(BaseModel):
    id: int
    title: str
    severity: str
    summary: str
    recommended_action: str
    metrics_at_detection: dict
    timestamp: str
    resolved: bool = False


# ─── Prometheus Helpers ──────────────────────────────────────────────────────

async def query_prometheus(metric: str) -> Optional[float]:
    """Query a single instant value from Prometheus."""
    try:
        async with httpx.AsyncClient(timeout=5) as hx:
            r = await hx.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": metric})
            data = r.json()
            results = data.get("data", {}).get("result", [])
            if results:
                return float(results[0]["value"][1])
    except Exception as e:
        log.warning(f"Prometheus query failed for '{metric}': {e}")
    return None


async def get_metrics_snapshot() -> dict:
    """Pull current metrics from Prometheus into a structured dict."""
    keys = {
        "rpc_up": "chainops_rpc_up",
        "block_number": "chainops_block_number",
        "block_time_seconds": "chainops_block_time_seconds",
        "gas_price_gwei": "chainops_gas_price_gwei",
        "gas_price_fast_gwei": "chainops_gas_price_fast_gwei",
        "block_gas_used": "chainops_block_gas_used",
        "block_gas_limit": "chainops_block_gas_limit",
        "block_tx_count": "chainops_block_tx_count",
        "pending_tx_count": "chainops_pending_tx_count",
        "rpc_errors_total": "chainops_rpc_errors_total",
        "rpc_latency_p99": "histogram_quantile(0.99, rate(chainops_rpc_latency_seconds_bucket[5m]))",
        "rpc_latency_p50": "histogram_quantile(0.50, rate(chainops_rpc_latency_seconds_bucket[5m]))",
    }
    snapshot = {}
    for friendly_name, query in keys.items():
        val = await query_prometheus(query)
        snapshot[friendly_name] = round(val, 4) if val is not None else None
    return snapshot


# ─── Anomaly Detection ────────────────────────────────────────────────────────

THRESHOLDS = {
    "rpc_up": {"min": 1, "label": "RPC Down"},
    "block_time_seconds": {"max": 30, "label": "Block Time Spike"},
    "gas_price_gwei": {"max": 200, "label": "High Gas Price"},
    "rpc_latency_p99": {"max": 3.0, "label": "High RPC Latency"},
    "pending_tx_count": {"max": 100000, "label": "Mempool Congestion"},
}


def detect_anomalies(snapshot: dict) -> list[dict]:
    anomalies = []
    for metric, rules in THRESHOLDS.items():
        val = snapshot.get(metric)
        if val is None:
            continue
        if "min" in rules and val < rules["min"]:
            anomalies.append({"metric": metric, "value": val, "label": rules["label"], "severity": "critical"})
        if "max" in rules and val > rules["max"]:
            severity = "critical" if val > rules["max"] * 2 else "warning"
            anomalies.append({"metric": metric, "value": val, "label": rules["label"], "severity": severity})
    return anomalies


# ─── AI Agent Core ────────────────────────────────────────────────────────────

def build_system_prompt(snapshot: dict) -> str:
    return f"""You are ChainOps Agent, an expert AI for Web3 infrastructure operations.
You have real-time access to Ethereum network metrics. Your job is to:
1. Answer questions about infrastructure health in plain, clear English
2. Diagnose anomalies and explain root causes
3. Recommend concrete operational actions
4. Generate incident reports when asked

Current metrics snapshot:
- RPC Status: {"UP" if snapshot.get("rpc_up") == 1 else "DOWN"}
- Latest Block: {snapshot.get("block_number")}
- Block Time: {snapshot.get("block_time_seconds")}s (normal: ~12s for Ethereum)
- Gas Price: {snapshot.get("gas_price_gwei")} Gwei (fast: {snapshot.get("gas_price_fast_gwei")} Gwei)
- RPC Latency p50: {snapshot.get("rpc_latency_p50")}s | p99: {snapshot.get("rpc_latency_p99")}s
- Block Gas Used: {snapshot.get("block_gas_used")} / {snapshot.get("block_gas_limit")}
- Transactions in last block: {snapshot.get("block_tx_count")}
- Pending transactions (mempool): {snapshot.get("pending_tx_count")}
- Total RPC errors: {snapshot.get("rpc_errors_total")}

Be direct, technical, and actionable. If something looks abnormal, say so clearly.
If everything looks healthy, say that confidently too.
Keep responses concise — 2-4 sentences unless generating an incident report."""


async def ask_agent(question: str, snapshot: dict, history: list = []) -> str:
    system = build_system_prompt(snapshot)

    # Build messages: history + current question
    messages = []
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": question})

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return message.content[0].text


async def generate_incident_report(anomaly: dict, snapshot: dict) -> dict:
    system = build_system_prompt(snapshot)
    prompt = f"""Generate a concise incident report for this anomaly:
- Metric: {anomaly['metric']}
- Value: {anomaly['value']}
- Issue: {anomaly['label']}
- Severity: {anomaly['severity']}

Respond ONLY in this JSON format (no markdown, no backticks):
{{
  "title": "short incident title",
  "summary": "2-3 sentence explanation of what is happening and likely cause",
  "recommended_action": "specific actionable next step for a DevOps engineer"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    import json
    text = message.content[0].text.strip()
    try:
        return json.loads(text)
    except Exception:
        return {
            "title": anomaly["label"],
            "summary": f"{anomaly['metric']} is at {anomaly['value']} which is anomalous.",
            "recommended_action": "Investigate the metric in Grafana and check RPC provider status.",
        }


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/metrics/snapshot")
async def metrics_snapshot():
    snapshot = await get_metrics_snapshot()
    anomalies = detect_anomalies(snapshot)
    return {"snapshot": snapshot, "anomalies": anomalies, "timestamp": datetime.utcnow().isoformat()}


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")
    snapshot = await get_metrics_snapshot()
    answer = await ask_agent(req.question, snapshot, req.history)
    return AskResponse(
        answer=answer,
        metrics_snapshot=snapshot,
        timestamp=datetime.utcnow().isoformat(),
    )


@app.post("/detect")
async def detect_and_report():
    """Run anomaly detection and auto-generate incidents for anything found."""
    snapshot = await get_metrics_snapshot()
    anomalies = detect_anomalies(snapshot)
    new_incidents = []

    for anomaly in anomalies:
        report = await generate_incident_report(anomaly, snapshot)
        incident = {
            "id": len(incident_log) + 1,
            "title": report["title"],
            "severity": anomaly["severity"],
            "summary": report["summary"],
            "recommended_action": report["recommended_action"],
            "metrics_at_detection": snapshot,
            "timestamp": datetime.utcnow().isoformat(),
            "resolved": False,
        }
        incident_log.append(incident)
        new_incidents.append(incident)

    return {"detected": len(new_incidents), "incidents": new_incidents}


@app.get("/incidents")
async def get_incidents():
    return {"incidents": list(reversed(incident_log)), "total": len(incident_log)}


@app.get("/incidents/{incident_id}")
async def get_incident(incident_id: int):
    for inc in incident_log:
        if inc["id"] == incident_id:
            return inc
    raise HTTPException(status_code=404, detail="Incident not found")


@app.post("/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: int):
    for inc in incident_log:
        if inc["id"] == incident_id:
            inc["resolved"] = True
            return {"status": "resolved", "incident": inc}
    raise HTTPException(status_code=404, detail="Incident not found")


@app.post("/demo/seed")
async def seed_demo_incidents():
    """
    Seeds realistic fake incidents for demo/hackathon presentations.
    Useful when the network is calm and no real anomalies exist.
    """
    demo_incidents = [
        {
            "id": len(incident_log) + 1,
            "title": "Gas Price Spike Detected",
            "severity": "critical",
            "summary": (
                "Gas price surged to 342 Gwei — 4x above the 7-day average of 82 Gwei. "
                "This is consistent with a high-activity event such as an NFT mint or "
                "major DeFi liquidation cascade driving mempool congestion."
            ),
            "recommended_action": (
                "Pause any non-urgent transactions. Set max fee to 80 Gwei and monitor "
                "for price normalization. Check pending tx count — if >150k, expect "
                "continued congestion for 15–30 minutes."
            ),
            "metrics_at_detection": {
                "gas_price_gwei": 342.5,
                "gas_price_fast_gwei": 411.0,
                "block_tx_count": 312,
                "pending_tx_count": 187423,
                "rpc_up": 1,
                "block_time_seconds": 12.1,
            },
            "timestamp": datetime.utcnow().isoformat(),
            "resolved": False,
        },
        {
            "id": len(incident_log) + 2,
            "title": "RPC Latency Degradation",
            "severity": "warning",
            "summary": (
                "p99 RPC latency climbed to 4.2 seconds over the last 5 minutes — "
                "well above the healthy threshold of 1 second. The primary endpoint "
                "appears overloaded. Automatic failover to backup endpoint was triggered."
            ),
            "recommended_action": (
                "Verify the primary RPC endpoint status with your provider. "
                "Consider upgrading to a dedicated node or load-balancing across "
                "multiple providers. Current traffic is being handled by the fallback endpoint."
            ),
            "metrics_at_detection": {
                "rpc_latency_p99": 4.2,
                "rpc_latency_p50": 1.8,
                "rpc_up": 1,
                "rpc_failovers_total": 1,
                "gas_price_gwei": 78.3,
            },
            "timestamp": datetime.utcnow().isoformat(),
            "resolved": False,
        },
        {
            "id": len(incident_log) + 3,
            "title": "Block Time Anomaly",
            "severity": "warning",
            "summary": (
                "Block time increased to 28 seconds — more than double the expected ~12 seconds. "
                "This may indicate validator client issues, network propagation delays, or "
                "a temporary drop in validator participation."
            ),
            "recommended_action": (
                "Monitor the next 5–10 blocks. If block time returns to normal, "
                "this was likely a transient propagation issue. If it persists >10 minutes, "
                "check beacon chain status at beaconcha.in and validator client logs."
            ),
            "metrics_at_detection": {
                "block_time_seconds": 28.4,
                "block_number": 21847392,
                "rpc_up": 1,
                "gas_price_gwei": 91.0,
            },
            "timestamp": datetime.utcnow().isoformat(),
            "resolved": False,
        },
    ]

    for inc in demo_incidents:
        incident_log.append(inc)

    return {
        "seeded": len(demo_incidents),
        "incidents": demo_incidents,
        "note": "These are demo incidents for hackathon presentation purposes.",
    }


# ─── Serve Frontend ───────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")
