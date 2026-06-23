#!/usr/bin/env python3
"""
Analyze a docs-orchestrator pipeline run for failures, bottlenecks,
and context-pressure indicators.

Reads:
  - progress file: .agent_workspace/<ticket>/workflow/<type>_<ticket>.json
  - step-result.json sidecars from each step output folder
  - file system metadata (sizes, modification times) for context estimation

Outputs JSON to stdout with sections: timeline, failures, bottlenecks,
context_pressure, and recommendations.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    ts = ts.rstrip("Z").replace("+00:00", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class DirStats:
    __slots__ = ("size_kb", "file_count", "earliest_mtime", "latest_mtime")

    def __init__(
        self,
        size_kb: float = 0.0,
        file_count: int = 0,
        earliest_mtime: datetime | None = None,
        latest_mtime: datetime | None = None,
    ):
        self.size_kb = size_kb
        self.file_count = file_count
        self.earliest_mtime = earliest_mtime
        self.latest_mtime = latest_mtime


def scan_dir(path: str, cache: dict[str, DirStats] | None = None) -> DirStats:
    if cache is not None and path in cache:
        return cache[path]
    total_kb = 0.0
    count = 0
    earliest_ts = float("inf")
    latest_ts = 0.0
    found = False
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                count += 1
                try:
                    st = os.stat(fp)
                    total_kb += st.st_size / 1024
                    earliest_ts = min(earliest_ts, st.st_mtime)
                    latest_ts = max(latest_ts, st.st_mtime)
                    found = True
                except OSError:
                    pass
    except OSError:
        pass
    stats = DirStats(
        size_kb=total_kb,
        file_count=count,
        earliest_mtime=datetime.fromtimestamp(earliest_ts, tz=timezone.utc) if found else None,
        latest_mtime=datetime.fromtimestamp(latest_ts, tz=timezone.utc) if found else None,
    )
    if cache is not None:
        cache[path] = stats
    return stats


CONTEXT_HEAVY_STEPS = {
    "requirements": 1.0,
    "code-analysis": 1.5,
    "scope-req-audit": 1.0,
    "pr-analysis": 0.8,
    "planning": 1.2,
    "writing": 2.0,
    "technical-review": 1.8,
    "style-review": 0.8,
    "quality-gate": 1.0,
    "resolve-feedback": 1.5,
}


def estimate_context_pressure(
    step_order: list[str],
    steps: dict,
    base_path: str,
    cache: dict[str, DirStats] | None = None,
) -> dict:
    """Estimate context pressure using artifact sizes and step progression."""
    completed = [s for s in step_order if steps.get(s, {}).get("status") == "completed"]
    total_steps = len([s for s in step_order if steps.get(s, {}).get("status") != "skipped"])

    total_artifact_kb = 0.0
    per_step_kb = {}
    for name in completed:
        step_dir = os.path.join(base_path, name)
        stats = scan_dir(step_dir, cache)
        per_step_kb[name] = round(stats.size_kb, 1)
        total_artifact_kb += stats.size_kb

    weighted_load = sum(CONTEXT_HEAVY_STEPS.get(s, 0.5) for s in completed)

    iterations = 0
    for name in ["technical-review", "quality-gate"]:
        result = steps.get(name, {}).get("result") or {}
        it = result.get("iteration", 1)
        if isinstance(it, int) and it > 1:
            iterations += it - 1

    risk_score = 0
    risk_factors = []

    if len(completed) >= 6:
        risk_score += 2
        risk_factors.append(f"{len(completed)}/{total_steps} steps completed in single session")
    if len(completed) >= 8:
        risk_score += 2

    if total_artifact_kb > 500:
        risk_score += 1
        risk_factors.append(f"Total artifacts: {total_artifact_kb:.0f} KB")
    if total_artifact_kb > 1000:
        risk_score += 2

    if weighted_load > 8.0:
        risk_score += 2
        risk_factors.append(f"Weighted context load: {weighted_load:.1f}")

    if iterations > 0:
        risk_score += iterations
        risk_factors.append(f"{iterations} extra iteration(s) in review/gate loops")

    # F8: artifact growth across iterations compounds context pressure
    for name in ["technical-review", "quality-gate"]:
        result = steps.get(name, {}).get("result") or {}
        it = result.get("iteration", 1)
        step_kb = per_step_kb.get(name, 0)
        if isinstance(it, int) and it > 1 and step_kb > 0:
            per_iter_kb = step_kb / it
            if per_iter_kb > 50:
                extra = min(3, int(per_iter_kb / 50))
                risk_score += extra
                risk_factors.append(
                    f"{name} artifacts grow ~{per_iter_kb:.0f} KB/iteration "
                    f"({step_kb:.0f} KB over {it} iterations)"
                )

    code_analysis_kb = per_step_kb.get("code-analysis", 0)
    if code_analysis_kb > 200:
        risk_score += 1
        risk_factors.append(f"code-analysis artifacts: {code_analysis_kb:.0f} KB")

    level = "low"
    if risk_score >= 3:
        level = "moderate"
    if risk_score >= 6:
        level = "high"
    if risk_score >= 9:
        level = "critical"

    return {
        "level": level,
        "risk_score": risk_score,
        "risk_factors": risk_factors,
        "completed_steps": len(completed),
        "total_active_steps": total_steps,
        "total_artifact_kb": round(total_artifact_kb, 1),
        "per_step_artifact_kb": per_step_kb,
        "weighted_context_load": round(weighted_load, 1),
        "iteration_overhead": iterations,
    }


def get_step_file_span(
    base_path: str,
    step_name: str,
    cache: dict[str, DirStats] | None = None,
) -> tuple[datetime | None, datetime | None]:
    step_dir = os.path.join(base_path, step_name)
    stats = scan_dir(step_dir, cache)
    return stats.earliest_mtime, stats.latest_mtime


def get_step_mtime(
    base_path: str,
    step_name: str,
    cache: dict[str, DirStats] | None = None,
) -> datetime | None:
    sidecar_path = os.path.join(base_path, step_name, "step-result.json")
    if os.path.isfile(sidecar_path):
        try:
            mt = os.path.getmtime(sidecar_path)
            return datetime.fromtimestamp(mt, tz=timezone.utc)
        except OSError:
            pass

    _, latest = get_step_file_span(base_path, step_name, cache)
    return latest


def build_timeline(
    step_order: list[str],
    steps: dict,
    base_path: str,
    workflow_created: datetime | None,
    cache: dict[str, DirStats] | None = None,
) -> list[dict]:
    """Build a chronological timeline using filesystem mtimes as the
    primary time source.  Model-generated sidecar ``completed_at``
    values are included for reference but NOT used for duration
    calculations — they drift significantly from wall-clock time."""
    entries = []
    prev_end: datetime | None = None

    # Use the progress file's own mtime as the workflow start reference
    # (more reliable than model-generated created_at).
    progress_path = os.path.join(base_path, "workflow")
    if os.path.isdir(progress_path):
        try:
            candidates = [
                os.path.join(progress_path, f)
                for f in os.listdir(progress_path)
                if f.endswith(".json") and not f.endswith(".stop_count")
            ]
            if candidates:
                earliest = min(os.path.getctime(c) for c in candidates)
                prev_end = datetime.fromtimestamp(earliest, tz=timezone.utc)
        except OSError:
            pass
    if prev_end is None:
        prev_end = workflow_created

    for name in step_order:
        info = steps.get(name, {})
        status = info.get("status", "unknown")

        sidecar_path = os.path.join(base_path, name, "step-result.json")
        sidecar = {}
        if os.path.isfile(sidecar_path):
            try:
                with open(sidecar_path) as f:
                    sidecar = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        step_mtime = get_step_mtime(base_path, name, cache)
        step_dir = os.path.join(base_path, name)
        stats = scan_dir(step_dir, cache)

        duration_s = None
        if step_mtime and prev_end:
            delta = round((step_mtime - prev_end).total_seconds())
            if delta >= 0:
                duration_s = delta

        entry = {
            "step": name,
            "status": status,
            "completed_at": step_mtime.isoformat() if step_mtime else None,
            "sidecar_completed_at": sidecar.get("completed_at"),
            "duration_s": duration_s,
            "artifact_kb": round(stats.size_kb, 1),
            "file_count": stats.file_count,
        }

        if sidecar.get("iteration") is not None and sidecar["iteration"] > 1:
            entry["iteration"] = sidecar["iteration"]

        result = info.get("result") or {}
        if result.get("skip_reason"):
            entry["skip_reason"] = result["skip_reason"]
        if result.get("confidence"):
            entry["confidence"] = result["confidence"]
        if result.get("severity_counts"):
            entry["severity_counts"] = result["severity_counts"]

        entries.append(entry)
        if step_mtime:
            prev_end = step_mtime

    # Detect iteration loops and compute combined durations.
    # When steps run in a loop (quality-gate → resolve-feedback → quality-gate),
    # individual mtimes interleave and per-step durations are misleading.
    # We group them and compute the span from the preceding step's end to the
    # latest file mtime across all directories in the loop.
    loop_groups = detect_loop_groups(step_order, steps, base_path, entries, cache)
    if loop_groups:
        for entry in entries:
            for lg in loop_groups:
                if entry["step"] in lg["steps"]:
                    entry["loop_group"] = lg["name"]

    return entries, loop_groups


KNOWN_LOOPS = [
    {
        "name": "technical-review-loop",
        "trigger": "technical-review",
        "members": ["technical-review"],
        "label": "Technical review loop",
    },
    {
        "name": "quality-gate-loop",
        "trigger": "quality-gate",
        "members": ["quality-gate", "resolve-feedback"],
        "label": "Quality gate + resolve-feedback loop",
    },
]


def detect_loop_groups(
    step_order: list[str],
    steps: dict,
    base_path: str,
    timeline_entries: list[dict],
    cache: dict[str, DirStats] | None = None,
) -> list[dict]:
    """Detect iteration loops and compute combined wall-clock durations."""
    groups = []

    for loop_def in KNOWN_LOOPS:
        trigger = loop_def["trigger"]
        result = steps.get(trigger, {}).get("result") or {}
        iteration = result.get("iteration", 1)
        if not isinstance(iteration, int) or iteration <= 1:
            continue
        if steps.get(trigger, {}).get("status") != "completed":
            continue

        members = [
            m
            for m in loop_def["members"]
            if steps.get(m, {}).get("status") in ("completed", "skipped")
        ]
        if not members:
            continue

        # Find the preceding step's mtime as the loop start
        first_member_idx = None
        for i, name in enumerate(step_order):
            if name == members[0]:
                first_member_idx = i
                break

        loop_start = None
        if first_member_idx is not None and first_member_idx > 0:
            for j in range(first_member_idx - 1, -1, -1):
                prev_name = step_order[j]
                for te in timeline_entries:
                    if te["step"] == prev_name and te.get("completed_at"):
                        loop_start = parse_iso(te["completed_at"])
                        break
                if loop_start:
                    break

        latest_mtime = None
        for member in members:
            member_dir = os.path.join(base_path, member)
            stats = scan_dir(member_dir, cache)
            if stats.latest_mtime and (latest_mtime is None or stats.latest_mtime > latest_mtime):
                latest_mtime = stats.latest_mtime

        combined_s = None
        if loop_start and latest_mtime:
            delta = round((latest_mtime - loop_start).total_seconds())
            if delta >= 0:
                combined_s = delta

        # Compute per-step breakdown within the loop.
        # For each member, measure the span of file activity in its own
        # directory.  This captures the time the agent actively spent
        # producing that step's artifacts, even when iterations
        # interleave files across directories.
        step_breakdown = []
        for member in members:
            earliest, latest = get_step_file_span(base_path, member, cache)
            self_s = None
            if earliest and latest:
                self_s = round((latest - earliest).total_seconds())
            step_breakdown.append(
                {
                    "step": member,
                    "self_duration_s": self_s,
                    "self_duration_min": round(self_s / 60, 1) if self_s else None,
                    "earliest_file": earliest.isoformat() if earliest else None,
                    "latest_file": latest.isoformat() if latest else None,
                }
            )

        # Attribute remaining loop time not covered by member file spans.
        # This is orchestrator overhead, progress file writes, skill
        # loading, and gaps between steps.
        member_self_total = sum(
            sb["self_duration_s"] for sb in step_breakdown if sb["self_duration_s"] is not None
        )
        overhead_s = None
        if combined_s is not None:
            overhead_s = max(0, combined_s - member_self_total)

        groups.append(
            {
                "name": loop_def["name"],
                "label": loop_def["label"],
                "steps": members,
                "iterations": iteration,
                "combined_duration_s": combined_s,
                "combined_duration_min": round(combined_s / 60, 1) if combined_s else None,
                "overhead_s": overhead_s,
                "started_at": loop_start.isoformat() if loop_start else None,
                "finished_at": latest_mtime.isoformat() if latest_mtime else None,
                "step_breakdown": step_breakdown,
            }
        )

    return groups


def detect_failures(
    step_order: list[str],
    steps: dict,
    base_path: str,
) -> list[dict]:
    """Identify failed steps, missing outputs, and anomalies."""
    issues = []

    for name in step_order:
        info = steps.get(name, {})
        status = info.get("status", "unknown")

        if status == "failed":
            issues.append(
                {
                    "type": "step_failed",
                    "step": name,
                    "severity": "high",
                    "detail": f"Step '{name}' has status 'failed' in progress file",
                }
            )

        if status == "completed":
            output = info.get("output")
            if output and not os.path.isdir(output):
                issues.append(
                    {
                        "type": "missing_output",
                        "step": name,
                        "severity": "high",
                        "detail": (
                            f"Step '{name}' marked completed but output dir missing: {output}"
                        ),
                    }
                )

            sidecar = os.path.join(base_path, name, "step-result.json")
            if not os.path.isfile(sidecar):
                issues.append(
                    {
                        "type": "missing_sidecar",
                        "step": name,
                        "severity": "low",
                        "detail": f"Step '{name}' has no step-result.json sidecar",
                    }
                )

        if status == "deferred":
            issues.append(
                {
                    "type": "step_deferred",
                    "step": name,
                    "severity": "medium",
                    "detail": (
                        f"Step '{name}' is still deferred — upstream condition never resolved"
                    ),
                }
            )

    result = steps.get("technical-review", {}).get("result") or {}
    if result.get("confidence") == "LOW":
        issues.append(
            {
                "type": "low_confidence",
                "step": "technical-review",
                "severity": "high",
                "detail": (
                    "Technical review ended with LOW confidence"
                    f" (iteration {result.get('iteration', '?')})"
                ),
            }
        )

    severity = result.get("severity_counts") or {}
    critical = severity.get("critical", 0)
    significant = severity.get("significant", 0)
    if (
        isinstance(critical, int)
        and isinstance(significant, int)
        and (critical >= 3 or critical + significant >= 8)
    ):
        issues.append(
            {
                "type": "high_severity_count",
                "step": "technical-review",
                "severity": "high",
                "detail": (
                    f"Technical review has {critical} critical + {significant} significant issues"
                ),
            }
        )

    result = steps.get("quality-gate", {}).get("result") or {}
    ia = result.get("intent_alignment")
    if isinstance(ia, (int, float)) and ia < 3:
        issues.append(
            {
                "type": "quality_gate_low",
                "step": "quality-gate",
                "severity": "high",
                "detail": f"Quality gate intent_alignment={ia}/5 (below acceptable threshold)",
            }
        )

    result = steps.get("planning", {}).get("result") or {}
    if result.get("module_count") == 0 and steps.get("planning", {}).get("status") == "completed":
        issues.append(
            {
                "type": "empty_plan",
                "step": "planning",
                "severity": "high",
                "detail": "Planning produced 0 modules",
            }
        )

    result = steps.get("writing", {}).get("result") or {}
    if (
        steps.get("writing", {}).get("status") == "completed"
        and isinstance(result.get("files"), list)
        and len(result["files"]) == 0
    ):
        issues.append(
            {
                "type": "no_files_written",
                "step": "writing",
                "severity": "high",
                "detail": "Writing step completed but produced 0 files",
            }
        )

    return issues


EXPECTED_DURATION_S = {
    "requirements": 180,
    "code-analysis": 300,
    "scope-req-audit": 300,
    "planning": 120,
    "writing": 300,
    "technical-review": 600,
    "style-review": 180,
    "quality-gate": 300,
    "resolve-feedback": 300,
}


def detect_bottlenecks(timeline: list[dict]) -> list[dict]:
    """Identify steps with unusually long durations."""
    bottlenecks = []
    durations = [
        (e["step"], e["duration_s"])
        for e in timeline
        if e.get("duration_s") is not None and e["duration_s"] > 0
    ]

    if not durations:
        return bottlenecks

    avg = sum(d for _, d in durations) / len(durations)

    for name, dur in durations:
        ratio = dur / avg if avg > 0 else float("inf")
        expected = EXPECTED_DURATION_S.get(name)
        if dur > 300 and ratio > 2.0:
            bottlenecks.append(
                {
                    "step": name,
                    "duration_s": dur,
                    "duration_min": round(dur / 60, 1),
                    "ratio_to_avg": round(ratio, 1),
                    "severity": "high" if ratio > 3.0 else "medium",
                }
            )
        elif dur > 600:
            bottlenecks.append(
                {
                    "step": name,
                    "duration_s": dur,
                    "duration_min": round(dur / 60, 1),
                    "ratio_to_avg": round(ratio, 1),
                    "severity": "medium",
                }
            )
        elif expected and dur > expected * 2:
            bottlenecks.append(
                {
                    "step": name,
                    "duration_s": dur,
                    "duration_min": round(dur / 60, 1),
                    "ratio_to_avg": round(ratio, 1),
                    "expected_s": expected,
                    "severity": "medium" if dur > expected * 3 else "low",
                }
            )

    return sorted(bottlenecks, key=lambda b: b["duration_s"], reverse=True)


def build_recommendations(
    failures: list[dict],
    bottlenecks: list[dict],
    context_pressure: dict,
) -> list[str]:
    """Generate actionable recommendations from analysis."""
    recs = []

    high_failures = [f for f in failures if f["severity"] == "high"]
    if high_failures:
        step_names = ", ".join(f["step"] for f in high_failures)
        recs.append(f"Fix high-severity failures before re-running: {step_names}")

    if context_pressure["level"] in ("high", "critical"):
        recs.append(
            "Context pressure is elevated. Consider: "
            "(1) splitting into a custom workflow YAML with fewer steps, "
            "(2) using --draft to skip framework detection overhead, "
            "(3) pre-resolving source repos with source.yaml to reduce resolution chatter"
        )

    if context_pressure["iteration_overhead"] > 0:
        recs.append(
            f"Review loops added {context_pressure['iteration_overhead']} extra iteration(s). "
            "If iterations are consistently needed, consider improving upstream step quality "
            "(requirements precision, code-analysis depth) to reduce downstream fixes"
        )

    for b in bottlenecks:
        if b["step"] == "code-analysis" and b["duration_s"] > 600:
            recs.append(
                "code-analysis is a bottleneck. Use source.yaml scope.include/exclude "
                "to limit the analyzed codebase surface"
            )
        elif b["step"] == "technical-review" and b["duration_s"] > 900:
            recs.append(
                "technical-review is slow. This often indicates large claim counts. "
                "Consider reducing module count in planning or scoping source code more tightly"
            )
        elif b["step"] == "writing" and b["duration_s"] > 900:
            recs.append(
                "writing step is slow. If the plan has many modules, consider breaking the "
                "ticket into smaller documentation units"
            )

    missing_sidecars = [f for f in failures if f["type"] == "missing_sidecar"]
    if missing_sidecars:
        names = ", ".join(f["step"] for f in missing_sidecars)
        recs.append(
            f"Missing step-result.json sidecars for: {names}. "
            "This may indicate the step completed abnormally or was interrupted. "
            "Check if context compaction lost the sidecar-write instruction"
        )

    if context_pressure["total_artifact_kb"] > 2000:
        recs.append(
            f"Total artifacts are {context_pressure['total_artifact_kb']:.0f} KB. "
            "Large artifact footprints increase disk I/O and context re-read overhead on resume"
        )

    if not recs:
        recs.append("No significant issues detected. Pipeline health looks good.")

    return recs


def analyze(progress_path: str) -> dict:
    with open(progress_path) as f:
        progress = json.load(f)

    ticket = progress.get("ticket", "unknown")
    base_path = progress.get("base_path", "")
    step_order = progress.get("step_order", [])
    steps = progress.get("steps", {})
    status = progress.get("status", "unknown")
    workflow_type = progress.get("workflow", "unknown")
    created_at = parse_iso(progress.get("created_at"))
    updated_at = parse_iso(progress.get("updated_at"))  # noqa: F841

    dir_cache: dict[str, DirStats] = {}
    timeline, loop_groups = build_timeline(step_order, steps, base_path, created_at, dir_cache)
    failures = detect_failures(step_order, steps, base_path)
    bottlenecks = detect_bottlenecks(timeline)
    context_pressure = estimate_context_pressure(step_order, steps, base_path, dir_cache)
    recommendations = build_recommendations(failures, bottlenecks, context_pressure)

    # Compute total duration from file mtimes (first and last step)
    completed_mtimes = [
        parse_iso(e["completed_at"])
        for e in timeline
        if e.get("completed_at") and e["status"] == "completed"
    ]
    total_duration_s = None
    first_mtime = min(completed_mtimes) if completed_mtimes else None
    last_mtime = max(completed_mtimes) if completed_mtimes else None
    if first_mtime and last_mtime:
        total_duration_s = round((last_mtime - first_mtime).total_seconds())

    return {
        "summary": {
            "ticket": ticket,
            "workflow": workflow_type,
            "status": status,
            "started_at": first_mtime.isoformat() if first_mtime else progress.get("created_at"),
            "finished_at": last_mtime.isoformat() if last_mtime else progress.get("updated_at"),
            "total_duration_s": total_duration_s,
            "total_duration_min": round(total_duration_s / 60, 1) if total_duration_s else None,
            "timing_source": "file_mtime",
            "progress_file": progress_path,
            "base_path": base_path,
        },
        "timeline": timeline,
        "loop_groups": loop_groups,
        "failures": failures,
        "bottlenecks": bottlenecks,
        "context_pressure": context_pressure,
        "recommendations": recommendations,
    }


def find_progress_files(ticket: str | None, workspace: str = ".agent_workspace") -> list[str]:
    """Find progress files, optionally filtering by ticket."""
    results = []
    if not os.path.isdir(workspace):
        return results

    for entry in os.listdir(workspace):
        if entry.startswith("."):
            continue
        workflow_dir = os.path.join(workspace, entry, "workflow")
        if not os.path.isdir(workflow_dir):
            continue
        if ticket and entry != ticket.lower():
            continue
        for f in os.listdir(workflow_dir):
            if f.endswith(".json") and not f.endswith(".stop_count"):
                results.append(os.path.join(workflow_dir, f))

    return sorted(results)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze docs-orchestrator pipeline run diagnostics"
    )
    parser.add_argument(
        "ticket",
        nargs="?",
        help="JIRA ticket ID (searches .agent_workspace/<ticket>/workflow/)",
    )
    parser.add_argument(
        "--progress-file",
        help="Direct path to progress JSON file (overrides ticket-based search)",
    )
    parser.add_argument(
        "--workspace",
        default=".agent_workspace",
        help="Path to .agent_workspace directory (default: .agent_workspace)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "summary"],
        default="json",
        help="Output format: 'json' (full structured output) or 'summary' (human-readable)",
    )
    args = parser.parse_args()

    if args.progress_file:
        paths = [args.progress_file]
    elif args.ticket:
        paths = find_progress_files(args.ticket, args.workspace)
    else:
        paths = find_progress_files(None, args.workspace)

    if not paths:
        target = args.progress_file or args.ticket or args.workspace
        print(json.dumps({"error": f"No progress files found for: {target}"}), file=sys.stderr)
        sys.exit(1)

    results = []
    for p in paths:
        try:
            results.append(analyze(p))
        except (json.JSONDecodeError, KeyError, OSError) as e:
            results.append({"error": str(e), "progress_file": p})

    output = results[0] if len(results) == 1 else {"runs": results}

    if args.format == "summary":
        print_summary(output)
    else:
        print(json.dumps(output, indent=2))


def print_summary(data: dict):
    """Print a human-readable summary."""
    runs = data.get("runs", [data])
    for run in runs:
        if "error" in run:
            print(f"ERROR: {run['error']} ({run.get('progress_file', '?')})")
            continue

        s = run["summary"]
        print(f"=== Pipeline Diagnostic: {s['ticket']} ({s['workflow']}) ===")
        print(f"Status: {s['status']}")
        if s.get("total_duration_min"):
            print(f"Duration: {s['total_duration_min']} min (from file mtimes)")
        print()

        cp = run["context_pressure"]
        print(f"Context pressure: {cp['level'].upper()} (score {cp['risk_score']})")
        print(f"  Steps completed: {cp['completed_steps']}/{cp['total_active_steps']}")
        print(f"  Artifacts: {cp['total_artifact_kb']:.0f} KB")
        print(f"  Weighted load: {cp['weighted_context_load']}")
        if cp["iteration_overhead"]:
            print(f"  Extra iterations: {cp['iteration_overhead']}")
        for rf in cp["risk_factors"]:
            print(f"  ! {rf}")
        print()

        if run["failures"]:
            print("Failures:")
            for f in run["failures"]:
                print(f"  [{f['severity'].upper()}] {f['type']}: {f['detail']}")
            print()

        if run["bottlenecks"]:
            print("Bottlenecks:")
            for b in run["bottlenecks"]:
                print(f"  {b['step']}: {b['duration_min']} min ({b['ratio_to_avg']}x avg)")
            print()

        print("Timeline:")
        loop_steps = set()
        for lg in run.get("loop_groups", []):
            for s in lg["steps"]:
                loop_steps.add(s)

        for t in run["timeline"]:
            dur_s = t.get("duration_s")
            if dur_s is not None:
                if dur_s >= 60:
                    dur = f" ({dur_s // 60}m {dur_s % 60}s)"
                else:
                    dur = f" ({dur_s}s)"
            else:
                dur = ""
            extra = ""
            if t.get("iteration"):
                extra += f" [iter {t['iteration']}]"
            if t.get("confidence"):
                extra += f" [confidence={t['confidence']}]"
            if t.get("skip_reason"):
                extra += f" [skip: {t['skip_reason']}]"
            if t["step"] in loop_steps:
                extra += " *"
            print(
                f"  {t['status']:>12}  {t['step']}{dur}{extra}"
                f"  ({t['artifact_kb']} KB, {t['file_count']} files)"
            )

        if run.get("loop_groups"):
            print()
            print("Iteration loops:")
            for lg in run["loop_groups"]:
                cdm = lg.get("combined_duration_min")
                dur_str = f"{cdm} min" if cdm else "unknown"
                print(f"  {lg['label']} ({lg['iterations']} iterations): {dur_str} total")
                for sb in lg.get("step_breakdown", []):
                    sd = sb.get("self_duration_min")
                    sd_str = f"{sd} min" if sd is not None else "n/a"
                    print(f"    {sb['step']}: {sd_str}")
                if lg.get("overhead_s") and lg["overhead_s"] > 5:
                    print(f"    orchestrator overhead: {round(lg['overhead_s'] / 60, 1)} min")
        print()

        print("Recommendations:")
        for i, r in enumerate(run["recommendations"], 1):
            print(f"  {i}. {r}")
        print()


if __name__ == "__main__":
    main()
