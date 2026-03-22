"""
ChainOps Agent — Background Scanner
Runs anomaly detection on a schedule and fires Slack alerts when issues are found.
Runs as a separate async task inside the FastAPI lifespan.
"""

import os
import asyncio
import logging
import httpx
from datetime import datetime

log = logging.getLogger("chainops-scanner")

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))  # default: every 60s
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


async def send_slack_alert(incident: dict):
    """Post an incident alert to Slack via webhook."""
    if not SLACK_WEBHOOK_URL:
        return

    severity_emoji = {"critical": "🔴", "warning": "🟡"}.get(incident["severity"], "⚪")

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{severity_emoji} ChainOps Incident #{incident['id']}: {incident['title']}"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Severity:*\n`{incident['severity'].upper()}`"},
                    {"type": "mrkdwn", "text": f"*Detected:*\n{incident['timestamp']}"}
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Summary:*\n{incident['summary']}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Recommended Action:*\n>{incident['recommended_action']}"}
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"ChainOps Agent • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"}
                ]
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=5) as hx:
            r = await hx.post(SLACK_WEBHOOK_URL, json=payload)
            if r.status_code == 200:
                log.info(f"Slack alert sent for incident #{incident['id']}")
            else:
                log.warning(f"Slack webhook returned {r.status_code}")
    except Exception as e:
        log.error(f"Failed to send Slack alert: {e}")


async def scan_loop(detect_fn, incident_log_ref):
    """
    Continuous anomaly scan loop.
    Calls the detect function directly (imported from main.py) on each tick.
    Sends Slack alerts for new critical/warning incidents.
    """
    log.info(f"Background scanner started — interval: {SCAN_INTERVAL}s")
    seen_ids = set()

    while True:
        await asyncio.sleep(SCAN_INTERVAL)
        try:
            log.info("Running scheduled anomaly scan...")
            result = await detect_fn()
            new_incidents = [i for i in result["incidents"] if i["id"] not in seen_ids]

            for incident in new_incidents:
                seen_ids.add(incident["id"])
                log.warning(
                    f"[{incident['severity'].upper()}] {incident['title']} — {incident['summary'][:80]}"
                )
                await send_slack_alert(incident)

            if not new_incidents:
                log.info("Scan complete — no new anomalies detected")

        except Exception as e:
            log.error(f"Scanner error: {e}")
