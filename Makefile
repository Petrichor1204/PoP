.PHONY: test lint docker-build docker-run

# ── Dev ───────────────────────────────────────────────────
test:
	pytest -q

lint:
	flake8 .

# ── Docker (local) ────────────────────────────────────────
docker-build:
	docker build -t pop .

docker-run:
	docker run --env-file .env -p 10000:10000 pop
