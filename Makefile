.PHONY: up down build logs clean restart status

# ─── Start everything ──────────────────────────────────────────────────────
up:
	@echo "🚀 Starting ChainOps Agent..."
	docker compose up -d --build
	@echo ""
	@echo "  ✅ Agent UI:      http://localhost:8000"
	@echo "  ✅ Grafana:       http://localhost:3000  (admin / chainops)"
	@echo "  ✅ Prometheus:    http://localhost:9090"
	@echo "  ✅ Alertmanager:  http://localhost:9093"
	@echo "  ✅ Metrics:       http://localhost:9101/metrics"

# ─── Stop everything ──────────────────────────────────────────────────────
down:
	docker compose down

# ─── Rebuild without cache ────────────────────────────────────────────────
build:
	docker compose build --no-cache

# ─── Tail logs ────────────────────────────────────────────────────────────
logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-exporter:
	docker compose logs -f exporter

# ─── Restart a single service ─────────────────────────────────────────────
restart:
	docker compose restart $(service)

# ─── Container status ─────────────────────────────────────────────────────
status:
	docker compose ps

# ─── Nuke all volumes (clean slate) ──────────────────────────────────────
clean:
	docker compose down -v
	@echo "🗑  Volumes removed — Prometheus and Grafana data cleared."

# ─── Quick API tests (requires httpie or curl) ───────────────────────────
test-ask:
	curl -s -X POST http://localhost:8000/ask \
		-H "Content-Type: application/json" \
		-d '{"question": "What is the current network health?"}' | python3 -m json.tool

test-snapshot:
	curl -s http://localhost:8000/metrics/snapshot | python3 -m json.tool

test-detect:
	curl -s -X POST http://localhost:8000/detect | python3 -m json.tool

test-incidents:
	curl -s http://localhost:8000/incidents | python3 -m json.tool

# ─── Demo / Hackathon ─────────────────────────────────────────────────────
demo-seed:
	python3 demo_seed.py

demo-status:
	python3 demo_seed.py --status

present:
	@echo ""
	@echo "  🎯 ChainOps Agent — Demo Ready"
	@echo ""
	@echo "  Agent UI:     http://localhost:8000"
	@echo "  Grafana:      http://localhost:3000  (admin/chainops)"
	@echo "  Prometheus:   http://localhost:9090"
	@echo ""
	@echo "  Seeding demo incidents..."
	@python3 demo_seed.py
