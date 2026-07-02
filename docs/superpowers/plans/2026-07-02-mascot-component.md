# PolicyBot Mascot Component Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the two-mood robot mascot (neutral/thinking, friendly) approved in the
brainstorm as a reusable, framework-ready component: a Python mood-data module, a
Jinja partial, and static CSS/JS — ready to drop into the FastAPI UI once `api/`
exists, with no rework needed then.

**Architecture:** One source of truth for the two mood states lives in
`policybot/api/mascot.py` (mouth path + spark opacity per mood). A Jinja partial
(`templates/partials/mascot.html`) renders the inline SVG using that data for the
initial server-rendered state. A small vanilla JS file duplicates the same two
mood values (no JS build step exists in this project) so the client can swap
mood after page load without a round-trip; a Python test asserts the two stay in
sync. No FastAPI routes are added — this plan builds the component and a
standalone preview script, not the surrounding `api/` app (out of scope per
§13/§14 of the design spec, which lists `api/` as still to come).

**Tech Stack:** Python 3.11, Jinja2 (already a dependency), vanilla JS/CSS (no
bundler), pytest.

## Global Constraints

- Match existing code style: `from __future__ import annotations`, module-level
  constants, pure functions, one-sentence docstrings with a WHY line where
  non-obvious (see `policybot/grille/matrix.py`).
- No new dependencies — Jinja2 is already in `pyproject.toml`.
- The mascot never appears on the verdict screen or the PDF report (design
  decision from brainstorming) — out of scope for this plan since neither
  exists yet; leave a one-line comment noting the constraint so it isn't lost.
- Mouth path and spark-opacity values must be identical, character-for-character,
  between `policybot/api/mascot.py` and `policybot/api/static/mascot/mascot.js` —
  enforced by a test, not just a comment.
- `build/` is already gitignored — the preview script writes there.

---

### Task 1: Mood data module

**Files:**
- Create: `policybot/api/__init__.py`
- Create: `policybot/api/mascot.py`
- Test: `tests/api/__init__.py`
- Test: `tests/api/test_mascot.py`

**Interfaces:**
- Produces: `MASCOT_MOODS: dict[str, dict[str, object]]` with keys `"neutral"`
  and `"friendly"`, each a dict with `"mouth_d": str` and `"spark_opacity": int`
  (0 or 1). Produces: `mascot_context(mood: str = "neutral") -> dict[str, object]`
  returning `{"mood": mood, "mouth_d": ..., "spark_opacity": ...}`, raising
  `ValueError` for an unknown mood. Later tasks (2, 3) import both.

- [ ] **Step 1: Write the failing test**

Create `tests/api/__init__.py` (empty file, matches the existing
`tests/grille/__init__.py` pattern).

Create `tests/api/test_mascot.py`:

```python
import pytest
from policybot.api.mascot import MASCOT_MOODS, mascot_context


def test_mascot_moods_has_neutral_and_friendly():
    assert set(MASCOT_MOODS) == {"neutral", "friendly"}


def test_mascot_context_returns_mood_values():
    ctx = mascot_context("friendly")
    assert ctx["mood"] == "friendly"
    assert ctx["mouth_d"] == MASCOT_MOODS["friendly"]["mouth_d"]
    assert ctx["spark_opacity"] == MASCOT_MOODS["friendly"]["spark_opacity"]


def test_mascot_context_defaults_to_neutral():
    assert mascot_context()["mood"] == "neutral"


def test_mascot_context_rejects_unknown_mood():
    with pytest.raises(ValueError):
        mascot_context("grumpy")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_mascot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'policybot.api'`

- [ ] **Step 3: Write the implementation**

Create `policybot/api/__init__.py` (empty).

Create `policybot/api/mascot.py`:

```python
from __future__ import annotations

# Keep the two mood values identical to policybot/api/static/mascot/mascot.js —
# tests/api/test_mascot.py::test_mascot_js_stays_in_sync_with_python_moods enforces it.
MASCOT_MOODS: dict[str, dict[str, object]] = {
    "neutral": {"mouth_d": "M46,88 Q60,85 74,88", "spark_opacity": 0},
    "friendly": {"mouth_d": "M44,84 Q60,99 76,84", "spark_opacity": 1},
}


def mascot_context(mood: str = "neutral") -> dict[str, object]:
    """Render context for the mascot partial: the mood name plus its mouth/spark values."""
    if mood not in MASCOT_MOODS:
        raise ValueError(f"Unknown mascot mood: {mood!r}. Expected one of {sorted(MASCOT_MOODS)}.")
    return {"mood": mood, **MASCOT_MOODS[mood]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_mascot.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add policybot/api/__init__.py policybot/api/mascot.py tests/api/__init__.py tests/api/test_mascot.py
git commit -m "feat: add mascot mood data module"
```

---

### Task 2: Jinja partial for the mascot SVG

**Files:**
- Create: `policybot/api/templates/partials/mascot.html`
- Modify: `tests/api/test_mascot.py` (append template-rendering tests)

**Interfaces:**
- Consumes: `mascot_context(mood)` from Task 1 — the template expects `mood`,
  `mouth_d`, `spark_opacity` in its render context.
- Produces: a template loadable as `"partials/mascot.html"` from a Jinja
  `Environment` rooted at `policybot/api/templates`. Root element is an `<svg>`
  with `class="pb-mascot"` and `data-mood="{{ mood }}"`; the mouth path carries
  `class="pb-mouth"` and `d="{{ mouth_d }}"`; the two spark paths carry
  `class="pb-spark-l"` / `class="pb-spark-r"` and `opacity="{{ spark_opacity }}"`.
  Task 3's JS relies on these three class names and the `data-mood` attribute.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_mascot.py`:

```python
import xml.etree.ElementTree as ET
from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = "policybot/api/templates"


def _render_mascot(mood: str) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("partials/mascot.html")
    return template.render(**mascot_context(mood))


@pytest.mark.parametrize("mood", ["neutral", "friendly"])
def test_mascot_partial_renders_valid_svg_with_mood(mood):
    svg = ET.fromstring(_render_mascot(mood))
    assert svg.tag == "svg"
    assert svg.attrib["data-mood"] == mood


@pytest.mark.parametrize("mood", ["neutral", "friendly"])
def test_mascot_partial_mouth_path_matches_mood(mood):
    svg = ET.fromstring(_render_mascot(mood))
    mouth = svg.find(".//*[@class='pb-mouth']")
    assert mouth.attrib["d"] == MASCOT_MOODS[mood]["mouth_d"]


@pytest.mark.parametrize("mood", ["neutral", "friendly"])
def test_mascot_partial_spark_opacity_matches_mood(mood):
    svg = ET.fromstring(_render_mascot(mood))
    spark = svg.find(".//*[@class='pb-spark-l']")
    assert spark.attrib["opacity"] == str(MASCOT_MOODS[mood]["spark_opacity"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/api/test_mascot.py -v`
Expected: FAIL with `jinja2.exceptions.TemplateNotFound: partials/mascot.html`

- [ ] **Step 3: Write the implementation**

Create `policybot/api/templates/partials/mascot.html`:

```html
<svg viewBox="0 0 120 120" class="pb-mascot" data-mood="{{ mood }}" role="img" aria-label="PolicyBot mascot">
  <line x1="60" y1="30" x2="60" y2="14" stroke="#9fb0c4" stroke-width="4" stroke-linecap="round"/>
  <circle cx="60" cy="10" r="6" fill="#4fc3e0"/>
  <path class="pb-spark-l" d="M22,38 L30,38 M26,34 L26,42" stroke="#4fc3e0" stroke-width="2.4" stroke-linecap="round" opacity="{{ spark_opacity }}"/>
  <path class="pb-spark-r" d="M90,38 L98,38 M94,34 L94,42" stroke="#4fc3e0" stroke-width="2.4" stroke-linecap="round" opacity="{{ spark_opacity }}"/>
  <rect x="18" y="30" width="84" height="74" rx="30" fill="#c9d4e0"/>
  <rect x="24" y="78" width="72" height="20" rx="10" fill="#9fb0c4" opacity="0.5"/>
  <circle cx="16" cy="62" r="7" fill="#9fb0c4"/>
  <circle cx="104" cy="62" r="7" fill="#9fb0c4"/>
  <rect x="36" y="54" width="17" height="22" rx="8.5" fill="#1e2a38"/>
  <rect x="67" y="54" width="17" height="22" rx="8.5" fill="#1e2a38"/>
  <circle cx="41" cy="60" r="2.6" fill="#ffffff" opacity="0.9"/>
  <circle cx="72" cy="60" r="2.6" fill="#ffffff" opacity="0.9"/>
  <path class="pb-mouth" d="{{ mouth_d }}" stroke="#1e2a38" stroke-width="4" stroke-linecap="round" fill="none"/>
</svg>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_mascot.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add policybot/api/templates/partials/mascot.html tests/api/test_mascot.py
git commit -m "feat: add mascot Jinja partial"
```

---

### Task 3: Static CSS/JS for client-side mood swaps

**Files:**
- Create: `policybot/api/static/mascot/mascot.css`
- Create: `policybot/api/static/mascot/mascot.js`
- Modify: `tests/api/test_mascot.py` (append sync test)

**Interfaces:**
- Consumes: the three class names and `data-mood` attribute produced by Task 2's
  template.
- Produces: a global function `setMascotMood(root: SVGElement, mood: "neutral" |
  "friendly")` that updates `.pb-mouth`'s `d`, `.pb-spark-l`/`.pb-spark-r`'s
  `opacity`, and `root.dataset.mood`. Future UI code (once `api/` exists) calls
  this after AJAX form-step transitions, e.g.
  `setMascotMood(document.querySelector(".pb-mascot"), "friendly")`.

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_mascot.py`:

```python
from pathlib import Path

JS_PATH = Path("policybot/api/static/mascot/mascot.js")


def test_mascot_js_stays_in_sync_with_python_moods():
    js_source = JS_PATH.read_text(encoding="utf-8")
    for values in MASCOT_MOODS.values():
        assert f'"{values["mouth_d"]}"' in js_source
        assert f'spark_opacity: {values["spark_opacity"]}' in js_source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_mascot.py::test_mascot_js_stays_in_sync_with_python_moods -v`
Expected: FAIL with `FileNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `policybot/api/static/mascot/mascot.css`:

```css
.pb-mascot .pb-mouth,
.pb-mascot .pb-spark-l,
.pb-mascot .pb-spark-r {
  transition: d 0.15s ease, opacity 0.15s ease;
}

@media (prefers-reduced-motion: reduce) {
  .pb-mascot .pb-mouth,
  .pb-mascot .pb-spark-l,
  .pb-mascot .pb-spark-r {
    transition: none;
  }
}
```

Create `policybot/api/static/mascot/mascot.js`:

```js
// Keep in sync with policybot/api/mascot.py MASCOT_MOODS —
// tests/api/test_mascot.py::test_mascot_js_stays_in_sync_with_python_moods enforces it.
const MASCOT_MOODS = {
  neutral: { mouth_d: "M46,88 Q60,85 74,88", spark_opacity: 0 },
  friendly: { mouth_d: "M44,84 Q60,99 76,84", spark_opacity: 1 },
};

function setMascotMood(root, mood) {
  const m = MASCOT_MOODS[mood];
  if (!m) {
    throw new Error(`Unknown mascot mood: ${mood}`);
  }
  root.querySelector(".pb-mouth").setAttribute("d", m.mouth_d);
  root.querySelector(".pb-spark-l").setAttribute("opacity", m.spark_opacity);
  root.querySelector(".pb-spark-r").setAttribute("opacity", m.spark_opacity);
  root.dataset.mood = mood;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_mascot.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add policybot/api/static/mascot/mascot.css policybot/api/static/mascot/mascot.js tests/api/test_mascot.py
git commit -m "feat: add mascot static CSS/JS for client-side mood swaps"
```

---

### Task 4: Standalone preview script + visual verification

**Files:**
- Create: `scripts/render_mascot_preview.py`

**Interfaces:**
- Consumes: `mascot_context` from Task 1, the `partials/mascot.html` template
  from Task 2, and the static files from Task 3.
- Produces: `build/mascot-preview.html` (plus copies of `mascot.css`/`mascot.js`
  next to it) — a plain HTML file, openable directly in a browser, with no
  FastAPI server required. This is the manual QA harness until the real `api/`
  app exists to serve `partials/mascot.html` through a live route.

- [ ] **Step 1: Write the script**

Create `scripts/render_mascot_preview.py`:

```python
"""Render both mascot moods to a static HTML file for manual visual QA.

No FastAPI app exists yet to serve policybot/api/templates + static/, so this
renders the same Jinja partial standalone. Run:
    python scripts/render_mascot_preview.py
then open build/mascot-preview.html in a browser.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from policybot.api.mascot import mascot_context

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "policybot" / "api" / "templates"
STATIC_DIR = ROOT / "policybot" / "api" / "static" / "mascot"
OUT_DIR = ROOT / "build"

PREVIEW_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Mascot preview</title>
<link rel="stylesheet" href="mascot.css">
<style>
  body {{ font-family: sans-serif; display: flex; gap: 32px; padding: 40px; }}
  svg {{ width: 120px; height: 120px; }}
  button {{ display: block; margin-top: 12px; }}
</style>
</head>
<body>
  <div>
    <p>neutral (server-rendered)</p>
    {neutral_svg}
  </div>
  <div>
    <p>friendly (server-rendered)</p>
    {friendly_svg}
  </div>
  <div>
    <p>client-side toggle</p>
    {neutral_svg_live}
    <button onclick="setMascotMood(document.getElementById('live-mascot'), 'neutral')">neutral</button>
    <button onclick="setMascotMood(document.getElementById('live-mascot'), 'friendly')">friendly</button>
  </div>
  <script src="mascot.js"></script>
</body>
</html>
"""


def main() -> None:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("partials/mascot.html")

    neutral_svg = template.render(**mascot_context("neutral"))
    friendly_svg = template.render(**mascot_context("friendly"))
    live_svg = template.render(**mascot_context("neutral")).replace(
        'class="pb-mascot"', 'class="pb-mascot" id="live-mascot"', 1
    )

    OUT_DIR.mkdir(exist_ok=True)
    shutil.copy(STATIC_DIR / "mascot.css", OUT_DIR / "mascot.css")
    shutil.copy(STATIC_DIR / "mascot.js", OUT_DIR / "mascot.js")
    (OUT_DIR / "mascot-preview.html").write_text(
        PREVIEW_HTML.format(
            neutral_svg=neutral_svg,
            friendly_svg=friendly_svg,
            neutral_svg_live=live_svg,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {OUT_DIR / 'mascot-preview.html'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script**

Run: `python scripts/render_mascot_preview.py`
Expected: `Wrote <repo-root>/build/mascot-preview.html`, and `build/mascot.css`,
`build/mascot.js` exist alongside it.

- [ ] **Step 3: Visually verify in a browser**

Open `build/mascot-preview.html` directly (double-click, or `start
build/mascot-preview.html` on Windows). Confirm:
- The neutral and friendly server-rendered robots look correct and match each
  other's head/antenna/eyes exactly, differing only in mouth curve and spark
  visibility.
- The "client-side toggle" buttons switch the third robot between the two
  moods live, with a short transition.

- [ ] **Step 4: Commit**

```bash
git add scripts/render_mascot_preview.py
git commit -m "feat: add mascot preview script for manual visual QA"
```

---

## Not in scope

- The FastAPI `api/` app, routes, and `QuestionSpec` rendering — none of that
  exists yet in this codebase; wiring the mascot into real interview screens is
  a follow-up plan once that layer is built.
- Mascot appearance on the verdict screen or PDF report — explicitly excluded
  by the brainstorm decision.
- A third mood/expression — only neutral and friendly were requested.
