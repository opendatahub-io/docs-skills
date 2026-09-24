#!/usr/bin/env python3
"""Run Vale and return its alerts as data."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SEVERITY_RANK = {"suggestion": 0, "warning": 1, "error": 2}


class ValeError(RuntimeError):
    """Vale could not run, or ran but could not lint what it was given."""


@dataclass(frozen=True)
class Alert:
    """One Vale alert, with the auto-fix data a rule may carry."""

    file: str
    line: int
    span: tuple[int, int]
    check: str
    severity: str
    message: str
    match: str
    action: dict | None = None
    description: str = ""
    link: str = ""
    suggestions: list[str] = field(default_factory=list)


def describe_error(stderr, stdout="", returncode=None):
    """Vale's runtime failure as one line: the code, the message, the next move."""
    raw = (stderr or stdout or "").strip()
    code, message = "", ""
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        code = str(payload.get("Code") or "").strip()
        message = _substantive(str(payload.get("Text") or ""), code)
    if not message and raw:
        message = " ".join(raw.splitlines()[0].split())
    if not message:
        return f"vale exited {returncode} with no output"

    message = message[:200].rstrip().rstrip(".")
    lead = f"{code}: {message}" if code else message
    return f"{lead}. {_next_action(message)}"


def _substantive(text, code):
    """The paragraph of Vale's `Text` that names the actual problem."""
    paragraphs = [" ".join(part.split()) for part in text.split("\n\n")]
    kept = [
        part
        for part in paragraphs
        if part
        and not (code and part.startswith(code))
        and not part.startswith("Execution stopped")
    ]
    if kept:
        return kept[0]
    return " ".join(text.split())


def _next_action(message):
    """What a reader should do about it, which is usually syncing styles."""
    if "StylesPath" in message or message.startswith("style "):
        return "Run `/docs --sync-styles` to install the styles the config names."
    return "Check the Vale config the run was given."


def at_or_above(severity, floor):
    """True when `severity` is at or above `floor`. An unknown value counts as an error."""
    return SEVERITY_RANK.get(severity, 2) >= SEVERITY_RANK.get(floor, 2)


def parse_range(text):
    """`START-END` as a 1-based, inclusive pair of line numbers."""
    first, _, last = text.partition("-")
    try:
        start, end = int(first), int(last)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected START-END, got {text!r}") from None
    if start < 1 or end < start:
        raise argparse.ArgumentTypeError(f"not a line range: {text!r}")
    return (start, end)


def expand_to_blocks(lines, ranges):
    """Widen each range to the blank-line-delimited blocks it touches, and merge.

    A prose rule reports where its sentence starts, which in wrapped Markdown is
    often a line above the one an edit changed. Scoping to the changed lines
    alone drops those alerts; scoping to the paragraph holding them keeps them
    without pulling in the rest of the page.
    """
    total = len(lines)
    if not total:
        return []

    widened = []
    for start, end in ranges:
        start = min(max(start, 1), total)
        end = min(max(end, start), total)
        while start > 1 and lines[start - 2].strip():
            start -= 1
        while end < total and lines[end].strip():
            end += 1
        widened.append((start, end))

    merged = []
    for start, end in sorted(widened):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def in_ranges(line, ranges):
    """True when `line` falls inside one of `ranges`. No ranges means no scope."""
    if not ranges:
        return True
    return any(start <= line <= end for start, end in ranges)


def replacement(alert):
    """The exact text an alert's `replace` action carries, or None for the rest.

    A `substitution` rule with one right answer ships that answer in the
    alert. Applying it here is the difference between a fix that costs a
    model call and a fix that costs a string splice.
    """
    action = alert.action or {}
    if action.get("name") != "replace":
        return None
    params = action.get("params") or []
    if len(params) != 1 or not isinstance(params[0], str):
        return None
    return params[0]


def _match_case(source, text):
    """Carry `source`'s capitalization onto `text`.

    The swap tables are written in lower case because that is how the word
    usually appears, so replacing "Utilize" with "use" would open a sentence
    in lower case. A fix applied without thought has to be right every time.
    """
    if not source or not text:
        return text
    if source.isupper() and len(source) > 1:
        return text.upper()
    if source[:1].isupper():
        return text[:1].upper() + text[1:]
    return text


def apply_fixes(path, alerts):
    """Apply every alert carrying an exact replacement. Returns those applied.

    Vale reports `Span` as 1-based, inclusive offsets into `Line`, counted in
    characters. A line is rewritten right to left so that an untouched span's
    offsets stay valid, and a span overlapping one already rewritten is left
    for the model.
    """
    path = Path(path)
    lines = path.read_text().split("\n")

    by_line = {}
    for alert in alerts:
        text = replacement(alert)
        if text is not None:
            by_line.setdefault(alert.line, []).append((alert, text))

    applied = []
    for number, items in by_line.items():
        if not 1 <= number <= len(lines):
            continue
        line = lines[number - 1]
        rewritten = []
        for alert, text in sorted(items, key=lambda item: -item[0].span[0]):
            start, end = alert.span
            if start < 1 or end > len(line) or start > end:
                continue
            if any(start <= done_end and done_start <= end for done_start, done_end in rewritten):
                continue
            # The file moved under us if the span no longer holds the match,
            # and a blind splice would corrupt it.
            if alert.match and line[start - 1 : end] != alert.match:
                continue
            line = line[: start - 1] + _match_case(line[start - 1 : end], text) + line[end:]
            rewritten.append((start, end))
            applied.append(alert)
        lines[number - 1] = line

    if applied:
        path.write_text("\n".join(lines))
    return applied


def run(config, files, timeout=120, level=None):
    """Lint `files`, returning every alert. A `config` of None lets Vale find its own.

    `level` is passed to Vale as `--minAlertLevel`, so a run that only gates on
    errors never builds, serializes or parses the suggestions it would discard.
    The composed config sets the floor to `suggestion` for the callers that do
    want them, and this narrows it per call instead of per config.
    """
    paths = [str(path) for path in files]
    if not paths:
        return []

    for path in paths:
        if not Path(path).exists():
            raise ValeError(f"file not found: {path}")

    argv = ["vale"]
    if config is not None:
        argv += ["--config", str(config)]
    if level is not None:
        argv += [f"--minAlertLevel={level}"]
    argv += ["--output=JSON", *paths]

    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise ValeError("the vale binary is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValeError(f"vale timed out after {timeout}s") from exc

    stdout = completed.stdout.lstrip()
    # Vale exits 1 when it finds alerts, which is a result rather than a failure.
    # A runtime error exits nonzero too, and prints something that is not JSON.
    if not stdout.startswith("{"):
        raise ValeError(describe_error(completed.stderr, completed.stdout, completed.returncode))

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValeError(f"vale produced output that is not JSON: {stdout[:200]}") from exc

    alerts = []
    for path, items in payload.items():
        for item in items:
            action = item.get("Action") or {}
            alerts.append(
                Alert(
                    file=path,
                    line=item["Line"],
                    span=tuple(item["Span"]),
                    check=item["Check"],
                    severity=item["Severity"],
                    message=item["Message"],
                    match=item.get("Match", ""),
                    action=(
                        {"name": action["Name"], "params": action.get("Params") or []}
                        if action.get("Name")
                        else None
                    ),
                    description=item.get("Description", ""),
                    link=item.get("Link", ""),
                    suggestions=item.get("Suggestions", []),
                )
            )
    return alerts


def format_applied(path, applied):
    """Tell the caller what was rewritten under it, because its copy is stale.

    One line, and short on purpose. This is a fact rather than an instruction:
    the rule name and the line number would pad a message nobody acts on, and
    the point of applying a fix here was to spend less than relaying it did.
    Repeats collapse, because the same swap made twice reads the same once.
    """
    swaps = []
    for alert in sorted(applied, key=lambda a: (a.line, a.span[0])):
        swap = f"{alert.match}->{replacement(alert)}"
        if swap not in swaps:
            swaps.append(swap)
    return f"Vale applied {len(applied)} exact replacement(s) to {path}: {', '.join(swaps)}"


# Long enough to show the sentence a length rule is complaining about, short
# enough that a table row or a pasted URL cannot run away with the payload.
EXCERPT = 300


def _source_line(alert, cache):
    """The line an alert names, read from the file Vale linted."""
    lines = cache.get(alert.file)
    if lines is None:
        try:
            lines = Path(alert.file).read_text().split("\n")
        except OSError:
            lines = []
        cache[alert.file] = lines
    if 1 <= alert.line <= len(lines):
        return lines[alert.line - 1].strip()
    return ""


def carries_its_text(alert):
    """Whether the message already says what the rule found.

    Most do: "Inflated word: 'leveraging'". Two do not. `Direct.Length` says
    only how many words the sentence ran to, and its match is the sentence's
    first word; `RedHat.NoGerundsInTitles` names no heading at all. An alert
    that quotes nothing, against a line number in a rendered file the model
    was never given, is an alert it can only answer by guessing.
    """
    # The quoted form, not a substring: a match as short as `If` or `A` would
    # otherwise turn up inside some word of the message by accident and the
    # excerpt would go missing on exactly the rules that need it.
    return bool(alert.match) and f"'{alert.match}'" in alert.message


def format_alerts(path, alerts, floor="error", scoped=False):
    """Render alerts as the instruction a model reads next."""
    where = "in the lines just changed in" if scoped else "in"
    head = f"Vale reports {len(alerts)} alert(s) at {floor} level or above {where} {path}:"
    cache = {}
    # One excerpt per line. Three rules reading the same sentence carried three
    # copies of it, and on a page linted below `error` that repetition was most
    # of the payload. Every entry names its line, so saying it once says it.
    excerpted = set()
    body = []
    for a in alerts:
        entry = f"line {a.line}: {a.check} [{a.severity}] — {a.message}"
        if not carries_its_text(a) and (a.file, a.line) not in excerpted:
            source = _source_line(a, cache)
            if source:
                entry += f"\n    {source[:EXCERPT]}"
                excerpted.add((a.file, a.line))
        body.append(entry)
    if floor == "error":
        tail = (
            "Fix these before moving on, preserving the markup exactly. "
            "Do not disable a rule to clear one."
        )
    else:
        tail = (
            "Fix the errors before moving on, preserving the markup exactly. "
            "Treat warnings and suggestions as advice. Do not disable a rule to clear one."
        )
    return "\n".join([head, *body, tail])


def main(argv=None):
    """Lint one file and print the alerts a caller should relay, or nothing."""
    parser = argparse.ArgumentParser(description="Lint a file and report relayable alerts")
    parser.add_argument("path", help="File to lint")
    parser.add_argument("--config", default=None, help="Vale config. Default: Vale's own search")
    parser.add_argument("--level", default="error", choices=sorted(SEVERITY_RANK))
    parser.add_argument("--json", action="store_true", help="Emit alerts as JSON")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply the alerts carrying an exact replacement, then report what is left",
    )
    parser.add_argument(
        "--range",
        action="append",
        dest="ranges",
        type=parse_range,
        metavar="START-END",
        help="Limit the run to these lines, widened to their blocks. Repeatable",
    )
    args = parser.parse_args(argv)

    # Read before linting, and once. `apply_fixes` splices inside a line and
    # never changes how many there are, so a scope computed here stays valid
    # across the fix pass and the re-lint that follows it.
    scope = []
    if args.ranges:
        try:
            lines = Path(args.path).read_text().split("\n")
        except OSError as exc:
            print(f"cannot read {args.path}: {exc}", file=sys.stderr)
            return 2
        scope = expand_to_blocks(lines, args.ranges)

    def relay(found):
        return [
            a for a in found if at_or_above(a.severity, args.level) and in_ranges(a.line, scope)
        ]

    try:
        alerts = run(args.config, [args.path], level=args.level)
    except ValeError as exc:
        # A caller that cannot lint is not a caller that should fail. Report and
        # leave the decision to it.
        print(str(exc), file=sys.stderr)
        return 2

    relayed = relay(alerts)

    applied = []
    if args.fix and relayed:
        # Only what the scope covers. A gate whose blast radius is wider than
        # the edit that opened it rewrites paragraphs nobody was looking at.
        applied = apply_fixes(args.path, relayed)
        if applied:
            try:
                alerts = run(args.config, [args.path], level=args.level)
            except ValeError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            relayed = relay(alerts)

    if args.json:
        print(json.dumps([a.__dict__ for a in relayed]))
        return 1 if relayed else 0

    report = []
    if applied:
        # Said even when nothing is left, because the file on disk no longer
        # matches the copy the caller believes it wrote.
        report.append(format_applied(args.path, applied))
    if relayed:
        report.append(format_alerts(args.path, relayed, args.level, scoped=bool(scope)))
    if report:
        print("\n\n".join(report))
    return 1 if relayed else 0


if __name__ == "__main__":
    raise SystemExit(main())
