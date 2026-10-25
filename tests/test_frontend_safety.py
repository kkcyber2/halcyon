"""Guards against re-introducing markup injection in the browser layer.

The calendar's error path used to assign server text to innerHTML, so any error
message containing markup would have been rendered as HTML. These tests read the
shipped JavaScript, which is what actually runs in a visitor's browser.
"""
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"


def test_app_js_exists():
    assert APP_JS.is_file(), f"expected the browser bundle at {APP_JS}"


def test_error_text_is_never_assigned_to_innerhtml():
    source = APP_JS.read_text(encoding="utf-8")

    # Find every innerHTML assignment and check none of them interpolates a
    # value that comes from a caught error or a response body.
    offenders = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        if "innerHTML" not in line:
            continue
        for tainted in ("e.message", "data.error", "error.message", "err.message"):
            if f"${{{tainted}}}" in line:
                offenders.append((line_no, tainted, line.strip()))

    assert not offenders, "error text interpolated into innerHTML: " + repr(offenders)


def test_error_path_uses_text_content():
    source = APP_JS.read_text(encoding="utf-8")
    assert "err.textContent = e.message" in source, (
        "the booking error path should write the message as text, not markup"
    )
