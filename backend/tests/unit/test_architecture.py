"""Architecture fitness tests.

Clean architecture decays quietly. One `from sqlalchemy import ...` in a
domain module is harmless on the day it lands and structural rot six months
later, because nobody notices until the business core can no longer be tested
without a database.

These tests fail the build instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"

# Packages the domain must never reach for. Pydantic is deliberately absent:
# it is a validation library, not a framework, and the policy layer is
# specified in terms of it.
FORBIDDEN_IN_DOMAIN = {
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "asyncpg",
    "psycopg",
    "redis",
    "qdrant_client",
    "fastembed",
    "langgraph",
    "langchain",
    "langchain_core",
    "openai",
    "anthropic",
    "fitz",
    "httpx",
}

# The dependency rule: which app layers each layer may import from.
#
# `composition` is the composition root — the one place allowed to know about
# every layer, because wiring concrete adapters to ports is precisely its job.
# Naming it explicitly keeps that privilege deliberate and confined to a
# single package, rather than letting it leak into `core`.
ALLOWED_INTERNAL_DEPS = {
    "domain": {"domain"},
    "composition": {
        "composition", "core", "domain", "infrastructure", "services", "graph",
    },
    "application": {"application", "domain"},
    "services": {"services", "domain", "core"},
    "graph": {"graph", "services", "domain", "core", "application"},
    "infrastructure": {"infrastructure", "domain", "core"},
    "api": {"api", "application", "services", "domain", "core", "graph"},
    "workers": {"workers", "infrastructure", "services", "domain", "core"},
    "db": {"db", "domain", "core"},
    "core": {"core", "domain"},
    "prompts": {"prompts", "domain"},
}


def python_files(package: str) -> list[Path]:
    root = APP / package
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if "migrations" not in p.parts]


def imported_modules(path: Path) -> set[str]:
    """Top-level module names imported by a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def app_imports(path: Path) -> set[str]:
    """The `app.<layer>` packages a module imports from."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    layers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            parts = node.module.split(".")
            if len(parts) > 1:
                layers.add(parts[1])
    return layers


class TestDomainPurity:
    """The domain is pure Python. It must be testable with no I/O at all."""

    def test_domain_imports_no_framework(self) -> None:
        violations: list[str] = []

        for path in python_files("domain"):
            forbidden = imported_modules(path) & FORBIDDEN_IN_DOMAIN
            if forbidden:
                rel = path.relative_to(APP.parent)
                violations.append(f"{rel} imports {', '.join(sorted(forbidden))}")

        assert not violations, (
            "The domain layer must not depend on frameworks or drivers. "
            "Move the adapter into app/infrastructure/ and depend on a port instead:\n  "
            + "\n  ".join(violations)
        )

    def test_domain_imports_nothing_from_other_app_layers(self) -> None:
        violations: list[str] = []

        for path in python_files("domain"):
            outward = app_imports(path) - {"domain"}
            if outward:
                rel = path.relative_to(APP.parent)
                violations.append(f"{rel} imports app.{', app.'.join(sorted(outward))}")

        assert not violations, (
            "Dependencies point inward; the domain sits at the centre and imports "
            "nothing from outer layers:\n  " + "\n  ".join(violations)
        )

    def test_domain_is_importable_without_any_infrastructure(self) -> None:
        # The real assertion: no database, no Qdrant, no API key, no network.
        import importlib

        for module in (
            "app.domain.enums",
            "app.domain.value_objects",
            "app.domain.entities",
            "app.domain.ports",
            "app.domain.policies",
        ):
            importlib.import_module(module)


class TestLayerDependencies:
    @pytest.mark.parametrize("layer", sorted(ALLOWED_INTERNAL_DEPS))
    def test_layer_respects_the_dependency_rule(self, layer: str) -> None:
        allowed = ALLOWED_INTERNAL_DEPS[layer]
        violations: list[str] = []

        for path in python_files(layer):
            for imported in app_imports(path) - allowed:
                rel = path.relative_to(APP.parent)
                violations.append(f"{rel} imports app.{imported}")

        assert not violations, (
            f"app/{layer}/ may only import from {sorted(allowed)}:\n  "
            + "\n  ".join(violations)
        )

    def test_services_never_reach_for_infrastructure_directly(self) -> None:
        # Services depend on ports and receive adapters by injection. A direct
        # import would make the service untestable without a live backend.
        violations = [
            str(path.relative_to(APP.parent))
            for path in python_files("services")
            if "infrastructure" in app_imports(path)
        ]
        assert not violations, (
            "Services must depend on app.domain.ports and take adapters via "
            "dependency injection:\n  " + "\n  ".join(violations)
        )


class TestPolicyIntegrity:
    """Business rules live in YAML, and a malformed rule must fail loudly at
    startup rather than midway through a customer conversation."""

    def test_every_policy_file_validates(self) -> None:
        from app.domain.policies import load_all

        load_all()

    def test_confidence_weights_sum_to_one(self) -> None:
        from app.domain.policies import confidence_policy

        assert sum(confidence_policy().weights.values()) == pytest.approx(1.0)

    def test_every_intent_category_has_a_rule(self) -> None:
        from app.domain.enums import IntentCategory
        from app.domain.policies import intent_policy

        assert set(intent_policy().categories) == set(IntentCategory)

    def test_finance_defaults_respect_the_regulator(self) -> None:
        from app.domain.policies import finance_policy

        policy = finance_policy()
        assert policy.defaults.tenure_months <= policy.regulatory.max_tenure_months
        assert policy.defaults.down_payment_ratio >= policy.regulatory.min_down_payment_ratio
