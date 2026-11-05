.PHONY: install test lint eval run mcp docker

install:
	pip install -r requirements-dev.txt

test:
	pytest -q

lint:
	ruff check .

eval:
	python -m fixflow.evals --compare

run:
	uvicorn fixflow.api:app --reload

mcp:
	python -m fixflow.mcp_server

docker:
	docker build -t fixflow . && docker run --rm -p 8000:8000 fixflow
