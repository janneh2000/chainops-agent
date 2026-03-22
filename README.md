# ChainOps Agent 🔗

> An autonomous AI agent for Web3 infrastructure operations.  
> Built for ETHGlobal Open Agents Hackathon.

ChainOps Agent monitors Ethereum infrastructure in real time — RPC health, gas prices, block times, mempool congestion — reasons about anomalies using an LLM, and answers questions in plain English. Think Grafana + Prometheus, but with an AI ops brain on top.

---

## Architecture

```
[Ethereum RPC]
      ↓
[Python Exporter] → [Prometheus] → [Grafana Dashboards]
                          ↓
                   [FastAPI + Claude AI Agent]
                          ↓
                   [Chat UI @ localhost:8000]
```

---

## Stack

| Layer | Tool |
|---|---|
| Metrics collection | Python + prometheus-client |
| Visualization | Grafana |
| AI Agent | Claude claude-sonnet-4-20250514 (Anthropic) |
| Backend | FastAPI |
| Frontend | Vanilla HTML/CSS/JS (served by FastAPI) |
| Infra | Docker Compose |
| Web3 data | web3.py + Ethereum RPC |

---

## Quickstart

### 1. Clone and configure

```bash
git clone https://github.com/janneh2000/chainops-agent
cd chainops-agent
cp .env.example .env
```

Edit `.env` and add your `ANTHROPIC_API_KEY`.  
Optionally set `RPC_URL` to your own Alchemy/Infura endpoint for better rate limits.

### 2. Run everything

```bash
docker compose up --build
```

### 3. Open the interfaces

| Service | URL |
|---|---|
| ChainOps Agent UI + Chat | http://localhost:8000 |
| Grafana Dashboards | http://localhost:3000 (admin / chainops) |
| Prometheus | http://localhost:9090 |
| Raw Metrics | http://localhost:9101/metrics |

---

## API Reference

### `GET /metrics/snapshot`
Returns current metric values and detected anomalies.

### `POST /ask`
Ask the AI agent a question about your infrastructure.
```json
{ "question": "Is gas unusually high right now?" }
```

### `POST /detect`
Run anomaly detection and auto-generate incident reports for anything found.

### `GET /incidents`
Returns all incidents logged by the agent.

### `POST /incidents/{id}/resolve`
Mark an incident as resolved.

---

## Anomaly Thresholds

| Metric | Warning | Critical |
|---|---|---|
| RPC Up | — | = 0 (down) |
| Block Time | > 15s | > 30s |
| Gas Price | > 80 Gwei | > 200 Gwei |
| RPC Latency p99 | > 1.5s | > 3s |
| Pending Txs | — | > 100,000 |

---

## Built by

Alie Rivaldo Janneh — DevOps & Cloud Engineer  
[LinkedIn](https://linkedin.com/in/alie-janneh) · ETHGlobal Open Agents 2026
