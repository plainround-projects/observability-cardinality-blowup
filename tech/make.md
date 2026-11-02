# Make (the Makefile)

## What it is

Make is a command-line tool that runs named recipes from a file called `Makefile`. Each recipe is a **target**: a name, optionally the files or other targets it needs (its **prerequisites**), and the shell commands that produce it. Make was designed to rebuild only what is out of date, by comparing file modification times. Teams also use it as a simple "task runner": `make test` is shorter and more memorable than the long command it hides.

## Why this repository uses it

The lesson's commands are `make up`, `make run`, `make test` and `make down`. The Makefile makes them short and gives two knobs, `USERS` and `REQUESTS`, so the same `make run` can be the one-hour lesson-size experiment or the ten-minute quick version.

## Where it appears

| Path | What it does |
| --- | --- |
| `Makefile` | All targets. |
| `.editorconfig` | Keeps tab indentation for the Makefile. |
| `.github/workflows/ci.yml` | Calls `make check`, `make audit`, `make up`, `make test-integration test-e2e`, `make down`. |

## How it works underneath

You type `make up`. Make reads `Makefile` in the current folder, finds the target `up`, and first makes each of its prerequisites (right of the colon). A prerequisite that is a file is rebuilt only if it does not exist or is older than the files it depends on. A prerequisite that is only a name is always run. Then Make runs the target's **recipe**: each line indented with one **tab** character is handed to a shell (`/bin/sh`) as a separate command. If any command exits with a non-zero code, Make stops and reports the error.

Things to know:

- A **variable** is set with `NAME := value` (evaluated once, right away) or `NAME ?= value` (set only if not already set, so you can override it from the shell). `$(NAME)` reads it. `$@` is the name of the current target. `$(MAKE)` is the Make program itself, used to call Make again.
- `.PHONY` lists targets that are *not* files. Without it, a file called `test` in the folder would make `make test` say "nothing to do".
- A line starting with `@` is run without printing the command first.
- `-include .env` reads another Makefile-style file and does not fail if it is missing. `export` with no names passes every Make variable to the commands as environment variables.
- Each recipe line runs in its own shell, so `cd` or a variable set on one line is gone on the next. Joining lines with `\` makes them one command.
- `##` comments after a target are a convention: the `help` target greps them to print a menu.

## Walkthrough of this repository's use

### Variables and settings

```makefile
# make up | run | test | lint | down      (make help lists everything)
PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)
VENV := .venv
PY := $(VENV)/bin/python
STAMP := $(VENV)/.installed
PROMETHEUS_IMAGE := prom/prometheus:v2.54.1
COLLECTOR_IMAGE := otel/opentelemetry-collector-contrib:0.111.0
```

Line 1 lists the main commands. `PYTHON ?= $(shell command -v python3.13 || command -v python3.12 || command -v python3)` picks the first interpreter that exists (`command -v` prints a command's path and fails if it does not exist; `||` tries the next). `VENV`, `PY` and `STAMP` name the virtual environment, its interpreter and a marker file that exists only after a successful install. The last two variables pin the Prometheus and Collector images used by `lint-config` and `test-rules` to the versions in the Compose file.

```makefile
-include .env
export

# The experiment's size. The lesson's numbers are 50,000 users and 200,000 requests; make test-e2e uses a tenth.
USERS ?= 50000
REQUESTS ?= 200000
```

`-include .env` reads `.env` if it exists, `export` hands every Make variable to the commands as an environment variable. Then the experiment size: `USERS ?= 50000` and `REQUESTS ?= 200000` are the lesson's numbers; `?=` means a value from the command line or environment wins, so `make run USERS=5000 REQUESTS=20000` runs a tenth.

```makefile
.PHONY: help install up run load health lint format lint-config test test-rules test-integration test-e2e audit check \
        docker-build down clean
```

`.PHONY` lists the targets that are names, not files. The backslash continues the list.

### `help`, `.env`, the virtual environment

```makefile
help: ## list the targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort

.env:
	cp .env.example .env
	@echo "created .env from .env.example"

$(STAMP): requirements-dev.lock pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --require-hashes -r requirements-dev.lock
	$(VENV)/bin/pip install -q --no-deps -e .
	touch $@
```

`help` is the self-documenting menu: `grep -hE '^[a-z-]+:.*## '` finds every line that looks like `target: ... ## text` (`-h` drops the file names grep would add because `-include .env` puts `.env` in `$(MAKEFILE_LIST)`), `sed -E 's/:.*## /\t/'` turns it into `target<TAB>text`, and `sort` orders them. `.env:` is a file target that copies `.env.example` when `.env` is missing. `$(STAMP)` depends on the lock file and `pyproject.toml`: when either changes, the recipe creates the venv, installs the locked packages with hash checking, installs the project in editable mode without dependencies, and `touch $@` refreshes the marker.

```makefile
install: $(STAMP) ## create .venv from the lock file
```

`install` is only a friendly name for the stamp.

### The stack and the experiment

```makefile
up: .env $(STAMP) ## build and start the app, Prometheus, the Collector, Tempo and Grafana
	docker compose up -d --build --wait --wait-timeout 1800
	$(MAKE) --no-print-directory health

health: $(STAMP) ## the app, Prometheus, Tempo and Grafana all answer
	$(PY) -m cardinality_lab.lab.health_cli
```

`up` builds and starts everything and waits (see `docker-compose.md`), then `health` runs the stack check module (see `argparse-and-urllib.md`).

```makefile
# The whole lesson: baseline, blow-up, diagnosis, fix, guard and the hidden slow dependency. Takes about an hour at
# the lesson's size (make run USERS=5000 REQUESTS=20000 is the quick version).
run: $(STAMP) ## run the six phases and print the report (USERS=50000 REQUESTS=200000)
	$(PY) -m cardinality_lab.lab.scenario_cli --users $(USERS) --requests $(REQUESTS)

load: $(STAMP) ## send traffic only (USERS, REQUESTS)
	$(PY) -m cardinality_lab.lab.load_cli --users $(USERS) --requests $(REQUESTS)
```

`run` is the whole lesson. The comment says it takes about an hour at the lesson's size and gives the quick version. The recipe passes the Make variables as options to the scenario command. `load` sends traffic only.

### Checks

```makefile
lint: $(STAMP) lint-config ## ruff, format check, mypy, import-linter, and the observability configs
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/mypy
	$(VENV)/bin/lint-imports

format: $(STAMP) ## apply ruff's formatting and safe fixes
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .
```

`lint` runs `lint-config` first and then `ruff check .`, `ruff format --check .`, `mypy` and `lint-imports`. `format` applies the fixes.

```makefile
lint-config: ## promtool checks both Prometheus configs and the rules; the Collector validates its config
	docker run --rm --entrypoint promtool -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" $(PROMETHEUS_IMAGE) \
	  check rules /etc/prometheus/rules/cardinality.rules.yml
	docker run --rm --entrypoint sh -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" $(PROMETHEUS_IMAGE) -c \
	  'mkdir -p /tmp/rules && cp /etc/prometheus/rules/*.yml /tmp/rules/ && for f in prometheus.yml prometheus.guarded.yml; do sed "s#/etc/prometheus/rules#/tmp/rules#" /etc/prometheus/$$f > /tmp/$$f && promtool check config /tmp/$$f || exit 1; done'
	docker run --rm -v "$(CURDIR)/observability/collector/config.yaml:/etc/otelcol/config.yaml:ro" $(COLLECTOR_IMAGE) \
	  validate --config=/etc/otelcol/config.yaml
```

`lint-config` runs three one-off containers: `promtool check rules` on the rule file; a `sh -c` script that rewrites the rule path in a copy of each configuration and runs `promtool check config` on both (explained step by step in `prometheus.md`); and the Collector's `validate`.

```makefile
# Unit tests need no containers. Coverage is reported; the domain and application must stay at 95% or more.
test: $(STAMP) ## unit and config-lint tests with coverage (no stack needed)
	$(PY) -m pytest tests/unit tests/observability --cov=cardinality_lab --cov-report=term
	$(PY) -m coverage report --include='src/cardinality_lab/domain/*,src/cardinality_lab/application/*' --fail-under=95
```

`test` runs pytest on the unit and observability tests with coverage for `cardinality_lab`, then fails if the domain and application layers are under 95 percent.

```makefile
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
```

`test-rules` replays the alert tests; `test-integration` and `test-e2e` run the tests with the matching marker (the end-to-end test runs the whole scenario at a tenth of the size); `audit` checks the locked dependencies for known vulnerabilities; `check` has no recipe, only prerequisites: `lint`, `test` and `test-rules`.

```makefile
docker-build: ## build the app image
	docker build -t observability-cardinality-blowup:dev .

down: ## stop the stack and delete its data
	docker compose down -v

clean: down
	rm -rf $(VENV) logs .pytest_cache .mypy_cache .ruff_cache .coverage .import_linter_cache
```

`docker-build` builds the image; `down` stops the stack and deletes its data; `clean` depends on `down` and then deletes the virtual environment and every cache.

## Try it yourself

```bash
make help
```

Expected: one line per target with its description.

```bash
make -n run USERS=5000 REQUESTS=20000
```

Expected: the command that would run: `.venv/bin/python -m cardinality_lab.lab.scenario_cli --users 5000 --requests 20000`.

```bash
make -n run
```

Expected: the same with `--users 50000 --requests 200000`.

```bash
make install && ls .venv/.installed
```

Expected: the stamp exists; a second `make install` prints nothing.

```bash
make check
```

Expected: ruff, mypy, import-linter pass; pytest passes with coverage; `promtool` prints `SUCCESS`.

## Mistakes people make

- **Spaces instead of a tab** at the start of a recipe line: Make stops with "missing separator". The `.editorconfig` in this repository sets `indent_style = tab` for the Makefile.
- **Forgetting `.PHONY`** for a target that is not a file.
- **Assuming `cd` carries over** to the next line.
- **Using `$VAR` for a Make variable.** Make needs `$(VAR)`. A single `$` is for Make; to give the shell a `$`, write `$$`.
- **Silent failure in a pipeline.** In `a | b`, the exit code is that of `b`. Recipes here avoid hiding failures in pipes.

## Check yourself

1. What does `.PHONY` do? *It marks targets that are names, not files, so they always run.*
2. Why must recipe lines start with a tab? *Make uses the tab to tell a recipe command from other lines.*
3. What is the difference between `:=` and `?=`? *`:=` always sets; `?=` sets only if the variable has no value yet, so the environment can override it.*
4. What does a leading `@` do? *It hides the command line itself; only its output is shown.*
5. If a prerequisite file is newer than the target file, what does Make do? *It runs the recipe again.*

## Further reading

- GNU Make manual: https://www.gnu.org/software/make/manual/make.html (this repository works with GNU Make 3.81, the version macOS ships)
