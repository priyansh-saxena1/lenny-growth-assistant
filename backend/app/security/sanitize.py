"""Artifact sanitisation.

Threat model: the HTML in an artifact is written by a language model that has
just read attacker-influenceable text (transcripts, and whatever the user
pasted into the chat). Treat it as hostile.

The isolation is two layers, and the layering is the point:

  Layer 1 — the browser. The viewer renders into an <iframe sandbox="allow-scripts">
  with *no* allow-same-origin. That combination puts the frame on an opaque
  origin: no access to the parent DOM, no cookies, no localStorage, no
  same-origin fetch. We also inject a CSP of `default-src 'none'` which kills
  every outbound request the frame could make. So even a script that survives
  layer 2 has nothing to steal and nowhere to send it.

  Layer 2 — this module. Strips the things that are dangerous *and* useless to
  a legitimate artifact: external resource loads, form submissions, frame
  embedding, and top-level navigation. It does NOT strip inline <script>,
  because interactive artifacts are a product requirement and layer 1 already
  contains them. Stripping scripts would give a false sense of safety while
  breaking the feature.

Why keep scripts at all: an artifact that can't run JS can't be a calculator, a
sortable table, or a chart — which is most of what people ask an artifact for.
The sandboxed-opaque-origin model is exactly how Claude's own artifact viewer
handles this, and it's a stronger guarantee than regex-stripping script tags,
which is famously bypassable.

Everything removed is reported back so the UI can say "3 things blocked" and
the user can see what and why, rather than silently getting different output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Nothing loads from the network. `data:` images are allowed because inline SVG
# and base64 sparklines are common in artifacts and can't phone home.
CSP = (
    "default-src 'none'; "
    "img-src data:; "
    "style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; "
    "font-src data:; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-src 'none'"
)

SANDBOX = "allow-scripts"  # deliberately NOT allow-same-origin

POLICY = {
    "permitted": [
        "Inline <script> (contained by the sandboxed opaque origin + CSP)",
        "Inline <style> and style attributes",
        "Static HTML structure and text",
        "data: URI images and fonts",
        "Same-frame DOM manipulation",
    ],
    "blocked": [
        "All network requests (fetch, XHR, WebSocket, EventSource) via CSP default-src 'none'",
        "External <script src>, <link rel=stylesheet>, remote <img src>",
        "<iframe>, <object>, <embed>, <portal>",
        "<form> submission and formaction attributes",
        "<meta http-equiv=refresh> and target=_top navigation",
        "Access to parent DOM, cookies, localStorage (no allow-same-origin)",
        "javascript: and vbscript: URLs",
    ],
    "csp": CSP,
    "sandbox": SANDBOX,
    "rationale": (
        "Scripts are contained rather than removed. Regex script-stripping is "
        "bypassable and would break interactive artifacts; an opaque-origin "
        "sandbox with default-src 'none' gives a stronger guarantee and keeps "
        "the feature working."
    ),
}


@dataclass
class SanitizerReport:
    blocked: list[dict] = field(default_factory=list)
    kind: str = "html"

    def add(self, rule: str, detail: str) -> None:
        self.blocked.append({"rule": rule, "detail": detail[:180]})

    def as_dict(self) -> dict:
        return {"kind": self.kind, "blocked_count": len(self.blocked), "blocked": self.blocked}


# Tags removed wholesale, contents and all.
_KILL_TAGS = ("iframe", "object", "embed", "portal", "frame", "frameset", "base")

_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("external-script",
     re.compile(r"<script\b[^>]*\bsrc\s*=\s*[\"']?[^\"'>\s]+[^>]*>\s*</script\s*>", re.I), ""),
    ("external-stylesheet",
     re.compile(r"<link\b[^>]*\brel\s*=\s*[\"']?stylesheet[^>]*>", re.I), ""),
    ("meta-refresh",
     re.compile(r"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh[^>]*>", re.I), ""),
    ("form-tag",
     re.compile(r"</?form\b[^>]*>", re.I), ""),
    ("formaction-attr",
     re.compile(r"\sformaction\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I), ""),
    ("js-url",
     re.compile(r"\s(?:href|src|action|xlink:href)\s*=\s*(\"|')?\s*(?:javascript|vbscript|data:text/html)\s*:[^\"'>\s]*\1?", re.I), ""),
    ("target-top",
     re.compile(r"\starget\s*=\s*[\"']?_(?:top|parent)[\"']?", re.I), ""),
]

# Remote resource loads on tags we otherwise keep.
_REMOTE_SRC = re.compile(
    r"\s(src|href|poster|srcset)\s*=\s*(\"|')?(https?:)?//[^\"'>\s]+\2?", re.I
)


def sanitize_html(html: str) -> tuple[str, SanitizerReport]:
    rep = SanitizerReport(kind="html")
    out = html

    for tag in _KILL_TAGS:
        pat = re.compile(rf"<{tag}\b.*?</{tag}\s*>|<{tag}\b[^>]*/?>", re.I | re.S)
        for m in pat.finditer(out):
            rep.add(f"{tag}-tag", m.group(0))
        out = pat.sub("", out)

    for rule, pat, repl in _PATTERNS:
        for m in pat.finditer(out):
            rep.add(rule, m.group(0))
        out = pat.sub(repl, out)

    # Remote loads: strip the attribute, keep the element. An <img> with no src
    # renders as alt text, which is a clearer failure than a missing element.
    for m in _REMOTE_SRC.finditer(out):
        rep.add("remote-resource", m.group(0).strip())
    out = _REMOTE_SRC.sub("", out)

    return _wrap_document(out), rep


def _wrap_document(body: str) -> str:
    """Force our CSP in even if the model wrote its own <head>."""
    meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    if re.search(r"<head\b[^>]*>", body, re.I):
        return re.sub(r"(<head\b[^>]*>)", r"\1" + meta, body, count=1, flags=re.I)
    if re.search(r"<html\b[^>]*>", body, re.I):
        return re.sub(r"(<html\b[^>]*>)", r"\1<head>" + meta + "</head>", body,
                      count=1, flags=re.I)
    return (
        "<!doctype html><html><head>" + meta +
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "</head><body>" + body + "</body></html>"
    )


def sanitize_markdown(md: str) -> tuple[str, SanitizerReport]:
    """Markdown is rendered client-side by react-markdown with raw HTML disabled.

    We still strip inline HTML server-side so that a downstream consumer of the
    /api/artifacts payload (the client mentioned wanting to pipe these into
    Notion) doesn't inherit a hole we closed only in our own renderer.
    """
    rep = SanitizerReport(kind="markdown")
    out = md

    for pat, rule in (
        (re.compile(r"<script\b.*?</script\s*>", re.I | re.S), "script-tag"),
        (re.compile(r"<style\b.*?</style\s*>", re.I | re.S), "style-tag"),
        (re.compile(r"<(iframe|object|embed|form)\b.*?</\1\s*>", re.I | re.S), "embedded-tag"),
        (re.compile(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I), "event-handler"),
        (re.compile(r"\]\(\s*javascript:[^)]*\)+", re.I), "js-link"),
    ):
        for m in pat.finditer(out):
            rep.add(rule, m.group(0))
        out = pat.sub("" if rule != "js-link" else "](#blocked)", out)

    return out, rep


def sanitize(kind: str, content: str) -> tuple[str, SanitizerReport]:
    return sanitize_html(content) if kind == "html" else sanitize_markdown(content)
