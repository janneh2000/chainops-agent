#!/usr/bin/env python3
"""
ChainOps Agent — Demo Seeder
Run this before a hackathon demo to populate realistic incidents
even when the Ethereum network is calm.

Usage:
    python demo_seed.py                    # seed incidents + print summary
    python demo_seed.py --url http://...   # custom backend URL
    python demo_seed.py --reset            # clear all incidents (restart backend to reset)
"""

import sys
import argparse
import httpx

DEFAULT_URL = "http://localhost:8000"


def seed(base_url: str):
    print(f"\n🔗 ChainOps Agent Demo Seeder")
    print(f"   Backend: {base_url}\n")

    # Health check
    try:
        r = httpx.get(f"{base_url}/health", timeout=5)
        r.raise_for_status()
        print("✅ Backend is up\n")
    except Exception as e:
        print(f"❌ Backend not reachable: {e}")
        print("   Make sure `docker compose up` is running first.")
        sys.exit(1)

    # Seed demo incidents
    print("📦 Seeding demo incidents...")
    r = httpx.post(f"{base_url}/demo/seed", timeout=10)
    data = r.json()

    print(f"\n✅ Seeded {data['seeded']} incidents:\n")
    for inc in data["incidents"]:
        sev = inc["severity"].upper()
        icon = "🔴" if sev == "CRITICAL" else "🟡"
        print(f"  {icon} [{sev}] #{inc['id']} — {inc['title']}")
        print(f"       {inc['summary'][:90]}...")
        print()

    print("─" * 60)
    print(f"\n🎯 Demo tips:")
    print(f"   1. Open {base_url} in your browser")
    print(f"   2. Click any incident in the left panel to see details")
    print(f"   3. Use 'Ask Agent About This' to show AI reasoning")
    print(f"   4. Try asking: 'What should I do about the gas spike?'")
    print(f"   5. Grafana dashboards: http://localhost:3000 (admin/chainops)")
    print(f"\n")


def check_status(base_url: str):
    print(f"\n📊 ChainOps Agent Status\n")
    try:
        snap = httpx.get(f"{base_url}/metrics/snapshot", timeout=5).json()
        s = snap["snapshot"]
        print(f"  RPC:        {'UP ✅' if s.get('rpc_up') == 1 else 'DOWN ❌'}")
        print(f"  Block:      #{s.get('block_number', '—')}")
        print(f"  Block Time: {s.get('block_time_seconds', '—')}s")
        print(f"  Gas Price:  {s.get('gas_price_gwei', '—')} Gwei")
        print(f"  Latency p99:{s.get('rpc_latency_p99', '—')}s")

        anomalies = snap["anomalies"]
        if anomalies:
            print(f"\n  ⚠  {len(anomalies)} active anomaly/anomalies:")
            for a in anomalies:
                print(f"     [{a['severity'].upper()}] {a['label']} — {a['metric']}: {a['value']}")
        else:
            print(f"\n  ✅ No anomalies detected")

        incidents = httpx.get(f"{base_url}/incidents", timeout=5).json()
        total = incidents["total"]
        unresolved = sum(1 for i in incidents["incidents"] if not i["resolved"])
        print(f"\n  Incidents:  {total} total, {unresolved} unresolved")

    except Exception as e:
        print(f"  Error: {e}")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChainOps Agent Demo Seeder")
    parser.add_argument("--url", default=DEFAULT_URL, help="Backend URL")
    parser.add_argument("--status", action="store_true", help="Show current status only")
    args = parser.parse_args()

    if args.status:
        check_status(args.url)
    else:
        seed(args.url)
        check_status(args.url)
