import re

from scripts.gate_codex_app_review import scan_diff


def test_scan_diff_redacts_hardcoded_secret_values() -> None:
    secret_field = "API" + "_KEY"
    secret_value = "super" + "secretvalue123456"
    diff = "\n".join(
        (
            "diff --git a/app.py b/app.py",
            "+++ b/app.py",
            f'+{secret_field} = "{secret_value}"',
        )
    )

    violations = scan_diff(diff, path_patterns=[])

    assert len(violations) == 1
    assert "<redacted>" in violations[0]
    assert secret_value not in violations[0]
    assert re.search(r"api[_\\s]?key", violations[0], re.IGNORECASE)
