#!/usr/bin/env python3
"""Cross-platform task runner for the Alto AI Support Orchestrator.

`make` is not available on Windows, where this project is primarily
developed, so this module is the single source of truth for project
commands. The Makefile delegates here so Linux and CI users can keep
typing `make <target>`.

Standard library only — it must run before any dependency is installed.

Usage:
    python tasks.py <target> [args...]
    python tasks.py help
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

# Populated by the @task decorator.
TASKS: dict[str, Callable[[Sequence[str]], int]] = {}
HELP: dict[str, str] = {}


# ─────────────────────────────────────────────────────────────────────
# Plumbing
# ─────────────────────────────────────────────────────────────────────
def task(help_text: str) -> Callable[[Callable[..., int | None]], Callable[..., int | None]]:
    """Register a function as a runnable target, keyed by its name."""

    def decorator(fn: Callable[..., int | None]) -> Callable[..., int | None]:
        name = fn.__name__.replace("_", "-")
        TASKS[name] = fn  # type: ignore[assignment]
        HELP[name] = help_text
        return fn

    return decorator


class Colour:
    """ANSI codes, suppressed when stdout is not an interactive terminal."""

    _on = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

    BOLD = "\033[1m" if _on else ""
    DIM = "\033[2m" if _on else ""
    RED = "\033[31m" if _on else ""
    GREEN = "\033[32m" if _on else ""
    YELLOW = "\033[33m" if _on else ""
    RESET = "\033[0m" if _on else ""


def info(message: str) -> None:
    print(f"{Colour.BOLD}==>{Colour.RESET} {message}")


def ok(message: str) -> None:
    print(f"{Colour.GREEN}[ok]{Colour.RESET} {message}")


def warn(message: str) -> None:
    print(f"{Colour.YELLOW}[warn]{Colour.RESET} {message}")


def fail(message: str) -> None:
    print(f"{Colour.RED}[fail]{Colour.RESET} {message}", file=sys.stderr)


def run(cmd: Sequence[str], cwd: Path | None = None, check: bool = True) -> int:
    """Run a command, echoing it first. Returns its exit code."""
    print(f"{Colour.DIM}$ {' '.join(cmd)}{Colour.RESET}")
    code = subprocess.call(list(cmd), cwd=str(cwd or ROOT))
    if check and code != 0:
        raise SystemExit(code)
    return code


def compose(*args: str, check: bool = True) -> int:
    """Invoke `docker compose` with the project's compose file."""
    return run(["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), *args], check=check)


def require(binary: str) -> None:
    if shutil.which(binary) is None:
        raise SystemExit(f"{Colour.RED}Required executable not found on PATH: {binary}{Colour.RESET}")


def ensure_env_file() -> None:
    """Create .env from the template on first run so `up` works immediately."""
    env, template = ROOT / ".env", ROOT / ".env.example"
    if env.exists():
        return
    if not template.exists():
        raise SystemExit("Neither .env nor .env.example is present.")
    shutil.copyfile(template, env)
    warn("No .env found - created one from .env.example. Review it before use.")


# ─────────────────────────────────────────────────────────────────────
# Stack lifecycle
# ─────────────────────────────────────────────────────────────────────
@task("Start the data plane (Postgres, Redis, Qdrant) and wait for health")
def up(argv: Sequence[str]) -> int:
    require("docker")
    ensure_env_file()
    compose("up", "-d", *argv)
    return health([])


@task("Stop all services, preserving volumes")
def down(argv: Sequence[str]) -> int:
    require("docker")
    return compose("down", *argv)


@task("Stop all services and DESTROY all data volumes")
def reset(argv: Sequence[str]) -> int:
    require("docker")
    warn("This deletes all Postgres data and Qdrant collections.")
    if "--yes" not in argv and input("Type 'yes' to confirm: ").strip().lower() != "yes":
        info("Aborted — nothing was deleted.")
        return 1
    return compose("down", "-v")


@task("Show service status")
def ps(argv: Sequence[str]) -> int:
    require("docker")
    return compose("ps", *argv)


@task("Tail service logs (e.g. `logs qdrant`)")
def logs(argv: Sequence[str]) -> int:
    require("docker")
    return compose("logs", "-f", "--tail", "100", *argv)


@task("Wait for every service to report healthy, then probe each endpoint")
def health(argv: Sequence[str]) -> int:
    """Block until Compose reports health, then verify each service answers.

    Compose health checks run inside the container network; these probes run
    from the host, so together they confirm the published ports work too.
    """
    require("docker")
    deadline = time.monotonic() + 120

    info("Waiting for containers to report healthy...")
    while time.monotonic() < deadline:
        out = subprocess.run(
            ["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "ps",
             "--format", "{{.Service}}\t{{.Health}}"],
            capture_output=True, text=True, cwd=str(ROOT),
        ).stdout.strip()

        rows = [line.split("\t") for line in out.splitlines() if line.strip()]
        if rows and all(len(r) > 1 and r[1] == "healthy" for r in rows):
            for service, _ in rows:
                ok(f"{service} healthy")
            break
        time.sleep(2)
    else:
        fail("Timed out after 120s waiting for services. Try: python tasks.py logs")
        compose("ps", check=False)
        return 1

    return _probe_from_host()


def _probe_from_host() -> int:
    """Confirm the published ports are reachable from outside Docker."""
    env = _read_env()
    failures: list[str] = []

    info("Probing published ports from the host...")

    qdrant_port = env.get("QDRANT_HTTP_PORT", "6333")
    try:
        with urllib.request.urlopen(f"http://localhost:{qdrant_port}/healthz", timeout=5) as r:
            if r.status == 200:
                ok(f"qdrant  http://localhost:{qdrant_port} responding")
            else:
                failures.append(f"qdrant returned HTTP {r.status}")
    except (urllib.error.URLError, OSError) as exc:
        failures.append(f"qdrant unreachable on port {qdrant_port}: {exc}")

    for service, port_key, default, probe in (
        ("postgres", "POSTGRES_PORT", "5432", ["pg_isready", "-U", env.get("POSTGRES_USER", "alto")]),
        ("redis", "REDIS_PORT", "6379", ["redis-cli", "ping"]),
    ):
        port = env.get(port_key, default)
        code = subprocess.call(
            ["docker", "compose", "-f", str(ROOT / "docker-compose.yml"), "exec", "-T", service, *probe],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(ROOT),
        )
        if code == 0:
            ok(f"{service:<9s}localhost:{port} responding")
        else:
            failures.append(f"{service} probe failed")

    if failures:
        for f in failures:
            fail(f)
        return 1

    print()
    ok("Data plane is up and reachable.")
    return 0


def _read_env() -> dict[str, str]:
    """Parse .env into a dict. Deliberately minimal — no interpolation."""
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.split("#")[0].strip()
    return env


# ─────────────────────────────────────────────────────────────────────
# Quality gates
#
# These become active as their modules land. Until then they report the
# gap honestly rather than exiting 0 and implying the check ran.
# ─────────────────────────────────────────────────────────────────────
def _pending(module: str, what: str) -> int:
    warn(f"{what} arrives in Module {module}; nothing to run yet.")
    return 0


@task("Run the backend test suite")
def test(argv: Sequence[str]) -> int:
    if not (BACKEND / "pyproject.toml").exists():
        return _pending("2", "Backend tests")
    return run([sys.executable, "-m", "pytest", *(argv or ["-q"])], cwd=BACKEND)


@task("Lint and format-check the backend")
def lint(argv: Sequence[str]) -> int:
    if not (BACKEND / "pyproject.toml").exists():
        return _pending("2", "Backend linting")
    run([sys.executable, "-m", "ruff", "check", "."], cwd=BACKEND)
    return run([sys.executable, "-m", "ruff", "format", "--check", "."], cwd=BACKEND)


@task("Auto-format the backend")
def fmt(argv: Sequence[str]) -> int:
    if not (BACKEND / "pyproject.toml").exists():
        return _pending("2", "Backend formatting")
    run([sys.executable, "-m", "ruff", "check", "--fix", "."], cwd=BACKEND)
    return run([sys.executable, "-m", "ruff", "format", "."], cwd=BACKEND)


@task("Type-check backend (mypy strict) and frontend (tsc)")
def typecheck(argv: Sequence[str]) -> int:
    code = 0
    if (BACKEND / "pyproject.toml").exists():
        code |= run([sys.executable, "-m", "mypy", "app"], cwd=BACKEND, check=False)
    else:
        _pending("2", "Backend type-checking")
    if (FRONTEND / "package.json").exists():
        code |= run(["npx", "tsc", "--noEmit"], cwd=FRONTEND, check=False)
    else:
        _pending("10", "Frontend type-checking")
    return code


@task("Run every quality gate: lint, typecheck, test")
def check(argv: Sequence[str]) -> int:
    return lint([]) | typecheck([]) | test([])


# ─────────────────────────────────────────────────────────────────────
# Data pipeline
# ─────────────────────────────────────────────────────────────────────
@task("Ingest PDFs, policies and the vehicle catalog into Qdrant")
def ingest(argv: Sequence[str]) -> int:
    if not (BACKEND / "app" / "workers" / "ingestion" / "__main__.py").exists():
        return _pending("5", "The ingestion worker")
    return run([sys.executable, "-m", "app.workers.ingestion", *argv], cwd=BACKEND)


@task("Seed demo customers, vehicles and departments")
def seed(argv: Sequence[str]) -> int:
    if not (BACKEND / "app" / "db" / "seed.py").exists():
        return _pending("3", "The seed script")
    return run([sys.executable, "-m", "app.db.seed", *argv], cwd=BACKEND)


@task("Run the golden-set evaluation suite")
def evaluate(argv: Sequence[str]) -> int:
    if not (ROOT / "data" / "eval" / "golden_set.jsonl").exists():
        return _pending("14", "The evaluation suite")
    return run([sys.executable, "-m", "app.services.evaluation", *argv], cwd=BACKEND)


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────
@task("Show this help")
def help_(argv: Sequence[str]) -> int:
    print(f"\n{Colour.BOLD}Alto AI Support Orchestrator{Colour.RESET}\n")
    print(f"  {Colour.DIM}python tasks.py <target> [args...]{Colour.RESET}\n")
    for name in sorted(TASKS):
        label = "help" if name == "help-" else name
        print(f"  {Colour.BOLD}{label:<12}{Colour.RESET} {HELP[name]}")
    print()
    return 0


TASKS["help"] = TASKS.pop("help-")
HELP["help"] = HELP.pop("help-")
# `eval` is a Python builtin; expose the friendlier alias too.
TASKS["eval"] = TASKS["evaluate"]
HELP["eval"] = HELP["evaluate"]


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        return help_([])

    target, *rest = argv
    if target not in TASKS:
        fail(f"Unknown target: {target}")
        print(f"Run {Colour.BOLD}python tasks.py help{Colour.RESET} for the list.")
        return 1

    try:
        return TASKS[target](rest) or 0
    except KeyboardInterrupt:
        print()
        warn("Interrupted.")
        return 130
    except SystemExit as exc:
        return int(exc.code or 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
