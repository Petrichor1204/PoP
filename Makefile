.PHONY: test worker worker-simple

test:
	pytest -q

worker:
	rq worker pop

worker-simple:
	rq worker pop --worker-class rq.worker.SimpleWorker
