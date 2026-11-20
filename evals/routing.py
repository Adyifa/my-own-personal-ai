"""Routing evaluation: does each utterance reach the right skill, or at least never the wrong action?

Run:  python -m evals.routing            (summary per category + every failure)
      python -m evals.routing --category power

Case format (evals/routing_cases.txt), one per line:  utterance => expectation [| alternative ...]
  rule:open_app name=spotify   a rule intent, optionally with argument values (lists comma-joined)
  agent / agent:chat           handed to the LLM (any intent / a specific one)
  not:power,disk_clean         anything except these intents (for "must never do this" cases)
The expectation is what Mika *should* do, so features that are not built yet fail on purpose until they are.
"""

from __future__ import annotations

import argparse
import copy
import shlex
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mika.audio.wake import strip_wake_prefix
from mika.brain.router import Route, Router
from mika.config import DEFAULT_CONFIG, apply_personality_preset
from mika.skills.launcher import Launcher
from mika.text import clean_conversational_command, normalize

CASES_FILE = Path(__file__).with_name("routing_cases.txt")

# A fixed catalog shaped like the target laptop, so results never depend on what is installed where it runs.
EVAL_APPS = {
    "notepad": "notepad.exe", "kalkulator": "calc.exe", "paint": "mspaint.exe",
    "google chrome": "Google Chrome.lnk", "visual studio code": "Visual Studio Code.lnk", "discord": "Discord.lnk",
    "steam": "Steam.lnk", "obs studio": "OBS Studio.lnk", "microsoft word": "Word.lnk", "file explorer": "explorer.exe",
    "command prompt": "cmd.exe", "task manager": "taskmgr.exe", "vlc media player": "VLC media player.lnk",
    "laragon": "Laragon.lnk", "capcut": "CapCut.lnk",
}
EVAL_STORE_APPS = {
    name: f"shell:AppsFolder\\{name.replace(' ', '')}!App"
    for name in ("whatsapp", "spotify", "settings", "camera", "photos", "calculator", "microsoft store", "netflix",
                 "clock", "terminal", "sound recorder", "snipping tool", "media player", "sticky notes")
}
EVAL_GAMES = {"dota 2": "steam://rungameid/570", "pubg battlegrounds": "steam://rungameid/578080",
              "apex legends": "steam://rungameid/1172470"}
EVAL_WEBSITES = {"instagram": "https://www.instagram.com", "tiktok": "https://www.tiktok.com",
                 "shopee": "https://shopee.co.id", "tokopedia": "https://www.tokopedia.com", "twitter": "https://x.com",
                 "github": "https://github.com", "linkedin": "https://www.linkedin.com"}


@dataclass
class Expectation:
    path: str | None = None  # "rule" | "agent" | None (any)
    intent: str | None = None
    args: dict[str, str] = field(default_factory=dict)
    forbidden: tuple[str, ...] = ()

    def matches(self, route: Route) -> bool:
        if self.forbidden:
            return route.intent not in self.forbidden
        if self.path and route.path != self.path:
            return False
        if self.intent and route.intent != self.intent:
            return False
        return all(_arg_text(route.args.get(key)) == value for key, value in self.args.items())


@dataclass
class Case:
    category: str
    utterance: str
    expectations: list[Expectation]
    line: int

    def check(self, route: Route) -> bool:
        return any(expectation.matches(route) for expectation in self.expectations)


@dataclass
class Result:
    case: Case
    route: Route
    passed: bool


def _arg_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return "" if value is None else str(value)


def parse_expectation(text: str) -> Expectation:
    """"rule:open_app name=spotify" → Expectation(path="rule", intent="open_app", args={"name": "spotify"})."""
    parts = shlex.split(text)
    head, args = parts[0], dict(part.split("=", 1) for part in parts[1:])
    if head.startswith("not:"):
        return Expectation(forbidden=tuple(head[4:].split(",")))
    if head == "agent":
        return Expectation(path="agent", args=args)
    path, _, intent = head.partition(":")
    return Expectation(path=path, intent=intent or None, args=args)


def load_cases(path: Path = CASES_FILE) -> list[Case]:
    cases, category = [], "uncategorized"
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            category = line.lstrip("# ").split(" ")[0]
            continue
        utterance, _, expected = line.partition("=>")
        if not expected:
            raise ValueError(f"{path.name}:{number}: missing '=>'")
        alternatives = [parse_expectation(part.strip()) for part in expected.split(" | ")]
        cases.append(Case(category, utterance.strip(), alternatives, number))
    return cases


def eval_config() -> dict[str, Any]:
    config = apply_personality_preset(copy.deepcopy(DEFAULT_CONFIG))
    config["auto_discovery"] = {"enabled": True, "scan_start_menu": False, "scan_desktop": False, "scan_steam": False,
                                "scan_store_apps": True}
    config["apps"] = dict(EVAL_APPS)
    config["games"].update(EVAL_GAMES)
    config["websites"].update(EVAL_WEBSITES)
    config["files"] = {"downloads": "C:/Users/demo/Downloads"}
    return config


def build_router(config: dict[str, Any] | None = None) -> tuple[Router, dict[str, Any]]:
    config = config or eval_config()
    launcher = Launcher(config, open_url=lambda url: None, start_file=lambda path: None, run_command=lambda cmd: None,
                        start_apps_scanner=lambda: dict(EVAL_STORE_APPS))
    return Router(config, launcher), config


def route_utterance(router: Router, config: dict[str, Any], utterance: str) -> Route:
    """The same steps as Assistant.handle before routing: wake phrase, casual-speech cleanup."""
    _, command = strip_wake_prefix(normalize(utterance), config.get("wake", {}))
    return router.route(clean_conversational_command(command))


def run(cases: list[Case] | None = None) -> list[Result]:
    router, config = build_router()
    results = []
    for case in cases if cases is not None else load_cases():
        route = route_utterance(router, config, case.utterance)
        results.append(Result(case, route, case.check(route)))
    return results


def summarize(results: list[Result]) -> str:
    by_category: dict[str, list[Result]] = defaultdict(list)
    for result in results:
        by_category[result.case.category].append(result)
    lines = []
    for category, items in by_category.items():
        passed = sum(item.passed for item in items)
        lines.append(f"{category:12} {passed:3}/{len(items):<3} {100 * passed / len(items):5.1f}%")
    total = sum(result.passed for result in results)
    lines.append(f"{'TOTAL':12} {total:3}/{len(results):<3} {100 * total / len(results):5.1f}%")
    return "\n".join(lines)


def describe(route: Route) -> str:
    shown = {key: value for key, value in route.args.items() if key not in ("text", "target", "url", "path", "command")}
    return f"{route.path}:{route.intent}" + (f" {shown}" if shown else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--category", help="only this category")
    parser.add_argument("--quiet", action="store_true", help="summary only")
    args = parser.parse_args(argv)
    cases = [case for case in load_cases() if not args.category or case.category == args.category]
    duplicates = [text for text, count in Counter(normalize(case.utterance) for case in cases).items() if count > 1]
    results = run(cases)
    print(summarize(results))
    if duplicates:
        print(f"\nDuplicate utterances: {duplicates}")
    if not args.quiet:
        failures = [result for result in results if not result.passed]
        print(f"\n{len(failures)} failures:")
        for result in failures:
            expected = " | ".join(_expectation_text(e) for e in result.case.expectations)
            print(f"  [{result.case.category}] {result.case.utterance!r}\n      want {expected}\n      got  {describe(result.route)}")
    return 0


def _expectation_text(expectation: Expectation) -> str:
    if expectation.forbidden:
        return "not " + ",".join(expectation.forbidden)
    head = f"{expectation.path or ''}:{expectation.intent or '*'}"
    return head + "".join(f" {key}={value}" for key, value in expectation.args.items())


if __name__ == "__main__":
    sys.exit(main())
