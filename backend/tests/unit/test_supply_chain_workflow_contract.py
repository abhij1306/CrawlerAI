from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_ROOT = PROJECT_ROOT / ".github" / "workflows"
_USES_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)")
_IMMUTABLE_ACTION = re.compile(r"^[^#\s]+@[0-9a-f]{40}$")


def _workflow(name: str) -> str:
    return (WORKFLOW_ROOT / name).read_text(encoding="utf-8")


def test_every_action_reference_is_immutable() -> None:
    unpinned: list[str] = []
    workflow_paths = sorted(
        [*WORKFLOW_ROOT.glob("*.yml"), *WORKFLOW_ROOT.glob("*.yaml")]
    )
    for path in workflow_paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = _USES_LINE.match(line)
            if match is None or match.group(1).startswith("./"):
                continue
            if _IMMUTABLE_ACTION.fullmatch(match.group(1)) is None:
                unpinned.append(f"{path.name}:{line_number}:{line.strip()}")

    assert unpinned == []


def test_container_supply_chain_builds_scans_and_publishes_sboms() -> None:
    workflow = _workflow("supply-chain.yml")

    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "backend/Dockerfile" in workflow
    assert "frontend/Dockerfile" in workflow
    assert "format: spdx-json" in workflow
    assert "severity: HIGH,CRITICAL" in workflow
    assert "ignore-unfixed: true" in workflow
    assert "exit-code: 1" in workflow
    assert "retention-days: 30" in workflow


def test_ecr_gate_uses_oidc_temporary_helper_and_fail_closed_policy() -> None:
    workflow = _workflow("ecr-enhanced-scan-gate.yml")

    assert "contents: read\n  id-token: write" in workflow
    assert "persist-credentials: false" in workflow
    assert "environment: production" in workflow
    assert "default: false" in workflow
    assert "vars.AWS_RELEASE_ROLE_ARN" in workflow
    assert 'AWS_ECR_DISABLE_CACHE: "true"' in workflow
    assert 'DOCKER_CONFIG="${RUNNER_TEMP}/docker-ecr"' in workflow
    assert 'echo \'{"credsStore":"ecr-login"}\'' in workflow
    assert "get-login-password" not in workflow
    assert "docker login" not in workflow
    assert "ecr_scan_gate.py" in workflow
    assert "risk-acceptance-reference" in workflow


def test_existing_dependency_secret_and_code_scans_remain_blocking() -> None:
    ci = _workflow("ci.yml")

    assert "uv lock --check" in ci
    assert "python -m pip_audit --vulnerability-service osv" in ci
    assert "vp install --frozen-lockfile" in ci
    assert "vp pm audit -- --audit-level=high" in ci
    assert "node ../scripts/quality.mjs --mode check --scope backend" in ci
    assert "node scripts/quality.mjs --mode check --scope frontend" in ci
    assert "CRAWLERAI_OPENAPI_JSON" in ci
    assert "--cov-report=xml" in ci
    assert "vp test --coverage" in ci
    assert "name: Required" in ci
    assert (WORKFLOW_ROOT / "gitleaks.yml").is_file()
    assert (WORKFLOW_ROOT / "codeql.yml").is_file()
