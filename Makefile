.PHONY: test lint worker worker-simple docker-build docker-run

# ── Dev ───────────────────────────────────────────────────
test:
	pytest -q

lint:
	flake8 .

# ── Workers ───────────────────────────────────────────────
worker:
	rq worker pop

worker-simple:
	rq worker pop --worker-class rq.worker.SimpleWorker

# ── Docker (local) ────────────────────────────────────────
docker-build:
	docker build -t pop .

docker-run:
	docker run --env-file .env -p 10000:10000 pop
