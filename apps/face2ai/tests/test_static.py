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


# ---------- expression (Stage 1): opt-in, hedged, never a certainty ----------


def test_expression_toggle_and_tile_are_present_and_off_by_default():
    html = INDEX.read_text(encoding="utf-8")
    button = re.search(r"<button[^>]*id=\"expressionButton\"[^>]*>", html)
    assert button, "expression toggle button missing"
    assert "disabled" in button.group(0), "toggle must start disabled until /api/status says the engine is available"
    assert re.search(r"id=\"expressionTile\"", html), "expression metric tile missing"
    assert re.search(r"id=\"expressionValue\"[^>]*>off<", html), "tile must start as 'off' (opt-in default off)"
    for bar in ("valenceFill", "arousalFill"):
        assert re.search(rf"class=\"mood-bar-fill\" id=\"{bar}\"", html), bar
    assert "Expression: off" in html
    assert "a hint, not a fact" in html, "the tile must say what it is: a hint, never a fact"


def test_expression_wording_is_hedged_and_never_a_certainty(client):
    """The served bundle speaks of how a face *appears* ("looks …" — the shell is English); nothing reads as a finding.

    model.js keeps both wording tables (de "wirkt …" / en "looks …") so the view-model stays bilingual;
    app.js selects English. Forbidden anywhere in the shell: "is happy", "ist fröhlich", "erkannt", and
    "detected" applied to a mood/expression (faces may be detected; moods only ever *look* like something).
    """
    model_js = client.get("/assets/js/model.js").text
    assert "wirkt " in model_js
    assert "looks " in model_js
    assert "ist fröhlich" not in model_js
    app_js = client.get("/assets/js/app.js").text
    assert "EXPRESSION_LANG = 'en'" in app_js, "the browser shell is English; the tile must say 'looks …'"
    assert "looks " in app_js
    assert "expressionButton" in app_js
    assert "Expression: off" in app_js and "Expression: on" in app_js
    assert "Not available · " in app_js
    for path in [INDEX, STATIC / "css" / "app.css", *_js_files()]:
        text = path.read_text(encoding="utf-8").lower()
        assert "erkannt" not in text, f"{path.name}: expression must never be presented as 'erkannt'"
        assert not re.search(r"\bist (fröhlich|traurig|verärgert|ängstlich|überrascht|angewidert|abschätzig|neutral)\b", text), path.name
        assert not re.search(r"\b(is|are|was|were) (happy|sad|angry|fearful|surprised|disgusted|contemptuous)\b", text), (
            f"{path.name}: expression must be hedged ('looks happy'), never asserted ('is happy')"
        )
        assert not re.search(r"\b(mood|expression|emotion)s? (is |was |)detected\b|\bdetected (mood|expression|emotion)", text), (
            f"{path.name}: a mood is never 'detected' — it only ever 'looks' like something"
        )


def test_expression_toggle_is_the_only_thing_the_browser_sends_for_the_feature():
    api_js = (JS_DIR / "api.js").read_text(encoding="utf-8")
    assert re.search(r"'/api/expression'", api_js)
    assert re.search(r"JSON\.stringify\(\{ enabled: enabled === true \}\)", api_js), "toggle body must be exactly {enabled: bool}"
    app_js = (JS_DIR / "app.js").read_text(encoding="utf-8")
    assert "api.setExpression(" in app_js
    assert "expression_available" in app_js and "expression_reason" in app_js and "expression_enabled" in app_js


def test_shell_and_assets_must_be_revalidated_by_the_browser(client):
    """A redeploy must never pair a fresh app.js with a heuristically cached model.js (real case, 2026-08-18)."""
    assert client.get("/").headers["cache-control"] == "no-cache"
    for path in ("/assets/js/app.js", "/assets/js/model.js", "/assets/css/app.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache", path
        assert "etag" in response.headers, path
