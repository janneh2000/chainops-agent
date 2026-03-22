"""
ChainOps Agent — Web3 Metrics Exporter
Collects on-chain and RPC health metrics and exposes them to Prometheus.
Supports multi-RPC failover: if the primary endpoint fails, automatically
rotates through fallback endpoints.
"""

import os
import time
import logging
from web3 import Web3
from prometheus_client import start_http_server, Gauge, Counter, Histogram, Info

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("chainops-exporter")

# ─── Config ──────────────────────────────────────────────────────────────────
# Comma-separated list of RPC endpoints — first is primary, rest are fallbacks
RPC_URLS_RAW = os.getenv(
    "RPC_URL",
    "https://eth.llamarpc.com,https://rpc.ankr.com/eth,https://cloudflare-eth.com"
)
RPC_URLS = [u.strip() for u in RPC_URLS_RAW.split(",") if u.strip()]
SCRAPE_INTERVAL = int(os.getenv("SCRAPE_INTERVAL", "15"))
PORT = int(os.getenv("PORT", "9101"))
FAILOVER_THRESHOLD = int(os.getenv("FAILOVER_THRESHOLD", "3"))

# ─── Prometheus Metrics ──────────────────────────────────────────────────────
rpc_latency = Histogram(
    "chainops_rpc_latency_seconds",
    "Time to fetch the latest block from the RPC endpoint",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
rpc_up = Gauge("chainops_rpc_up", "1 if RPC is reachable, 0 otherwise")
rpc_errors_total = Counter("chainops_rpc_errors_total", "Total number of RPC errors")
rpc_failovers_total = Counter("chainops_rpc_failovers_total", "Total number of RPC failover events")
rpc_active_index = Gauge("chainops_rpc_active_index", "Index of the currently active RPC endpoint")
rpc_info = Info("chainops_rpc", "Currently active RPC endpoint info")

block_number = Gauge("chainops_block_number", "Latest block number")
block_time_seconds = Gauge("chainops_block_time_seconds", "Time between the last two blocks")
block_gas_used = Gauge("chainops_block_gas_used", "Gas used in the latest block")
block_gas_limit = Gauge("chainops_block_gas_limit", "Gas limit of the latest block")
block_tx_count = Gauge("chainops_block_tx_count", "Number of transactions in the latest block")
gas_price_gwei = Gauge("chainops_gas_price_gwei", "Current base gas price in Gwei")
gas_price_fast_gwei = Gauge("chainops_gas_price_fast_gwei", "Fast gas price estimate in Gwei")
pending_tx_count = Gauge("chainops_pending_tx_count", "Number of pending transactions in mempool")


# ─── RPC Manager with Failover ───────────────────────────────────────────────
class RPCManager:
    def __init__(self, urls: list):
        self.urls = urls
        self.active_index = 0
        self.consecutive_errors = 0
        self.w3 = self._connect(self.active_index)

    def _connect(self, index: int):
        url = self.urls[index]
        log.info(f"Connecting to RPC [{index}]: {url}")
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
        rpc_active_index.set(index)
        rpc_info.info({"url": url, "index": str(index)})
        return w3

    def _failover(self):
        next_index = (self.active_index + 1) % len(self.urls)
        if next_index == self.active_index:
            log.error("No other RPC endpoints to fail over to")
            return
        log.warning(
            f"Failing over: [{self.active_index}] {self.urls[self.active_index]} "
            f"-> [{next_index}] {self.urls[next_index]}"
        )
        self.active_index = next_index
        self.consecutive_errors = 0
        self.w3 = self._connect(self.active_index)
        rpc_failovers_total.inc()

    def get_block(self, block_id="latest"):
        start = time.time()
        try:
            block = self.w3.eth.get_block(block_id)
            elapsed = time.time() - start
            rpc_latency.observe(elapsed)
            rpc_up.set(1)
            self.consecutive_errors = 0
            return block, elapsed
        except Exception as e:
            elapsed = time.time() - start
            self.consecutive_errors += 1
            rpc_errors_total.inc()
            rpc_up.set(0)
            log.error(f"RPC error (#{self.consecutive_errors}): {e}")
            if self.consecutive_errors >= FAILOVER_THRESHOLD and len(self.urls) > 1:
                self._failover()
            raise

    def get_gas_price(self):
        return self.w3.eth.gas_price

    def get_pending_tx_count(self):
        return self.w3.eth.get_block_transaction_count("pending")


# ─── Collection ───────────────────────────────────────────────────────────────
_last_block_timestamp = None


def collect_metrics(rpc):
    global _last_block_timestamp
    try:
        latest, elapsed = rpc.get_block("latest")
        block_number.set(latest["number"])

        if _last_block_timestamp is not None:
            bt = latest["timestamp"] - _last_block_timestamp
            if 0 < bt < 600:
                block_time_seconds.set(bt)

        _last_block_timestamp = latest["timestamp"]
        block_gas_used.set(latest["gasUsed"])
        block_gas_limit.set(latest["gasLimit"])
        block_tx_count.set(len(latest["transactions"]))

        gas_wei = rpc.get_gas_price()
        gas_gwei_val = gas_wei / 1e9
        gas_price_gwei.set(gas_gwei_val)
        gas_price_fast_gwei.set(gas_gwei_val * 1.2)

        log.info(
            f"Block #{latest['number']} | Gas: {gas_gwei_val:.2f} Gwei | "
            f"Txs: {len(latest['transactions'])} | Latency: {elapsed*1000:.0f}ms | "
            f"RPC[{rpc.active_index}]"
        )
    except Exception:
        pass

    try:
        pending_tx_count.set(rpc.get_pending_tx_count())
    except Exception:
        pass


def main():
    log.info(f"Starting ChainOps Exporter on :{PORT}")
    log.info(f"RPC pool ({len(RPC_URLS)} endpoints): {RPC_URLS}")
    log.info(f"Failover threshold: {FAILOVER_THRESHOLD} consecutive errors")

    start_http_server(PORT)
    rpc = RPCManager(RPC_URLS)

    while True:
        collect_metrics(rpc)
        time.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    main()
