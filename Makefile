# make up | run | test | lint | down      (make help lists everything)
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
PROMETHEUS_IMAGE := prom/prometheus:v2.54.1
COLLECTOR_IMAGE := otel/opentelemetry-collector-contrib:0.111.0

-include .env
export

# The experiment's size. The lesson's numbers are 50,000 users and 200,000 requests; make test-e2e uses a tenth.
USERS ?= 50000
REQUESTS ?= 200000

.PHONY: help install up run load health lint format lint-config test test-rules test-integration test-e2e audit check \
        docker-build down clean

help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort

.env:
	cp .env.example .env
	@echo "created .env from .env.example"

$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@

install: $(STAMP) ## create .venv from the lock file

up: .env $(STAMP) ## build and start the app, Prometheus, the Collector, Tempo and Grafana
	docker compose up -d --build --wait --wait-timeout 900
	$(MAKE) --no-print-directory health

health: $(STAMP) ## the app, Prometheus, Tempo and Grafana all answer
	$(PY) -m cardinality_lab.lab.health_cli

# The whole lesson: baseline, blow-up, diagnosis, fix, guard and the hidden slow dependency. Takes about an hour at
# the lesson's size (make run USERS=5000 REQUESTS=20000 is the quick version).
run: $(STAMP) ## run the six phases and print the report (USERS=50000 REQUESTS=200000)
	$(PY) -m cardinality_lab.lab.scenario_cli --users $(USERS) --requests $(REQUESTS)

load: $(STAMP) ## send traffic only (USERS, REQUESTS)
	$(PY) -m cardinality_lab.lab.load_cli --users $(USERS) --requests $(REQUESTS)

lint: $(STAMP) lint-config ## ruff, format check, mypy, import-linter, and the observability configs
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports

format: $(STAMP) ## apply ruff's formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

lint-config: ## promtool checks both Prometheus configs and the rules; the Collector validates its config
	docker run --rm --entrypoint promtool -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" $(PROMETHEUS_IMAGE) \
	  check rules /etc/prometheus/rules/cardinality.rules.yml
	docker run --rm --entrypoint sh -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" $(PROMETHEUS_IMAGE) -c \
	  'mkdir -p /tmp/rules && cp /etc/prometheus/rules/*.yml /tmp/rules/ && for f in prometheus.yml prometheus.guarded.yml; do sed "s#/etc/prometheus/rules#/tmp/rules#" /etc/prometheus/$$f > /tmp/$$f && promtool check config /tmp/$$f || exit 1; done'
	docker run --rm -v "$(CURDIR)/observability/collector/config.yaml:/etc/otelcol/config.yaml:ro" $(COLLECTOR_IMAGE) \
	  validate --config=/etc/otelcol/config.yaml

# Unit tests need no containers. Coverage is reported; the domain and application must stay at 95% or more.
test: $(STAMP) ## unit and config-lint tests with coverage (no stack needed)
	$(PY) -m pytest tests/unit tests/observability --cov=cardinality_lab --cov-report=term
	$(PY) -m coverage report --include='src/cardinality_lab/domain/*,src/cardinality_lab/application/*' --fail-under=95

test-rules: ## replay series through promtool and assert the alerts fire (and stay silent when they should)
	docker run --rm --entrypoint promtool -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" $(PROMETHEUS_IMAGE) \
	  test rules /etc/prometheus/tests/cardinality.rules.test.yml

test-integration: $(STAMP) ## the running app's /metrics and the stores answering (make up first)
	$(PY) -m pytest tests/integration -m integration

test-e2e: $(STAMP) ## the whole scenario at a tenth of the size, asserted number by number (make up first)
	$(PY) -m pytest tests/e2e -m e2e

audit: $(STAMP) ## check the locked dependencies for known vulnerabilities
	$(VENV)/bin/pip-audit --no-deps --disable-pip -r requirements-dev.lock

check: lint test test-rules ## everything that needs no running stack

docker-build: ## build the app image
	docker build -t observability-cardinality-blowup:dev .

down: ## stop the stack and delete its data
	docker compose down -v

clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .coverage .import_linter_cache
