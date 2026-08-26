# Design

## Principles

**Receipts are the product.** Every design decision below serves one job: making
it cheap to check a claim. Anything that made the interface prettier but the
sources harder to reach got cut.

**Doubt is visible, not hidden.** Most AI chat UIs render every sentence with
identical confidence. This one doesn't — unsupported claims are underlined in
the answer itself. That looks worse and is more honest, and honest is the point.

**Nothing fails silently.** Empty index, dead provider, blocked artifact content
— each has a specific state that says what happened and what to do.

**One bold move.** The timecode-and-receipts system is the memorable element.
Everything around it is deliberately quiet.

## Grounding it in the subject

The material is *spoken conversation on a timeline*. That drove the concrete
choices:

- **Timecodes are set in mono** (`JetBrains Mono`) because they're data, not
  prose. They read as coordinates, which is what they are.
- **Citations are chips, not footnotes.** A footnote sends you to the bottom of
  a document. A chip carries the guest's name and the timecode on its face, so
  the most common question — *who said this and when* — is answered without a
  click.
- **The receipts drawer opens beside the answer, not over it.** Checking a claim
  shouldn't cost you your place in the conversation.

## Palette

AI-generated interfaces cluster hard around cream-and-terracotta, near-black
with an acid accent, and hairline-rule broadsheet. All three were available and
all three were avoided.

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#f5f6f4` | Background. Cool paper, not cream. |
| `--ink` | `#161c1a` | Text. Green-shifted black, not neutral. |
| `--pine` | `#2f6f62` | Primary. Studio green — calm, not a "tech" blue. |
| `--supported` | `#2f6f62` | Verified claims. Same as primary, deliberately. |
| `--partial` | `#b4761f` | Partly supported. |
| `--unsupported` | `#b3402f` | Unverifiable. |

The semantic three are load-bearing, so the palette is built around them rather
than adding them as an afterthought. Supported reuses the primary green because
"grounded" should read as the product's normal state, not as a special success
event.

## Type

| Role | Face | Why |
|---|---|---|
| Display | Bricolage Grotesque | Variable-width grotesque with real character; used only for the wordmark, headings and the empty state. |
| Body | Inter | Long-form reading at 15px/1.62. Neutral on purpose — the display face carries personality so the answers don't have to. |
| Data | JetBrains Mono | Timecodes, model names, scores, CSP strings. Anything a machine produced. |

The mono/prose split is the type system's one rule: **if a machine generated it
as data, it's mono.** That's why `00:14:32`, `qwen2.5:3b-instruct` and `14/15`
all share a face, and why they read as a category.

## Information architecture

```
┌────────────┬──────────────────────────────┬──────────────────┐
│ sessions   │ thread                       │ receipts │ artifact│
│            │  ├ answer                    │          │         │
│ ─────────  │  ├ grounding badge           │  passage │ sandboxed│
│ provider   │  ├ underlined doubt          │  + deep  │ iframe  │
│ + health   │  └ citation chips ──────────▶│  link    │         │
├────────────┼──────────────────────────────┴──────────────────┤
│            │ composer                                         │
└────────────┴──────────────────────────────────────────────────┘
```

Three columns, collapsing to two then one. The right panel is shared between
receipts and artifacts because they're the same gesture — *show me the thing
behind the answer* — and two competing panels would fight for the same space.

Provider status lives at the bottom of the rail, next to where you'd change it.
Status and control belong together; putting health in a header and the switcher
in settings is how people end up debugging the wrong thing.

## Key states

| State | Treatment |
|---|---|
| **Empty thread** | A thesis line and four starters, each labelled with what it demonstrates ("runs the essay skill and shows its rubric score"). The empty screen is the tutorial. |
| **Working** | Named stages — "Searching transcripts…", "Writing and checking the answer against sources…". On a local 3B a turn takes real seconds; a spinner would feel broken where a named stage feels deliberate. |
| **Grounded answer** | Green badge, `14/15` in mono. |
| **Partly grounded** | Amber badge; shaded sentences; a legend explaining what the shading means and where to check. |
| **Unverifiable claim** | Red wavy underline, hover explains the score. Not removed — the user decides. |
| **Empty index** | Banner with the exact command to run. |
| **Provider down** | Banner with the backend's own detail string ("model not pulled. Run: ollama pull …"), not a generic error. |
| **Fell back** | Badge on the message itself, so it's attached to the answer it affected rather than floating in a toast. |
| **Artifact with blocked content** | Count in the toolbar, rules listed in a strip, full detail in "What's blocked?" — three levels of depth for three levels of curiosity. |
| **Echo provider selected** | Amber warning that it's a stub, not a model. |

## Interaction detail

- Enter sends, Shift+Enter newlines; textarea grows to a cap.
- Citation chip → panel opens → smooth-scrolls to that receipt.
- Scorecard is a `<details>` — collapsed by default, because the score matters
  more than its breakdown until you disagree with it.
- Thread auto-scrolls on new messages only.
- Starters send immediately. A starter that fills the input and waits is a
  second click for nothing.

## Responsive

| Width | Behaviour |
|---|---|
| ≥1080px | Three columns |
| 720–1080px | Panel becomes an overlay drawer |
| <720px | Rail becomes a toggled drawer; single column; bubbles widen to 92% |

Designed for laptop first — that's where the work happens — but the artifact
viewer is genuinely usable on a phone, which matters because that's where
someone re-reads a one-pager before a meeting.

## Accessibility

- Semantic buttons throughout; no click handlers on `div`s.
- Visible focus ring on every interactive element (`--pine`, 2px, offset).
- `prefers-reduced-motion` collapses all transitions.
- Colour is never the only signal: the grounding badge carries `14/15` and a
  word; underlines pair colour with a distinct line style (solid vs wavy);
  provider dots sit next to text labels.
- Body text meets WCAG AA on `--paper`; the three semantic colours were darkened
  from their first draft to clear 4.5:1.
- `sr-only` labels on the provider select and composer; `aria-label` on icon
  buttons; `aria-expanded` on the policy toggle.

### Known gaps

Honest list, not a claim of completeness:

- The grounding underlines aren't announced to screen readers as a distinct
  region — a reader hears the sentence but not that it's flagged. Needs an
  `aria-describedby` per flagged sentence.
- Focus isn't trapped in the mobile drawers.
- No skip-to-content link.
- Not tested with an actual screen reader, only against the spec.

## Copy

Written from the user's side. "Ask the archive, get receipts", not "AI-powered
knowledge retrieval". Errors say what happened and the command that fixes it.
The stub-provider warning says answers "will look odd" rather than hedging.

One deliberate choice: the badge says **"grounded"**, not "verified" or
"accurate". The gate checks whether a claim matches a retrieved passage — it
does not check whether the passage is true. Overstating that in a one-word label
would undermine the entire point of building it.
