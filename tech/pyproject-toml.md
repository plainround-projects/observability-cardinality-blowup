# pyproject.toml, setuptools and TOML

## What it is

`pyproject.toml` is the single configuration file of a modern Python project. It is written in **TOML**, a configuration format made of `[tables]` (named sections) and `key = value` lines. Values can be strings in double quotes, numbers, `true`/`false`, lists in square brackets and small tables in curly braces.

The file serves three readers. The **build tool** (here, setuptools) reads `[build-system]` and `[project]` to learn the package name, version, dependencies and command-line entry points. `pip` reads the same file to install the project. And each **developer tool** (ruff, mypy, pytest, coverage, import-linter) reads its own `[tool.<name>]` table, so there is no scattered `.ini` or `.cfg` files.

## Why this repository uses it

One file describes the package, its commands, its dependencies and the settings of every developer tool, so a learner finds all of it in one place. The package metadata also creates the four commands (`cardinality-lab-app`, `-health`, `-load`, `-scenario`) that the Dockerfile, Compose and `make` call.

## Where it appears

| Path | What it does |
| --- | --- |
| `pyproject.toml` | Everything in this note. |
| `Dockerfile` | `pip install --no-deps .` builds and installs the package from it. |
| `Makefile` | `pip install -e .` for development. |

## How it works underneath

`pip install .` reads `[build-system]`, installs the listed build requirements (`setuptools>=75`) in a temporary environment, then calls the named **build backend** (`setuptools.build_meta`) to turn the source folder into an installable package (a "wheel"). A wheel is a zip file with the code and metadata. `pip install -e .` installs in **editable** mode: it adds a link to the source folder so that edits take effect without reinstalling.

`[project.scripts]` maps a command name to `module:function`. At install time the tool writes a small launcher file into the environment's `bin/` folder. When you run `three-signals-back`, the launcher imports `three_signals.interfaces.back_main` and calls its `main()`.

`[project.optional-dependencies]` defines an "extra" (here `dev`). `pip install '.[dev]'` installs the project plus the extra. `[tool.setuptools.packages.find] where = ["src"]` tells setuptools to look for packages inside the `src/` folder; this "src layout" prevents tests from accidentally importing the source folder instead of the installed package.

## Walkthrough of this repository's use

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```

`[build-system]` is a table. `requires = ["setuptools>=75"]` lists what must be installed to build the package; `build-backend = "setuptools.build_meta"` names the Python object that builds it.

```toml
[project]
name = "observability-cardinality-blowup"
version = "0.1.0"
description = "A checkout app and a real Prometheus that you overload on purpose with a user_id label, diagnose from the backend's own statistics, fix by moving the detail to trace attributes, and then use traces to find a slow dependency that averaged metrics hide."
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
authors = [{ name = "Sumit Srivastava" }]
```

`[project]` holds the metadata: `name`, `version`, a `description`, `readme` (the file shown as the long description; the Dockerfile copies `README.md` for this reason), `requires-python = ">=3.12"` (pip refuses older interpreters), `license = { text = "MIT" }` and `authors`, a list of small tables. In TOML `{ text = "MIT" }` is an **inline table**.

```toml
dependencies = [
    "flask>=3.1,<4",
    "waitress>=3.0,<4",
    "prometheus-client>=0.21,<1",
    "requests>=2.32,<3",
    "opentelemetry-distro>=0.66b1",
    "opentelemetry-exporter-otlp-proto-http>=1.45,<2",
    "opentelemetry-instrumentation-flask>=0.66b1",
]
```

`dependencies` is the run-time list, each with a version range written as `flask>=3.1,<4`: at least 3.1, below 4. `prometheus-client` exposes the metrics page; `requests` is used by the load generator and the store clients. `opentelemetry-distro` brings the `opentelemetry-instrument` command; `opentelemetry-exporter-otlp-proto-http` sends OTLP over HTTP; `opentelemetry-instrumentation-flask` automatically creates a span per web request. The ranges are wide on purpose; the lock files make the installed versions exact (see `uv-and-lock-files.md`).

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8,<10",
    "pytest-cov>=5",
    "ruff>=0.6",
    "mypy>=1.11",
    "import-linter>=2.0",
    "pip-audit>=2.7",
    "types-requests",
    "types-PyYAML",
    "pyyaml>=6",
]
```

`[project.optional-dependencies]` defines the `dev` extra: pytest and pytest-cov (tests), ruff (lint and format), mypy (types), import-linter (import rules), pip-audit (vulnerabilities), `types-requests` and `types-PyYAML` (type information for those libraries), and `pyyaml` (used by the configuration tests).

```toml
[project.scripts]
cardinality-lab-app = "cardinality_lab.interfaces.main:main"
cardinality-lab-health = "cardinality_lab.interfaces.health_cli:main"
cardinality-lab-load = "cardinality_lab.lab.load_cli:main"
cardinality-lab-scenario = "cardinality_lab.lab.scenario_cli:main"
```

`[project.scripts]` maps command names to functions, `name = "package.module:function"`. Installing the project writes a launcher for each into the environment's `bin` folder. For example `cardinality-lab-health` runs `cardinality_lab.interfaces.health_cli:main`; Compose's health check calls it, and `cardinality-lab-app` starts the app. The note `argparse-and-urllib.md` explains why `main` returns the exit code.

```toml
[tool.setuptools.packages.find]
where = ["src"]
```

`[tool.setuptools.packages.find]` with `where = ["src"]` tells setuptools to look for packages under `src/`.

The remaining tables, `[tool.ruff*]`, `[tool.mypy*]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]` and `[tool.importlinter*]`, are explained in `ruff.md`, `mypy.md`, `pytest.md` and `import-linter.md`.

## Try it yourself

```bash
.venv/bin/python -c "import tomllib; d = tomllib.load(open('pyproject.toml','rb')); print(d['project']['name'], list(d['project']['scripts']))"
```

Expected: the name and the four command names. (`tomllib` reads TOML and is in the standard library since Python 3.11.)

```bash
ls .venv/bin | grep cardinality-lab
```

Expected: the four launchers.

```bash
cat .venv/bin/cardinality-lab-health
```

Expected: a short Python script that imports `main` from `cardinality_lab.interfaces.health_cli` and runs it.

```bash
.venv/bin/pip show observability-cardinality-blowup | grep -E "^(Name|Version)"
```

Expected: `Name: observability-cardinality-blowup`, `Version: 0.1.0`.

```bash
.venv/bin/pip install --dry-run --no-deps -e . 2>&1 | tail -1
```

Expected: a line starting `Would install observability_cardinality_blowup-0.1.0`.

## Mistakes people make

- **Indenting TOML like YAML.** Indentation has no meaning in TOML; the `[table]` headers do.
- **Forgetting the quotes** around strings.
- **Mixing `[tool.x]` and `[[tool.x.y]]`.** Double brackets define one item of a *list* of tables, and repeating the header adds another item.
- **Loose dependency ranges without a lock.** The ranges here are wide on purpose; the lock files make installs exact.

## Check yourself

1. What are the three readers of `pyproject.toml`? *The build tool, pip, and the developer tools with `[tool.*]` tables.*
2. What does `[project.scripts]` create? *Command-line launchers that call a Python function.*
3. What does `pip install -e .` do differently from `pip install .`? *It links to the source so edits apply without reinstalling.*
4. What do double square brackets mean in TOML? *One element of a list of tables.*
5. Why put the code in `src/`? *So tests import the installed package, not the folder.*

## Further reading

- Writing `pyproject.toml`: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
- TOML 1.0 specification: https://toml.io/en/v1.0.0
- setuptools (75 and newer): https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html
