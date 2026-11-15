"""Hive Web Project Harness v0.1.

Runs a local/static web candidate in Chromium via Playwright and emits an
ObservationBundle: screenshots, console messages, page errors, assertions,
and interaction trace. This is infrastructure for Hive's internal candidate
loop; it is deliberately independent of any one game.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

try:
    from playwright.async_api import async_playwright
except ImportError as exc:  # pragma: no cover
    raise SystemExit("playwright is required: pip install playwright && playwright install chromium") from exc


@dataclass
class AssertionResult:
    name: str
    passed: bool
    evidence: str = ""


class WebHarness:
    def __init__(self, manifest: dict[str, Any], out_dir: Path):
        self.manifest = manifest
        self.out_dir = out_dir
        self.shots = out_dir / "screenshots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.console: list[dict[str, str]] = []
        self.errors: list[str] = []
        self.trace: list[dict[str, Any]] = []
        self.assertions: list[AssertionResult] = []

    async def run(self) -> dict[str, Any]:
        entry = Path(self.manifest["entrypoint"]).resolve()
        viewport = self.manifest.get("viewport", {"width": 412, "height": 915})
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(viewport=viewport)
            page.on("console", lambda msg: self.console.append({"type": msg.type, "text": msg.text}))
            page.on("pageerror", lambda err: self.errors.append(str(err)))
            await page.goto(entry.as_uri(), wait_until="load")
            await self._screenshot(page, "boot")
            for step in self.manifest.get("steps", []):
                await self._step(page, step)
            await browser.close()
        bundle = {
            "candidate": self.manifest.get("candidate"),
            "entrypoint": str(entry),
            "viewport": viewport,
            "console": self.console,
            "page_errors": self.errors,
            "assertions": [asdict(x) for x in self.assertions],
            "interaction_trace": self.trace,
            "verdict": self._verdict(),
        }
        (self.out_dir / "observation.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        return bundle

    def _verdict(self) -> str:
        if self.errors or any(not x.passed for x in self.assertions):
            return "REJECT"
        return "PASS"

    async def _screenshot(self, page, name: str):
        path = self.shots / f"{name}.png"
        await page.screenshot(path=str(path), full_page=True)
        self.trace.append({"action": "screenshot", "name": name, "path": str(path)})

    async def _step(self, page, step: dict[str, Any]):
        action = step["action"]
        self.trace.append(step)
        if action == "click_text":
            await page.get_by_text(step["text"], exact=step.get("exact", True)).first.click()
        elif action == "click_selector":
            await page.locator(step["selector"]).first.click()
        elif action == "screenshot":
            await self._screenshot(page, step["name"])
        elif action == "wait":
            await page.wait_for_timeout(step.get("ms", 250))
        elif action == "assert_text":
            text = step["text"]
            count = await page.get_by_text(text, exact=step.get("exact", False)).count()
            self.assertions.append(AssertionResult(step.get("name", f"text:{text}"), count > 0, f"matches={count}"))
        elif action == "assert_no_page_errors":
            self.assertions.append(AssertionResult(step.get("name", "no page errors"), not self.errors, "; ".join(self.errors)))
        elif action == "assert_js":
            value = await page.evaluate(step["expression"])
            expected = step.get("expected", True)
            self.assertions.append(AssertionResult(step.get("name", "js assertion"), value == expected, f"actual={value!r} expected={expected!r}"))
        else:
            raise ValueError(f"Unknown harness action: {action}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--out", default=".hive/observations/latest")
    args = ap.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    bundle = asyncio.run(WebHarness(manifest, Path(args.out)).run())
    print(json.dumps(bundle, indent=2))
    return 0 if bundle["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
