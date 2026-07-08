# Known-Tools YAML Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the hardcoded `KNOWN_TOOLS` list (wizard page 1 chip options) into an editable YAML file that is re-read on every request, so a non-developer can add a pre-approved tool without touching Python or restarting the server.

**Architecture:** A new `policybot/preapproved/known_tools.yaml` data file holds a flat list of tool names. A new loader function `load_known_tools()` in `policybot/preapproved/known_tools.py` reads and parses it (mirrors the existing `policybot/grille/rules.py` pattern: default path derived from `__file__`, `yaml.safe_load`, optional `path` override for tests). `policybot/web/routes.py`'s `wizard_home` calls this loader on every GET `/` instead of referencing a module-level constant, so edits to the YAML take effect on next page load with no restart.

**Tech Stack:** Python, PyYAML (already a dependency — used by `grille/rules.py`), pytest.

## Global Constraints

- Follow the loader pattern already established in `policybot/grille/rules.py` (default path next to the module, `yaml.safe_load`, `path: str | None = None` override).
- No Pydantic model for this loader — it's a flat list of strings, unlike `grille.yaml`'s nested `Rule` structure.
- Missing/malformed YAML file: let the exception propagate (no try/except) — same as `load_rules`. The file ships with the repo; its absence is a deployment error.
- `policybot/classify/tool_registry.py` (`REGISTRY`, `lookup_tool`) is out of scope — do not touch it.
- The wizard page 1 template (`policybot/web/templates/wizard_outil.html.j2`) already iterates over a `known_tools` context variable — do not modify it.

---

### Task 1: YAML data file + loader

**Files:**
- Create: `policybot/preapproved/known_tools.yaml`
- Create: `policybot/preapproved/known_tools.py`
- Test: `tests/preapproved/test_known_tools.py`

**Interfaces:**
- Produces: `load_known_tools(path: str | None = None) -> list[str]` — importable from `policybot.preapproved.known_tools`. Called with no arguments, reads the bundled default file; called with a `path`, reads that file instead.

- [ ] **Step 1: Write the failing tests**

Create `tests/preapproved/test_known_tools.py`:

```python
from policybot.preapproved.known_tools import load_known_tools


def test_load_known_tools_returns_default_list():
    tools = load_known_tools()
    assert "ChatGPT" in tools
    assert "Claude.ai" in tools
    assert len(tools) >= 5


def test_load_known_tools_reads_custom_path(tmp_path):
    custom = tmp_path / "custom.yaml"
    custom.write_text("- Outil A\n- Outil B\n", encoding="utf-8")
    assert load_known_tools(str(custom)) == ["Outil A", "Outil B"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/preapproved/test_known_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'policybot.preapproved.known_tools'`

- [ ] **Step 3: Create the YAML data file**

Create `policybot/preapproved/known_tools.yaml`:

```yaml
# Outils pré-approuvés proposés comme choix rapides sur la première page.
# Ajouter un nom ici suffit : pas besoin de redémarrer PolicyBot.
- ChatGPT
- ChatGPT Pro
- Claude.ai
- Perplexity
- Microsoft Copilot Entreprise
```

- [ ] **Step 4: Write the loader**

Create `policybot/preapproved/known_tools.py`:

```python
from __future__ import annotations
import os
import yaml

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "known_tools.yaml")


def load_known_tools(path: str | None = None) -> list[str]:
    with open(path or _DEFAULT_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    return list(raw)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/preapproved/test_known_tools.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add policybot/preapproved/known_tools.yaml policybot/preapproved/known_tools.py tests/preapproved/test_known_tools.py
git commit -m "feat(preapproved): load known tools list from YAML"
```

---

### Task 2: Wire the loader into the wizard route

**Files:**
- Modify: `policybot/web/routes.py:23` (remove `KNOWN_TOOLS` constant), `policybot/web/routes.py:38-42` (`wizard_home`)
- Test: `tests/web/test_routes_outil.py` (existing tests must still pass unmodified)

**Interfaces:**
- Consumes: `load_known_tools() -> list[str]` from Task 1 (`policybot.preapproved.known_tools`).

- [ ] **Step 1: Confirm existing tests currently pass (baseline)**

Run: `pytest tests/web/test_routes_outil.py -v`
Expected: PASS (all 4 tests) — this is the pre-change baseline; these tests must still pass after the edit below since `ChatGPT` remains in the YAML list from Task 1.

- [ ] **Step 2: Replace the hardcoded constant with the loader call**

In `policybot/web/routes.py`, remove line 23:

```python
KNOWN_TOOLS = ["ChatGPT", "ChatGPT Pro", "Claude.ai", "Perplexity", "Microsoft Copilot Entreprise"]
```

Add the import near the top (with the other `policybot.*` imports, after the `policybot.models` import):

```python
from policybot.preapproved.known_tools import load_known_tools
```

Change `wizard_home` (previously lines 38-42) from:

```python
@router.get("/", response_class=HTMLResponse)
def wizard_home(request: Request):
    return templates.TemplateResponse(request, "wizard_outil.html.j2", {
        "active_step": "outil", "known_tools": KNOWN_TOOLS,
    })
```

to:

```python
@router.get("/", response_class=HTMLResponse)
def wizard_home(request: Request):
    return templates.TemplateResponse(request, "wizard_outil.html.j2", {
        "active_step": "outil", "known_tools": load_known_tools(),
    })
```

- [ ] **Step 3: Run the route tests to verify they still pass**

Run: `pytest tests/web/test_routes_outil.py -v`
Expected: PASS (all 4 tests, same as baseline)

- [ ] **Step 4: Run the full test suite to catch any other reference to `KNOWN_TOOLS`**

Run: `pytest -q`
Expected: PASS, no failures. (Confirms no other module imports the removed `KNOWN_TOOLS` constant from `policybot.web.routes`.)

- [ ] **Step 5: Commit**

```bash
git add policybot/web/routes.py
git commit -m "refactor(web): read known tools from YAML instead of hardcoded constant"
```
