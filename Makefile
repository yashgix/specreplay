PYTHON ?= python
export SPECREPLAY_NODE ?= $(shell command -v node)
export SPECREPLAY_NODE_MODULES ?= $(CURDIR)/node_modules

.PHONY: lint typecheck test experiment wide readme

lint:
	ruff check .
	ruff format --check .

typecheck:
	$(SPECREPLAY_NODE) $(SPECREPLAY_NODE_MODULES)/typescript/bin/tsc -p web/tsconfig.json

test:
	$(PYTHON) -m unittest discover -s tests
	$(PYTHON) tools/run_acceptance.py

experiment:
	$(PYTHON) experiment.py --out results/metrics.json

wide:
	$(PYTHON) wide.py --out results/wide.json

readme:
	$(PYTHON) demo.py --readme README.md --out README.md
