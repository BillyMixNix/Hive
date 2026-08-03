# Hive Project Harness

The harness exists so the Pilot is not used as Hive's browser, eyes, and QA loop.

## Web Harness v0.1

`web_harness.py` launches a static/local HTML candidate in headless Chromium using Playwright, executes a manifest-defined smoke path, captures screenshots, records browser console output and page errors, evaluates assertions, and writes an `ObservationBundle` to disk.

The harness verdict is intentionally mechanical:

- `REJECT` if a page error occurs or an assertion fails.
- `PASS` when the smoke path completes without those failures.

A PASS is **not** automatically permission to ship to the Pilot. Screenshots and the interaction trace are evidence for the cognitive Hive to inspect for visual/intent drift before deciding whether to revise, continue, or request Pilot judgment.

## Manifest

```json
{
  "candidate": "endless-fusion-v0.71",
  "entrypoint": "/absolute/or/relative/path/to/game.html",
  "viewport": {"width": 412, "height": 915},
  "steps": [
    {"action": "assert_no_page_errors"},
    {"action": "screenshot", "name": "boot"},
    {"action": "click_text", "text": "Iron Longsword"},
    {"action": "click_text", "text": "Phoenix Heart"},
    {"action": "assert_text", "text": "FUSE", "exact": false},
    {"action": "screenshot", "name": "fusion-ready"}
  ]
}
```

Supported v0.1 actions: `click_text`, `click_selector`, `wait`, `screenshot`, `assert_text`, `assert_no_page_errors`, and `assert_js`.

## Run

```bash
pip install playwright
playwright install chromium
python -m hive.project_harness.web_harness project.hive-web.json --out .hive/observations/candidate-id
```

## Observation contract

Each run emits:

- `screenshots/*.png`
- `observation.json`
  - candidate identity
  - viewport
  - console messages
  - page errors
  - assertions
  - interaction trace
  - mechanical verdict

The next layer should add a runner abstraction for hosted dev servers and richer interaction primitives (drag, long press, keyboard, network capture, DOM snapshot). Do not expand those until a real project requires them.
