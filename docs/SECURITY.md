# Artifact security

## Threat model

Artifact HTML is written by a language model that has just consumed
attacker-influenceable text: podcast transcripts, and whatever the user pasted
into the chat. A prompt injection in either can steer the model into emitting
markup of the attacker's choosing. **Treat generated HTML as hostile.**

What an attacker wants:

1. Read the user's session or cookies
2. Reach the parent DOM and act as the user
3. Exfiltrate conversation content to a remote host
4. Navigate the top frame somewhere convincing

## Two layers

### Layer 1 — the browser (the real boundary)

```html
<iframe sandbox="allow-scripts" srcdoc="…"></iframe>
```

`allow-scripts` **without** `allow-same-origin` puts the frame on an *opaque
origin*. Consequences: no access to the parent DOM, no cookies, no
`localStorage`, no same-origin `fetch`. `document.cookie` returns empty.

Plus an injected CSP, forced into `<head>` even if the model wrote its own:

```
default-src 'none'; img-src data:; style-src 'unsafe-inline';
script-src 'unsafe-inline'; font-src data:; form-action 'none';
base-uri 'none'; frame-src 'none'
```

`default-src 'none'` blocks every outbound request — `fetch`, XHR, WebSocket,
EventSource. A script that survives layer 2 has nothing to read and nowhere to
send it.

### Layer 2 — the server sanitiser

`backend/app/security/sanitize.py` removes what is dangerous **and useless to a
legitimate artifact**:

| Removed | Reason |
|---|---|
| `<iframe>`, `<object>`, `<embed>`, `<base>`, `<frame>` | Nesting and base-URL hijacking |
| `<script src>`, `<link rel=stylesheet>` | External code and style |
| Remote `src` / `href` / `poster` / `srcset` | Tracking pixels, remote loads |
| `<form>`, `formaction` | Off-origin submission |
| `javascript:`, `vbscript:`, `data:text/html` URLs | Script execution via URL |
| `target=_top` / `_parent` | Breaking out of the frame |
| `<meta http-equiv=refresh>` | Navigation |

## Why inline scripts are kept

This is the decision most likely to be questioned, so it's stated plainly.

Inline `<script>` is **not** stripped. Two reasons:

1. **Regex script-stripping is bypassable.** It is one of the most reliably
   defeated controls in web security. Shipping it would create the appearance of
   safety while the real boundary went unbuilt.
2. **It would break the feature.** An artifact that can't run JavaScript can't
   be a calculator, a sortable table, or a chart — which is most of what people
   ask an artifact for.

Containment is a stronger guarantee than scrubbing. A script in an opaque-origin
frame under `default-src 'none'` can manipulate its own DOM and nothing else.
That's the same model Claude's own artifact viewer uses.

The consequence is visible in the tests: `test_inline_script_survives_because_the_sandbox_contains_it`
asserts that an exfiltration payload's `fetch(...+document.cookie)` **is still
present** in the sanitised output, alongside the CSP that neuters it. A test
asserting the script had been stripped would be asserting the wrong design.

## Transparency

Nothing is removed silently. The sanitiser returns a report — rule and matched
text — which is persisted with the artifact, surfaced as a "N blocked" chip,
expandable to the specific rules, with full policy detail behind
"What's blocked?".

`GET /api/artifacts/policy` returns the permit/block table and the live CSP
string. It's generated from the same constants the sanitiser enforces, so the
documentation cannot drift from the behaviour — and there's a test asserting
exactly that.

## Verifying it

```bash
make test   # tests/test_security.py — 9 tests against a real exfil payload
```

Or by hand: ask the assistant for an HTML artifact, then paste a payload
containing an external script, a tracking pixel, an iframe, a form post and a
`javascript:` link. The viewer renders it inert and reports what it blocked.

## Markdown artifacts

Rendered by `react-markdown` with raw HTML disabled. The server *also* strips
inline HTML from markdown, so a downstream consumer of the `/api/artifacts`
payload doesn't inherit a hole we closed only in our own renderer.

## Out of scope

Stated rather than implied:

- **No authentication.** Internal tool assumption (see PRD).
- **No rate limiting.** Add at the ingress if this leaves the VPN.
- **No prompt-injection defence in retrieval.** A malicious transcript could
  steer an answer. The grounding gate limits the damage — an injected claim
  still has to match retrieved evidence — but it isn't an injection defence.
- **Secrets** are never logged or returned; `/api/config` exposes presence only.
