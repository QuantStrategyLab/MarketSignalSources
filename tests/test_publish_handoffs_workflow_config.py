from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "publish-platform-handoffs.yml"


def test_publish_platform_handoffs_workflow_uses_secrets_for_gcp_vars() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "secrets.GCP_PROJECT_ID" in content
    assert "secrets.GCP_WORKLOAD_IDENTITY_PROVIDER" in content
    assert "secrets.GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT" in content
    assert "secrets.MARKET_SIGNAL_GCS_PREFIX" in content
    assert "vars.GCP_PROJECT_ID" not in content
    assert "vars.GCP_WORKLOAD_IDENTITY_PROVIDER" not in content
    assert "vars.GCP_WORKLOAD_IDENTITY_SERVICE_ACCOUNT" not in content
    assert "vars.MARKET_SIGNAL_GCS_PREFIX" not in content
    assert "${GCS_PREFIX}" not in content.split("Append job summary", 1)[1]
