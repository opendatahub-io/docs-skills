#!/usr/bin/env python3
"""Diagnostics judges for the eval harness.

Five deterministic judges score workspace artifacts without LLM calls.
One optional LLM reflection judge triggers when any score falls to a
configurable threshold (default ≤3), synthesizing actionable fix
recommendations from the low-scoring areas.

Each judge follows the module judge interface:
    def judge_fn(outputs=None, **arguments) -> tuple[int | None, str]

Also works as a standalone CLI:
    python3 diagnostics_judge.py .agent_workspace/<ticket> [--reflect] [--threshold N]
"""

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

_PD_DIR = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "docs-workflow-pipeline-diagnostics"
    / "scripts"
)
if str(_PD_DIR) not in sys.path:
    sys.path.insert(0, str(_PD_DIR))

import pipeline_diagnostics  # noqa: E402

# ---------------------------------------------------------------------------
# Cache — avoids re-reading artifacts when multiple judges score the same case
# ---------------------------------------------------------------------------

_cache: dict[str, object] = {}


def _cache_key(outputs: dict | None) -> str:
    mods = (outputs or {}).get("modified_files", {})
    for k in mods:
        if "/workflow/" in k and k.endswith(".json"):
            return k
    return id(outputs)


# ---------------------------------------------------------------------------
# Artifact helpers
# ---------------------------------------------------------------------------


def _find_progress_data(outputs: dict | None) -> tuple[dict | None, str | None]:
    """Extract progress dict and base_path from outputs."""
    cache_k = f"progress:{_cache_key(outputs)}"
    if cache_k in _cache:
        return _cache[cache_k]

    mods = (outputs or {}).get("modified_files", {})
    for k, v in mods.items():
        if "/workflow/" in k and k.endswith(".json"):
            try:
                progress = json.loads(v) if isinstance(v, str) else v
            except (json.JSONDecodeError, TypeError):
                continue
            base_path = _resolve_base_path(k, progress)
            result = (progress, base_path)
            _cache[cache_k] = result
            return result

    _cache[cache_k] = (None, None)
    return None, None


def _resolve_base_path(progress_key: str, progress: dict) -> str | None:
    explicit = progress.get("base_path", "")
    if explicit and os.path.isdir(explicit):
        return explicit
    abs_key = os.path.abspath(progress_key)
    workflow_dir = os.path.dirname(abs_key)
    candidate = os.path.dirname(workflow_dir)
    if os.path.basename(workflow_dir) == "workflow" and os.path.isdir(candidate):
        return candidate
    return None


def _read_artifact(outputs: dict | None, relative_path: str) -> dict | None:
    """Read a JSON artifact from modified_files or disk."""
    cache_k = f"artifact:{relative_path}:{_cache_key(outputs)}"
    if cache_k in _cache:
        return _cache[cache_k]

    mods = (outputs or {}).get("modified_files", {})
    for k, v in mods.items():
        if k.endswith(relative_path):
            try:
                result = json.loads(v) if isinstance(v, str) else v
                _cache[cache_k] = result
                return result
            except (json.JSONDecodeError, TypeError):
                pass

    _, base_path = _find_progress_data(outputs)
    if base_path:
        fpath = os.path.join(base_path, relative_path)
        if os.path.isfile(fpath):
            with open(fpath) as f:
                result = json.load(f)
            _cache[cache_k] = result
            return result

    _cache[cache_k] = None
    return None


def _read_step_result(outputs: dict | None, step: str) -> dict | None:
    return _read_artifact(outputs, f"{step}/step-result.json")


# ---------------------------------------------------------------------------
# Judge 1: pipeline_health
# ---------------------------------------------------------------------------


def pipeline_health(outputs=None, **arguments):
    """Score pipeline operational health from the progress file."""
    progress, base_path = _find_progress_data(outputs)
    if progress is None:
        return (None, "No progress file found in outputs")

    step_order = progress.get("step_order", [])
    steps = progress.get("steps", {})
    status = progress.get("status", "unknown")
    bp = base_path or ""

    failures = pipeline_diagnostics.detect_failures(step_order, steps, bp, progress)

    high = [f for f in failures if f["severity"] == "high"]
    medium = [f for f in failures if f["severity"] == "medium"]
    low = [f for f in failures if f["severity"] == "low"]
    stuck = [f for f in failures if f["type"] == "step_stuck"]

    pressure_level = "low"
    cp = None
    if base_path and os.path.isdir(base_path):
        try:
            cp = pipeline_diagnostics.estimate_context_pressure(step_order, steps, bp)
            pressure_level = cp.get("level", "low")
        except Exception:  # noqa: S110
            pass

    all_completed = all(
        steps.get(s, {}).get("status") in ("completed", "skipped") for s in step_order
    )

    parts = []

    if status == "failed" or len(high) >= 2:
        score = 1
    elif len(high) >= 1 or pressure_level in ("high", "critical"):
        score = 2
    elif len(medium) >= 1:
        score = 3
    elif len(low) >= 1 or pressure_level == "moderate" or not all_completed:
        score = 4
    else:
        score = 5

    if stuck:
        parts.append(f"{len(stuck)} stuck step(s)")
    if high:
        parts.append(f"{len(high)} high-severity failure(s)")
    if medium:
        parts.append(f"{len(medium)} medium-severity failure(s)")
    if low:
        parts.append(f"{len(low)} low-severity issue(s)")
    if cp and pressure_level != "low":
        total_tokens = cp.get("total_estimated_tokens", 0)
        window_pct = cp.get("context_window_pct", 0)
        parts.append(
            f"context pressure: {pressure_level} "
            f"(~{total_tokens:,} tokens, {window_pct}% of context window)"
        )
        per_step = cp.get("per_step_estimated_tokens", {})
        heaviest = max(per_step.items(), key=lambda x: x[1], default=None)
        if heaviest and heaviest[1] > 50_000:
            parts.append(f"heaviest step: {heaviest[0]} ~{heaviest[1]:,} tokens")
    if not all_completed:
        parts.append("not all steps completed")
    if not parts:
        parts.append("pipeline healthy")

    return (score, "; ".join(parts))


# ---------------------------------------------------------------------------
# Judge 2: evidence_quality
# ---------------------------------------------------------------------------


def evidence_quality(outputs=None, **arguments):
    """Score evidence grounding and claim verification."""
    evidence = _read_artifact(outputs, "validate/evidence-status.json")
    verdicts = _read_artifact(outputs, "technical-review/claim-verdicts.json")

    if evidence is None and verdicts is None:
        return (None, "No evidence or claim artifacts found")

    parts = []
    score = 5

    if evidence is not None:
        reqs = evidence.get("requirements", [])
        total = len(reqs)
        if total > 0:
            grounded = sum(1 for r in reqs if r.get("status") == "grounded")
            absent = sum(1 for r in reqs if r.get("status") == "absent")
            pct = grounded / total

            parts.append(f"evidence: {grounded}/{total} grounded")
            if absent:
                parts.append(f"{absent} absent")

            if pct < 0.6 or absent > 0:
                score = min(score, 3 if absent == 0 else 2)
            elif pct < 1.0:
                score = min(score, 4)
        else:
            parts.append("evidence: 0 requirements")
            score = min(score, 1)

    if verdicts is not None:
        total_claims = verdicts.get("total_claims", 0)
        verdict_counts = verdicts.get("verdicts", {})
        supported = verdict_counts.get("supported", 0)
        unsupported = verdict_counts.get("unsupported", 0)

        if total_claims > 0:
            pct = supported / total_claims
            parts.append(f"claims: {supported}/{total_claims} supported")
            if unsupported:
                parts.append(f"{unsupported} unsupported")
                score = min(score, 2)
            elif pct < 1.0:
                score = min(score, 4)
        else:
            parts.append("claims: 0 total")

    return (score, "; ".join(parts) if parts else "evidence quality assessed")


# ---------------------------------------------------------------------------
# Judge 3: review_quality
# ---------------------------------------------------------------------------


def review_quality(outputs=None, **arguments):
    """Score technical review severity and security findings."""
    tech_sr = _read_step_result(outputs, "technical-review")
    sec_sr = _read_artifact(outputs, "security-review/scanner-results.json")

    if tech_sr is None and sec_sr is None:
        return (None, "No review artifacts found")

    parts = []
    score = 5

    if tech_sr is not None:
        sev = tech_sr.get("severity_counts", {})
        critical = int(sev.get("critical", 0))
        significant = int(sev.get("significant", 0))
        iteration = int(tech_sr.get("iteration", 1))
        code_grounded = tech_sr.get("code_grounded", None)

        if critical > 1:
            score = min(score, 1)
        elif critical > 0:
            score = min(score, 2)
        elif significant > 0 or iteration > 1:
            score = min(score, 3)

        if code_grounded is False:
            score = min(score, 3)

        finding_parts = []
        for level in ("critical", "significant", "minor", "sme"):
            count = int(sev.get(level, 0))
            if count:
                finding_parts.append(f"{count} {level}")
        if finding_parts:
            parts.append(f"review: {', '.join(finding_parts)}")
        if iteration > 1:
            parts.append(f"{iteration} iterations")
        if code_grounded is False:
            parts.append("not code-grounded")

    if sec_sr is not None:
        by_cat = sec_sr.get("summary", sec_sr).get("by_category", {})
        non_url = {k: v for k, v in by_cat.items() if k != "url" and v > 0}
        if non_url:
            dangerous = {k: v for k, v in non_url.items() if k in ("credential", "ip", "email")}
            if dangerous:
                score = min(score, 2)
                parts.append(f"security: {dangerous}")
            else:
                score = min(score, 3)
                parts.append(f"security warnings: {non_url}")
        total = sec_sr.get("summary", sec_sr).get("total_findings", 0)
        url_count = by_cat.get("url", 0)
        if total and total == url_count:
            parts.append(f"security: {total} URL-only findings (expected)")

    if not parts:
        parts.append("reviews clean")

    return (score, "; ".join(parts))


# ---------------------------------------------------------------------------
# Judge 4: validation_quality
# ---------------------------------------------------------------------------


def validation_quality(outputs=None, **arguments):
    """Score DITA-LS and policy validation results."""
    report = _read_artifact(outputs, "dita-validation/report.json")
    policy = _read_artifact(outputs, "dita-validation/policy-report.json")

    if report is None and policy is None:
        return (None, "No DITA validation artifacts found")

    parts = []
    score = 5
    total_errors = 0
    total_warnings = 0

    if report is not None:
        errors = report.get("error_count", 0)
        warnings = report.get("warning_count", 0)
        status = report.get("status", "unknown")
        total_errors += errors
        total_warnings += warnings
        parts.append(f"dita-ls: {errors}E/{warnings}W ({status})")
        if status == "failed":
            score = min(score, 1)

    if policy is not None:
        errors = policy.get("error_count", 0)
        warnings = policy.get("warning_count", 0)
        total_errors += errors
        total_warnings += warnings
        parts.append(f"policy: {errors}E/{warnings}W")

    if total_errors >= 4:
        score = min(score, 1)
    elif total_errors >= 1:
        score = min(score, 2)
    elif total_warnings > 5:
        score = min(score, 3)
    elif total_warnings > 0:
        score = min(score, 4)

    return (score, "; ".join(parts))


# ---------------------------------------------------------------------------
# Judge 5: planning_fidelity
# ---------------------------------------------------------------------------


def planning_fidelity(outputs=None, **arguments):
    """Score planning-to-output ratio, source coverage, and context growth."""
    plan_sr = _read_step_result(outputs, "planning")
    write_sr = _read_step_result(outputs, "writing")
    discovery = _read_artifact(outputs, "requirements/discovery.json")

    if plan_sr is None and write_sr is None:
        return (None, "No planning/writing step-results found")

    parts = []
    score = 5

    if plan_sr is None or write_sr is None:
        score = min(score, 1)
        missing = "planning" if plan_sr is None else "writing"
        parts.append(f"missing {missing} step-result")
        return (score, "; ".join(parts))

    module_count = plan_sr.get("module_count", 0)
    files = write_sr.get("files", [])
    file_count = len(files) if isinstance(files, list) else 0

    if file_count == 0:
        score = min(score, 2)
        parts.append("0 files produced")
    elif module_count > 0:
        diff = abs(file_count - module_count)
        if diff == 0 or file_count >= module_count:
            parts.append(f"files: {file_count} (planned {module_count})")
        elif diff == 1:
            score = min(score, 4)
            parts.append(f"files: {file_count} vs planned {module_count}")
        else:
            score = min(score, 3)
            parts.append(f"files: {file_count} vs planned {module_count} (gap: {diff})")

    if discovery is not None:
        sources = discovery.get("sources_consulted", {})
        jira_count = len(sources.get("jira_tickets", []))
        pr_count = len(sources.get("pull_requests", []))
        parts.append(f"sources: {jira_count} JIRA, {pr_count} PR")
        if jira_count == 0 and pr_count == 0:
            score = min(score, 2)
        elif pr_count == 0:
            score = min(score, 3)
    else:
        parts.append("no discovery.json")

    progress, base_path = _find_progress_data(outputs)
    if progress:
        step_order = progress.get("step_order", [])
        ctx_sizes = []
        for step in step_order:
            sr = _read_step_result(outputs, step)
            if sr and "context_size_bytes" in sr:
                ctx_sizes.append((step, sr["context_size_bytes"]))
        if len(ctx_sizes) >= 2:
            first_ctx = ctx_sizes[0][1]
            last_ctx = ctx_sizes[-1][1]
            if first_ctx > 0:
                growth = last_ctx / first_ctx
                if growth > 4.0:
                    score = min(score, 3)
                    parts.append(f"context grew {growth:.1f}x")
                elif growth > 2.0:
                    score = min(score, 4)
                    parts.append(f"context grew {growth:.1f}x")

    return (score, "; ".join(parts))


# ---------------------------------------------------------------------------
# Aggregate helper
# ---------------------------------------------------------------------------

DETERMINISTIC_JUDGES = [
    ("pipeline_health", pipeline_health),
    ("evidence_quality", evidence_quality),
    ("review_quality", review_quality),
    ("validation_quality", validation_quality),
    ("planning_fidelity", planning_fidelity),
]


def _run_all_deterministic(outputs=None, **arguments):
    """Run all deterministic judges and return results dict."""
    results = {}
    for name, fn in DETERMINISTIC_JUDGES:
        results[name] = fn(outputs, **arguments)
    return results


# ---------------------------------------------------------------------------
# Judge 6: diagnostics_reflection (LLM, conditional)
# ---------------------------------------------------------------------------

REFLECTION_PROMPT = """You are analyzing pipeline diagnostics for a docs-orchestrator run.
Several deterministic quality checks scored below the threshold, indicating issues
that need attention. Your job is to:

1. Identify the root causes behind the low scores
2. Recommend specific, actionable fixes — name files, steps, and concrete changes
3. Prioritize fixes by impact (what would most improve the next run)

## Low-scoring diagnostics

{diagnostics_summary}

## Relevant artifacts

{artifact_excerpts}

## Instructions

Return a JSON object with:
- "score": 1-5 integer (5=easy fixes, 3=moderate rework, 1=fundamental issues)
- "rationale": string with prioritized fix recommendations
"""


def _build_reflection_context(
    results: dict, outputs: dict | None, threshold: int
) -> tuple[str, str]:
    """Build the prompt context from low-scoring judge results."""
    diag_parts = []
    artifact_parts = []

    for name, (score, rationale) in results.items():
        if score is not None and score <= threshold:
            diag_parts.append(f"**{name}** (score: {score}/5): {rationale}")

            if name == "evidence_quality":
                ev = _read_artifact(outputs, "validate/evidence-status.json")
                if ev:
                    reqs = ev.get("requirements", [])
                    problem_reqs = [r for r in reqs if r.get("status") != "grounded"]
                    if problem_reqs:
                        artifact_parts.append(
                            f"### Evidence gaps\n```json\n"
                            f"{json.dumps(problem_reqs[:5], indent=2)}\n```"
                        )

            elif name == "review_quality":
                sec = _read_artifact(outputs, "security-review/scanner-results.json")
                if sec:
                    findings = sec.get("findings", [])
                    non_url = [f for f in findings if f.get("category") != "url"]
                    if non_url:
                        artifact_parts.append(
                            f"### Security findings\n```json\n"
                            f"{json.dumps(non_url[:5], indent=2)}\n```"
                        )

            elif name == "validation_quality":
                report = _read_artifact(outputs, "dita-validation/report.json")
                if report:
                    diags = report.get("diagnostics", [])
                    errors = [d for d in diags if d.get("severity") == "error"]
                    if errors:
                        artifact_parts.append(
                            f"### Validation errors\n```json\n"
                            f"{json.dumps(errors[:10], indent=2)}\n```"
                        )

            elif name == "pipeline_health":
                progress, base_path = _find_progress_data(outputs)
                if progress:
                    step_order = progress.get("step_order", [])
                    steps = progress.get("steps", {})
                    failures = pipeline_diagnostics.detect_failures(
                        step_order, steps, base_path or "", progress
                    )
                    high = [f for f in failures if f["severity"] == "high"]
                    if high:
                        artifact_parts.append(
                            f"### High-severity failures\n```json\n"
                            f"{json.dumps(high[:5], indent=2)}\n```"
                        )

    return "\n\n".join(diag_parts), "\n\n".join(artifact_parts) or "No additional artifacts."


def diagnostics_reflection(outputs=None, **arguments):
    """LLM reflection on low-scoring diagnostics."""
    threshold = arguments.get("threshold", 3)
    results = _run_all_deterministic(outputs, **arguments)

    scored = {k: v for k, v in results.items() if v[0] is not None}
    if not scored:
        return (None, "No deterministic judges produced scores")

    low_scores = {k: v for k, v in scored.items() if v[0] <= threshold}
    if not low_scores:
        return (5, "All diagnostics healthy — no issues warrant deeper analysis")

    diag_summary, artifact_excerpts = _build_reflection_context(low_scores, outputs, threshold)
    prompt = REFLECTION_PROMPT.format(
        diagnostics_summary=diag_summary,
        artifact_excerpts=artifact_excerpts,
    )

    model = arguments.get("model", None)
    try:
        return _call_llm(prompt, model)
    except Exception as e:
        return (None, f"LLM reflection failed: {e}")


def _call_llm(prompt: str, model: str | None = None):
    """Call the Anthropic API to score and explain."""
    import anthropic

    if os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID"):
        client = anthropic.AnthropicVertex(
            project_id=os.environ["ANTHROPIC_VERTEX_PROJECT_ID"],
            region=os.environ.get("CLOUD_ML_REGION", "us-east5"),
        )
    elif os.environ.get("GOOGLE_CLOUD_PROJECT"):
        client = anthropic.AnthropicVertex(
            project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
            region=os.environ.get("CLOUD_ML_REGION", "us-east5"),
        )
    else:
        client = anthropic.Anthropic()

    model = model or os.environ.get("EVAL_JUDGE_MODEL", "claude-opus-4-6")

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=(
            "You are a pipeline diagnostics analyst. "
            'Respond with JSON: {"score": <1-5>, "rationale": "<explanation>"}'
        ),
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text
    try:
        data = json.loads(text)
        return data.get("score", 3), data.get("rationale", "")
    except json.JSONDecodeError:
        import re

        score_match = re.search(r'"score"\s*:\s*(\d)', text)
        if score_match:
            return int(score_match.group(1)), text[:500]
        return 3, f"Could not parse response: {text[:500]}"


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------


def _build_cli_outputs(workspace_path: str) -> dict:
    """Build an outputs dict from a workspace directory on disk."""
    workspace_path = os.path.abspath(workspace_path)

    progress_files = []
    workflow_dir = os.path.join(workspace_path, "workflow")
    if os.path.isdir(workflow_dir):
        for f in os.listdir(workflow_dir):
            if f.endswith(".json") and not f.endswith(".stop_count"):
                progress_files.append(os.path.join(workflow_dir, f))

    if not progress_files:
        return {}

    modified_files = {}

    for root, _dirs, files in os.walk(workspace_path):
        for fname in files:
            if fname.endswith(".json") or fname.endswith(".md"):
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, os.path.dirname(workspace_path))
                try:
                    with open(fpath) as fh:
                        modified_files[rel] = fh.read()
                except (OSError, UnicodeDecodeError):
                    pass

    return {"modified_files": modified_files, "case_dir": workspace_path}


# ---------------------------------------------------------------------------
# Architect mode — cross-workspace aggregation
# ---------------------------------------------------------------------------


def _discover_workspaces(path: str) -> list[dict]:
    """Auto-detect path type and return workspace entries.

    Supports three layouts:
    - Eval run dir: cases/<case>/_modified/.agent_workspace/<ticket>/
    - Workspace dir: <ticket>/ children with workflow/ subdirs
    - Single workspace: has workflow/ directly
    """
    path = os.path.abspath(path)
    results = []

    # Check for single workspace (has workflow/ directly)
    if os.path.isdir(os.path.join(path, "workflow")):
        return [{"workspace_path": path, "label": os.path.basename(path), "source": "single"}]

    # Check for eval run dir (has cases/ with _modified/ children)
    cases_dir = os.path.join(path, "cases")
    if os.path.isdir(cases_dir):
        for case_name in sorted(os.listdir(cases_dir)):
            case_path = os.path.join(cases_dir, case_name)
            if not os.path.isdir(case_path):
                continue
            modified = os.path.join(case_path, "_modified", ".agent_workspace")
            if not os.path.isdir(modified):
                continue
            for ticket in sorted(os.listdir(modified)):
                ws = os.path.join(modified, ticket)
                if os.path.isdir(os.path.join(ws, "workflow")):
                    results.append({"workspace_path": ws, "label": case_name, "source": "eval_run"})
        if results:
            return results

    # Workspace directory: children with workflow/ subdirs
    for entry in sorted(os.listdir(path)):
        child = os.path.join(path, entry)
        if os.path.isdir(os.path.join(child, "workflow")):
            results.append({"workspace_path": child, "label": entry, "source": "workspace_dir"})

    return results


def _collect_workspace_data(workspace: dict) -> dict | None:
    """Run diagnostics on a single workspace and return structured data."""
    global _cache
    _cache.clear()

    ws_path = workspace["workspace_path"]
    outputs = _build_cli_outputs(ws_path)
    if not outputs:
        return None

    results = _run_all_deterministic(outputs)

    progress, base_path = _find_progress_data(outputs)
    step_order = progress.get("step_order", []) if progress else []
    steps = progress.get("steps", {}) if progress else {}

    context_pressure = None
    if base_path and os.path.isdir(base_path):
        try:
            context_pressure = pipeline_diagnostics.estimate_context_pressure(
                step_order, steps, base_path
            )
        except Exception:  # noqa: S110
            pass

    return {
        "label": workspace["label"],
        "workspace_path": ws_path,
        "source": workspace["source"],
        "scores": {name: score for name, (score, _) in results.items()},
        "rationales": {name: rationale for name, (_, rationale) in results.items()},
        "step_order": step_order,
        "context_pressure": context_pressure,
    }


def _compute_score_stats(all_data: list[dict]) -> dict:
    """Compute per-judge score statistics across workspaces."""
    judge_names = [name for name, _ in DETERMINISTIC_JUDGES]
    stats = {}

    for judge in judge_names:
        scores = [d["scores"][judge] for d in all_data if d["scores"].get(judge) is not None]
        if not scores:
            stats[judge] = {"count": 0}
            continue

        failure_count = sum(1 for s in scores if s <= 2)
        concern_count = sum(1 for s in scores if s <= 3)
        low_findings = [
            {"label": d["label"], "score": d["scores"][judge], "rationale": d["rationales"][judge]}
            for d in all_data
            if d["scores"].get(judge) is not None and d["scores"][judge] <= 3
        ]

        stats[judge] = {
            "count": len(scores),
            "mean": round(statistics.mean(scores), 2),
            "median": statistics.median(scores),
            "min": min(scores),
            "max": max(scores),
            "stdev": round(statistics.stdev(scores), 2) if len(scores) > 1 else 0,
            "failure_rate": round(failure_count / len(scores), 2),
            "concern_rate": round(concern_count / len(scores), 2),
            "low_findings": low_findings,
        }

    return stats


def _compute_context_stats(all_data: list[dict]) -> dict:
    """Aggregate context pressure statistics across workspaces."""
    pressures = [d["context_pressure"] for d in all_data if d.get("context_pressure")]
    if not pressures:
        return {}

    totals = [p.get("total_estimated_tokens", 0) for p in pressures]
    window_pcts = [p.get("context_window_pct", 0) for p in pressures]
    risk_scores = [p.get("risk_score", 0) for p in pressures]
    levels = [p.get("level", "unknown") for p in pressures]

    level_dist = {}
    for lv in levels:
        level_dist[lv] = level_dist.get(lv, 0) + 1

    # Per-step averages
    step_totals: dict[str, list[int]] = {}
    for p in pressures:
        for step, tokens in p.get("per_step_estimated_tokens", {}).items():
            step_totals.setdefault(step, []).append(tokens)

    per_step_means = {
        step: round(statistics.mean(vals)) for step, vals in sorted(step_totals.items())
    }

    return {
        "count": len(pressures),
        "total_tokens": {
            "mean": round(statistics.mean(totals)),
            "max": max(totals),
            "min": min(totals),
        },
        "window_pct": {
            "mean": round(statistics.mean(window_pcts)),
            "max": max(window_pcts),
            "min": min(window_pcts),
        },
        "risk_score": {
            "mean": round(statistics.mean(risk_scores), 1),
        },
        "level_distribution": level_dist,
        "per_step_mean_tokens": per_step_means,
    }


def _detect_systemic_patterns(
    score_stats: dict, context_stats: dict, all_data: list[dict]
) -> list[dict]:
    """Detect systemic patterns across workspaces."""
    patterns = []

    for judge, st in score_stats.items():
        if st.get("count", 0) == 0:
            continue
        if st.get("failure_rate", 0) > 0.5:
            patterns.append(
                {
                    "type": "consistently_failing",
                    "severity": "high",
                    "judge": judge,
                    "detail": (
                        f"{judge} fails (score ≤2) in {st['failure_rate'] * 100:.0f}% of runs"
                    ),
                }
            )
        elif st.get("concern_rate", 0) > 0.5:
            patterns.append(
                {
                    "type": "consistently_concerning",
                    "severity": "medium",
                    "judge": judge,
                    "detail": (f"{judge} scores ≤3 in {st['concern_rate'] * 100:.0f}% of runs"),
                }
            )

    if context_stats:
        mean_risk = context_stats.get("risk_score", {}).get("mean", 0)
        if mean_risk >= 6:
            patterns.append(
                {
                    "type": "systemic_context_pressure",
                    "severity": "high",
                    "detail": f"mean risk score {mean_risk}/10 across runs",
                }
            )

        mean_window = context_stats.get("window_pct", {}).get("mean", 0)
        if mean_window >= 75:
            patterns.append(
                {
                    "type": "context_window_saturation",
                    "severity": "high",
                    "detail": f"mean context window usage {mean_window}%",
                }
            )

        for step, tokens in context_stats.get("per_step_mean_tokens", {}).items():
            if tokens > 50_000:
                patterns.append(
                    {
                        "type": "heavy_step",
                        "severity": "medium",
                        "step": step,
                        "detail": f"{step} averages ~{tokens:,} tokens",
                    }
                )

    return patterns


def _build_diagnose_output(all_data: list[dict]) -> dict:
    """Build structured output for diagnose mode."""
    score_stats = _compute_score_stats(all_data)
    context_stats = _compute_context_stats(all_data)
    patterns = _detect_systemic_patterns(score_stats, context_stats, all_data)

    all_scores = []
    for d in all_data:
        for s in d["scores"].values():
            if s is not None:
                all_scores.append(s)

    return {
        "mode": "diagnose",
        "workspace_count": len(all_data),
        "overall_mean": round(statistics.mean(all_scores), 2) if all_scores else None,
        "score_stats": score_stats,
        "context_stats": context_stats,
        "systemic_patterns": patterns,
        "workspaces": [
            {
                "label": d["label"],
                "scores": d["scores"],
                "step_order": d["step_order"],
            }
            for d in all_data
        ],
    }


def _build_compare_output(paths: list[str]) -> dict:
    """Build structured output for compare mode, grouping by architecture variant."""
    variants: dict[str, list[dict]] = {}

    for path in paths:
        workspaces = _discover_workspaces(path)
        for ws in workspaces:
            data = _collect_workspace_data(ws)
            if data is None:
                continue
            key = ",".join(data["step_order"]) if data["step_order"] else "unknown"
            variants.setdefault(key, []).append(data)

    variant_results = {}
    for key, data_list in variants.items():
        steps = data_list[0]["step_order"] if data_list else []
        variant_results[key] = {
            "step_order": steps,
            "step_count": len(steps),
            "workspace_count": len(data_list),
            "score_stats": _compute_score_stats(data_list),
            "context_stats": _compute_context_stats(data_list),
        }

    # Build delta table if exactly 2 variants
    delta = None
    variant_keys = list(variant_results.keys())
    if len(variant_keys) == 2:
        a_stats = variant_results[variant_keys[0]]["score_stats"]
        b_stats = variant_results[variant_keys[1]]["score_stats"]
        delta = {}
        for judge in [name for name, _ in DETERMINISTIC_JUDGES]:
            a_mean = a_stats.get(judge, {}).get("mean")
            b_mean = b_stats.get(judge, {}).get("mean")
            if a_mean is not None and b_mean is not None:
                delta[judge] = round(b_mean - a_mean, 2)

    return {
        "mode": "compare",
        "variant_count": len(variant_results),
        "variants": variant_results,
        "delta": delta,
    }


def _format_architect_text(output: dict) -> str:
    """Render architect output as human-readable text."""
    lines = []
    mode = output.get("mode", "diagnose")

    if mode == "diagnose":
        lines.append(f"\nArchitect Diagnostics — {output['workspace_count']} workspaces")
        lines.append("=" * 60)

        overall = output.get("overall_mean")
        if overall is not None:
            lines.append(f"  Overall mean: {overall}/5")
        lines.append("")

        # Score distribution table
        lines.append("  Score distribution:")
        lines.append(f"  {'Judge':<25} {'Mean':>5} {'Med':>5} {'Min':>4} {'Max':>4} {'Fail%':>6}")
        lines.append(f"  {'-' * 25} {'-' * 5} {'-' * 5} {'-' * 4} {'-' * 4} {'-' * 6}")
        for judge, st in output.get("score_stats", {}).items():
            if st.get("count", 0) == 0:
                continue
            lines.append(
                f"  {judge:<25} {st['mean']:>5.1f} {st['median']:>5.1f}"
                f" {st['min']:>4} {st['max']:>4}"
                f" {st['failure_rate'] * 100:>5.0f}%"
            )
        lines.append("")

        # Context pressure
        ctx = output.get("context_stats", {})
        if ctx:
            tok = ctx.get("total_tokens", {})
            win = ctx.get("window_pct", {})
            lines.append("  Context pressure:")
            lines.append(
                f"    Tokens: mean ~{tok.get('mean', 0):,}"
                f", max ~{tok.get('max', 0):,}"
                f", min ~{tok.get('min', 0):,}"
            )
            lines.append(
                f"    Window: mean {win.get('mean', 0)}%"
                f", max {win.get('max', 0)}%"
                f", min {win.get('min', 0)}%"
            )
            dist = ctx.get("level_distribution", {})
            if dist:
                dist_str = ", ".join(f"{lv}: {n}" for lv, n in sorted(dist.items()))
                lines.append(f"    Levels: {dist_str}")

            per_step = ctx.get("per_step_mean_tokens", {})
            heavy = {s: t for s, t in per_step.items() if t > 50_000}
            if heavy:
                lines.append("    Heavy steps:")
                for step, tokens in sorted(heavy.items(), key=lambda x: -x[1]):
                    lines.append(f"      {step}: ~{tokens:,} tokens")
            lines.append("")

        # Systemic patterns
        patterns = output.get("systemic_patterns", [])
        if patterns:
            lines.append("  Systemic patterns:")
            for p in patterns:
                sev = p.get("severity", "?").upper()
                lines.append(f"    [{sev}] {p['detail']}")
            lines.append("")

        # Low-scoring findings
        for judge, st in output.get("score_stats", {}).items():
            findings = st.get("low_findings", [])
            if findings:
                lines.append(f"  Low scores — {judge}:")
                for f in findings:
                    lines.append(f"    {f['label']}: {f['score']}/5 — {f['rationale']}")
                lines.append("")

    elif mode == "compare":
        lines.append(f"\nArchitect Compare — {output['variant_count']} variant(s)")
        lines.append("=" * 60)

        for i, (_key, variant) in enumerate(output.get("variants", {}).items()):
            label = f"Variant {i + 1}"
            lines.append(
                f"\n  {label} ({variant['step_count']} steps, {variant['workspace_count']} runs):"
            )
            lines.append(f"    Steps: {', '.join(variant['step_order'])}")
            lines.append(f"    {'Judge':<25} {'Mean':>5} {'Med':>5} {'Fail%':>6}")
            for judge, st in variant.get("score_stats", {}).items():
                if st.get("count", 0) == 0:
                    continue
                lines.append(
                    f"    {judge:<25} {st['mean']:>5.1f}"
                    f" {st['median']:>5.1f}"
                    f" {st['failure_rate'] * 100:>5.0f}%"
                )

        delta = output.get("delta")
        if delta:
            lines.append("\n  Delta (variant 2 - variant 1):")
            for judge, d in delta.items():
                sign = "+" if d > 0 else ""
                lines.append(f"    {judge:<25} {sign}{d:.2f}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run diagnostics judges against a workspace")
    parser.add_argument(
        "workspace",
        nargs="?",
        help="Path to .agent_workspace/<ticket> directory",
    )
    parser.add_argument(
        "--architect",
        nargs="+",
        metavar="PATH",
        help=(
            "Aggregate diagnostics across workspaces"
            " (eval run dir, workspace dir, or single workspace)"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["diagnose", "compare"],
        default="diagnose",
        help="Architect submode: diagnose (same arch) or compare (different archs)",
    )
    parser.add_argument(
        "--reflect",
        action="store_true",
        help="Run LLM reflection on low scores",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=3,
        help="Score threshold for LLM reflection (default: 3)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    if not args.workspace and not args.architect:
        parser.error("either workspace or --architect is required")

    # --- Architect mode ---
    if args.architect:
        if args.mode == "compare":
            output = _build_compare_output(args.architect)
        else:
            all_data = []
            for path in args.architect:
                workspaces = _discover_workspaces(path)
                for ws in workspaces:
                    data = _collect_workspace_data(ws)
                    if data is not None:
                        all_data.append(data)

            if not all_data:
                print(json.dumps({"error": "No valid workspaces found"}))
                sys.exit(1)

            output = _build_diagnose_output(all_data)

        if args.format == "json":
            print(json.dumps(output, indent=2))
        else:
            print(_format_architect_text(output))
        return

    # --- Single workspace mode ---
    outputs = _build_cli_outputs(args.workspace)
    if not outputs:
        print(json.dumps({"error": f"No workflow files found in {args.workspace}"}))
        sys.exit(1)

    results = _run_all_deterministic(outputs)

    if args.reflect:
        results["diagnostics_reflection"] = diagnostics_reflection(
            outputs, threshold=args.threshold
        )

    if args.format == "json":
        json_results = {}
        for name, (score, rationale) in results.items():
            json_results[name] = {"score": score, "rationale": rationale}
        print(json.dumps(json_results, indent=2))
    else:
        print(f"\nDiagnostics: {args.workspace}")
        print("=" * 60)
        for name, (score, rationale) in results.items():
            label = "SKIP" if score is None else f"{score}/5"
            print(f"  {name:.<30} {label:>6}  {rationale}")
        print()

        scored = [s for s, _ in results.values() if s is not None]
        if scored:
            avg = sum(scored) / len(scored)
            print(f"  Average: {avg:.1f}/5 ({len(scored)} judges)")
        print()


if __name__ == "__main__":
    main()
