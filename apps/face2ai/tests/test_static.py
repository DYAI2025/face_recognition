"""Static shell guards.

These tests protect the dependency-free browser shell described in ADR-001 and
docs/UI_DIRECTION.md: every asset referenced by index.html is served, the ES
module graph resolves, nothing is loaded from the network, and the enrollment
flow keeps its explicit-consent step and native <dialog> surfaces.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "face2ai_app" / "static"
INDEX = STATIC / "index.html"
JS_DIR = STATIC / "js"

ASSET_REF = re.compile(r"""(?:src|href)=["'](/assets/[^"']+)["']""")
IMPORT_REF = re.compile(r"""from\s+["'](\.\/[^"']+)["']""")
EXTERNAL_REF = re.compile(r"""(?:https?:)?//(?!127\.0\.0\.1|localhost|www\.w3\.org/)[a-z0-9.-]+\.[a-z]{2,}""", re.I)


def _asset_refs() -> list[str]:
    return ASSET_REF.findall(INDEX.read_text(encoding="utf-8"))


def _js_files() -> list[Path]:
    return sorted(JS_DIR.glob("*.js"))


def test_index_is_served_and_declares_module_entry(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'type="module"' in response.text
    assert "/assets/js/app.js" in response.text


def test_every_asset_referenced_by_index_is_served(client):
    refs = _asset_refs()
    assert refs, "index.html references no /assets/ files"
    for ref in refs:
        assert client.get(ref).status_code == 200, ref


def test_es_module_import_graph_resolves():
    files = _js_files()
    assert files, "no ES modules found"
    for file in files:
        for target in IMPORT_REF.findall(file.read_text(encoding="utf-8")):
            assert (JS_DIR / target).is_file(), f"{file.name} imports missing {target}"


@pytest.mark.parametrize("path", [INDEX, STATIC / "css" / "app.css", *_js_files()])
def test_static_shell_loads_nothing_from_the_network(path: Path):
    text = path.read_text(encoding="utf-8")
    hits = [m.group(0) for m in EXTERNAL_REF.finditer(text)]
    assert not hits, f"{path.name} references external hosts: {hits}"


def test_enrollment_uses_native_dialog_with_required_consent():
    html = INDEX.read_text(encoding="utf-8")
    assert re.search(r"<dialog[^>]*id=\"enrollDialog\"", html)
    consent = re.search(r"<input[^>]*id=\"consent\"[^>]*>", html)
    assert consent, "enrollment dialog has no consent control"
    assert 'type="checkbox"' in consent.group(0)
    assert "required" in consent.group(0)


def test_destructive_actions_do_not_use_blocking_browser_prompts():
    for file in _js_files():
        text = file.read_text(encoding="utf-8")
        assert not re.search(r"\b(?:window\.)?(?:confirm|alert|prompt)\(", text), file.name
    html = INDEX.read_text(encoding="utf-8")
    assert re.search(r"<dialog[^>]*id=\"eraseDialog\"", html)


def test_shell_never_presents_distance_as_confidence():
    for file in [INDEX, *_js_files()]:
        text = file.read_text(encoding="utf-8").lower()
        assert "confidence" not in text, file.name


def test_consent_is_enforced_by_client_and_sent_to_the_api():
    app_js = (JS_DIR / "app.js").read_text(encoding="utf-8")
    api_js = (JS_DIR / "api.js").read_text(encoding="utf-8")
    assert "if (!consent)" in app_js, "client-side consent guard missing"
    assert re.search(r"consent:\s*consent \? 'true' : 'false'", api_js), "consent flag not sent as query param"


def test_dialog_default_submit_buttons_are_the_primary_actions():
    """Implicit submission (Enter in a text field) must never trigger Cancel."""
    html = INDEX.read_text(encoding="utf-8")
    for form_id, expected in (("enrollForm", "learn"), ("eraseForm", "erase")):
        form = re.search(rf"<form[^>]*id=\"{form_id}\"[^>]*>(.*?)</form>", html, re.S)
        assert form, form_id
        submits = re.findall(r"<button[^>]*type=\"submit\"[^>]*>", form.group(1))
        assert submits, form_id
        assert f'value="{expected}"' in submits[0], f"{form_id}: first submit button is {submits[0]}"
        for cancel in re.findall(r"<button[^>]*>Cancel</button>", form.group(1)):
            assert 'type="button"' in cancel, cancel


def test_closed_dialogs_are_not_laid_out():
    """No author rule may set `display` on a dialog outside an [open] selector (UA hides closed dialogs)."""
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector, body = match.group(1).strip(), match.group(2)
        if not re.search(r"(^|[\s,])(dialog|\.drawer|\.modal-card)(?![\w-])", selector):
            continue
        if "display" in body:
            assert "[open]" in selector, f"{selector!r} sets display without [open]"
