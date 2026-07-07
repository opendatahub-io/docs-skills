#!/usr/bin/env python3
"""Docs orchestrator state machine driver.

Owns all deterministic workflow logic: progress file management, step
sequencing, argument construction, post-processing, tech review iteration.
The LLM becomes a thin executor: call init, run the skill it says, call
step-done, repeat.

Subcommands:
    init       Parse args, resolve source, create/resume progress, return first action.
    step-done  Record completion, run post-processing, return next action.
    next       Read-only query for the next action (recovery/debugging).
    status     Read-only query of current workflow state.

Exit codes:
    0 — success (JSON action on stdout)
    1 — error (JSON with error/message fields on stdout)
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

RESOLVE_SOURCE_SCRIPT = str(
    Path(__file__).resolve().parent.parent
    / "skills"
    / "docs-orchestrator"
    / "scripts"
    / "resolve_source.py"
)

DEFAULT_WORKFLOW_DIR = str(
    Path(__file__).resolve().parent.parent / "skills" / "docs-orchestrator" / "defaults"
)

PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)

# Steps whose SKILL.md is heavy enough to warrant main-loop agent dispatch via
# `prepare-step` instead of the Skill tool. A step is listed here only once its
# per-step prepare function exists in the PREPARE_STEPS dispatch table.
DISPATCH_STEPS = {"writing"}

VALID_WHEN_CONDITIONS = {
    "has_source_repo",
    "has_pr",
    "create_merge_request",
    "create_jira",
    "has_many_requirements",
}

TICKET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]+-\d+$")

# Workflow name comes from the --workflow CLI arg and is interpolated into a
# filename (docs-<name>.yaml). Restrict it to prevent path traversal.
WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_ticket(ticket):
    if not TICKET_RE.fullmatch(ticket):
        emit({"action": "fail", "error": True, "message": f"Invalid ticket format: {ticket}"})
        sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path, data):
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def git_root():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S603, S607
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return os.getcwd()


def emit(data):
    json.dump(data, sys.stdout, indent=2)
    print()


# ---------------------------------------------------------------------------
# YAML parser (adapted from resolve_steps.py)
# ---------------------------------------------------------------------------


def parse_workflow_yaml(path):
    """Parse the constrained workflow YAML format.

    Returns (workflow_name, workflow_description, steps_list, requires_list).
    """
    with open(path) as f:
        lines = f.readlines()

    workflow_name = "docs-workflow"
    workflow_description = ""
    steps = []
    requires = []
    current = None
    in_requires_block = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- name:"):
            in_requires_block = False
            if current:
                steps.append(current)
            current = {
                "name": stripped.split(":", 1)[1].strip(),
                "skill": None,
                "description": "",
                "when": None,
                "inputs": [],
            }
            continue

        if current is None:
            if in_requires_block and stripped.startswith("- "):
                requires.append(stripped[2:].strip())
                continue

            if ":" in stripped:
                key, value = stripped.split(":", 1)
                key = key.strip()
                value = value.strip()
                if key == "name":
                    workflow_name = value
                elif key == "description":
                    workflow_description = value
                elif key == "requires":
                    in_requires_block = True
                    match = re.match(r"\[(.*)\]", value)
                    if match:
                        requires = [s.strip() for s in match.group(1).split(",") if s.strip()]
                        in_requires_block = False
                else:
                    in_requires_block = False
            continue

        if ":" in stripped and not stripped.startswith("-"):
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()

            if key == "inputs":
                match = re.match(r"\[(.*)\]", value)
                if match:
                    current["inputs"] = [s.strip() for s in match.group(1).split(",") if s.strip()]
            elif key in ("skill", "description", "when"):
                current[key] = value
            elif key == "name" and current.get("name") is None:
                current["name"] = value

    if current:
        steps.append(current)

    return workflow_name, workflow_description, steps, requires


def validate_steps(steps):
    """Validate step list: unique names, valid skill refs, valid inputs."""
    errors = []
    names = set()
    step_map = {s["name"]: s for s in steps}

    for step in steps:
        if step["name"] in names:
            errors.append(f"Duplicate step name: '{step['name']}'")
        names.add(step["name"])

        if not step.get("skill"):
            errors.append(f"Step '{step['name']}' has no skill reference")

        for dep in step.get("inputs", []):
            if dep not in step_map:
                errors.append(f"Step '{step['name']}' references unknown input '{dep}'")

    return errors


# ---------------------------------------------------------------------------
# Progress file I/O
# ---------------------------------------------------------------------------


def progress_path(base_path, workflow_name, ticket_lower):
    return os.path.join(base_path, "workflow", f"{workflow_name}_{ticket_lower}.json")


def read_progress(path):
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def write_progress(path, data):
    data["updated_at"] = iso_now()
    atomic_write_json(path, data)


def create_progress(ticket, workflow_name, base_path, options, steps, step_order):
    return {
        "workflow": workflow_name,
        "ticket": ticket,
        "base_path": os.path.abspath(base_path),
        "status": "in_progress",
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "options": options,
        "step_order": step_order,
        "steps": {s["name"]: {"status": "pending", "output": None, "result": None} for s in steps},
    }


def marker_path_for(base_path):
    workspace = os.path.dirname(base_path)
    return os.path.join(workspace, ".active-workflow")


def write_active_marker(base_path, ticket, workflow_name, progress_file_rel):
    marker = marker_path_for(base_path)
    atomic_write_json(
        marker,
        {
            "ticket": ticket,
            "workflow": workflow_name,
            "progress_file": progress_file_rel,
        },
    )


def delete_active_marker(base_path):
    marker = marker_path_for(base_path)
    try:
        os.unlink(marker)
    except FileNotFoundError:
        pass


def delete_stop_counter(pfile):
    counter = pfile + ".stop_count"
    try:
        os.unlink(counter)
    except FileNotFoundError:
        pass


def resolve_progress_file(base_path, root):
    """Resolve progress file using .active-workflow marker, falling back to directory scan."""
    marker = marker_path_for(base_path)
    if os.path.isfile(marker):
        try:
            with open(marker) as f:
                data = json.load(f)
            pfile = os.path.join(root, data["progress_file"])
            if os.path.isfile(pfile):
                return pfile
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    workflow_dir = os.path.join(base_path, "workflow")
    if not os.path.isdir(workflow_dir):
        return None
    pfiles = sorted(
        f for f in os.listdir(workflow_dir) if f.endswith(".json") and not f.endswith(".stop_count")
    )
    return os.path.join(workflow_dir, pfiles[0]) if pfiles else None


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def call_resolve_source(
    base_path,
    repos=None,
    pr_urls=None,
    progress_file=None,
    scan_requirements=False,
    skip_deferred=False,
):
    """Call resolve_source.py as subprocess. Returns (exit_code, result_dict)."""
    cmd = ["python3", RESOLVE_SOURCE_SCRIPT, "--base-path", str(base_path)]
    if repos:
        cmd += ["--repo"] + list(repos)
    if pr_urls:
        cmd += ["--pr"] + list(pr_urls)
    if progress_file:
        cmd += ["--progress-file", str(progress_file)]
    if scan_requirements:
        cmd.append("--scan-requirements")
    if skip_deferred:
        cmd.append("--skip-deferred-on-no-source")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)  # noqa: S603
    except subprocess.TimeoutExpired:
        return 1, {"status": "error", "message": "resolve_source.py timed out"}

    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {
            "status": "error",
            "message": f"Invalid JSON from resolve_source.py: {result.stdout[:200]}",
        }
        return 1, data

    return result.returncode, data


def resolve_source_post_requirements(base_path, pfile, progress, options):
    """Resolve source repos after the requirements step completes.

    Call only after the completed requirements state has been persisted to
    ``pfile``: resolve_source.py reads and rewrites the whole progress file, so
    a stale on-disk state would be pulled back in.

    On success, resolve_source.py sets ``options.source`` and flips deferred
    source-dependent steps to pending (or to skipped, with skip_deferred, when
    no source is found). Re-read the progress file and update ``progress`` and
    ``options`` in place so callers holding references see the change.
    Idempotent via a ``.source-resolved`` stamp. Returns a list of messages.
    """
    messages = []
    if options.get("source") or options.get("no_source_repo"):
        return messages

    stamp = os.path.join(base_path, "requirements", ".source-resolved")
    if os.path.isfile(stamp):
        return messages

    exit_code, result = call_resolve_source(
        base_path,
        progress_file=pfile,
        scan_requirements=True,
        skip_deferred=True,
    )

    if exit_code == 0 and result.get("status") == "resolved":
        _rehydrate_progress(pfile, progress, options)
        messages.append(f"Source resolved: {result.get('repo_path', '?')}")
    elif exit_code == 2:
        # no_source: resolve_source flipped deferred steps to skipped on disk.
        _rehydrate_progress(pfile, progress, options)
        messages.append("No source repo discovered — source-dependent steps skipped")
    else:
        # Hard error (exit 1): leave the stamp unset so a resume can retry.
        return messages

    try:
        Path(stamp).touch()
    except OSError:
        pass
    return messages


def _rehydrate_progress(pfile, progress, options):
    """Re-read pfile and refresh progress/options in place.

    Replace the in-memory dicts' contents while preserving the caller's object
    identities (callers may hold separate references to progress and options),
    and keep progress["options"] aliased to the same options object.
    """
    updated = read_progress(pfile)
    if not updated:
        return
    progress.clear()
    progress.update(updated)
    options.clear()
    options.update(updated.get("options", {}))
    progress["options"] = options


# ---------------------------------------------------------------------------
# When-condition evaluator
# ---------------------------------------------------------------------------


def evaluate_when(condition, options):
    """Evaluate a when condition. Returns True/False/None (None = deferred)."""
    if condition is None:
        return True

    if condition == "create_merge_request":
        return options.get("create_merge_request", False)

    if condition == "create_jira":
        return bool(options.get("create_jira"))

    if condition == "has_pr":
        return bool(options.get("pr_urls"))

    if condition == "has_source_repo":
        if options.get("no_source_repo"):
            return False
        if options.get("source"):
            return True
        return None  # deferred

    if condition == "has_many_requirements":
        return None  # always deferred; evaluated in post-processing

    return False


def classify_step(step, options):
    """Returns initial status: 'pending', 'skipped', or 'deferred'."""
    result = evaluate_when(step.get("when"), options)
    if result is True:
        return "pending"
    elif result is False:
        return "skipped"
    else:
        return "deferred"


# ---------------------------------------------------------------------------
# Step args builder
# ---------------------------------------------------------------------------


def build_step_args(step_name, ticket, base_path, options, progress=None):
    """Build the CLI args string for invoking a step skill."""
    source = options.get("source") or {}
    repo_path = source.get("repo_path")
    additional = options.get("additional_sources") or []
    pr_urls = options.get("pr_urls") or []
    fmt = options.get("format", "adoc")
    draft = options.get("draft", False)
    docs_repo = options.get("docs_repo_path")

    if step_name == "code-analysis":
        output_dir = os.path.join(base_path, "code-analysis")
        parts = [f"--repo {repo_path}", f"--ticket {ticket}", f"--output-dir {output_dir}"]
        return " ".join(parts)

    if step_name.startswith("code-analysis-"):
        repo_name = step_name[len("code-analysis-") :]
        add_repo = _find_additional_repo(additional, repo_name)
        output_dir = os.path.join(base_path, step_name)
        parts = []
        if add_repo:
            parts.append(f"--repo {add_repo['repo_path']}")
        parts += [f"--ticket {ticket}", f"--output-dir {output_dir}"]
        return " ".join(parts)

    if step_name == "pr-analysis":
        first_pr = pr_urls[0] if pr_urls else ""
        output_dir = os.path.join(base_path, "pr-analysis")
        parts = [f"--pr {first_pr}", f"--ticket {ticket}", f"--output-dir {output_dir}"]
        if repo_path:
            parts.insert(1, f"--repo {repo_path}")
        else:
            return None  # pr-analysis requires --repo
        return " ".join(parts)

    parts = [ticket, f"--base-path {base_path}"]

    if step_name == "requirements":
        for url in pr_urls:
            parts.append(f"--pr {url}")
        if repo_path:
            parts.append(f"--repo {repo_path}")

    elif step_name == "scope-req-audit":
        if repo_path:
            parts.append(f"--repo {repo_path}")

    elif step_name == "writing":
        parts.append(f"--format {fmt}")
        if draft:
            parts.append("--draft")
        if repo_path:
            parts.append(f"--repo {repo_path}")
        for src in additional:
            rp = src.get("repo_path", "")
            if rp:
                parts.append(f"--repo {rp}")
        if docs_repo:
            parts.append(f"--repo-path {docs_repo}")

        if progress:
            fix_from = progress.get("_tech_review_fix_from")
            if not fix_from:
                fix_from = progress.get("_quality_gate_fix_from")
            if fix_from:
                parts.append(f"--fix-from {fix_from}")

    elif step_name == "technical-review":
        if repo_path:
            parts.append(f"--repo {repo_path}")
        for src in additional:
            rp = src.get("repo_path", "")
            if rp:
                parts.append(f"--repo {rp}")
        iteration = (progress or {}).get("_tech_review_iteration", 1)
        parts.append(f"--iteration {iteration}")

    elif step_name == "style-review":
        parts.append(f"--format {fmt}")

    elif step_name == "security-review":
        pass

    elif step_name == "quality-gate":
        iteration = (progress or {}).get("_quality_gate_iteration", 1)
        if iteration > 1:
            parts.append(f"--iteration {iteration}")

    elif step_name == "pipeline-diagnostics":
        ci_log = options.get("ci_log")
        if ci_log:
            parts.append(f"--ci-log {ci_log}")

    elif step_name == "create-merge-request":
        if draft:
            parts.append("--draft")
        if docs_repo:
            parts.append(f"--repo-path {docs_repo}")

    elif step_name == "create-jira":
        project = options.get("create_jira", "")
        parts.append(f"--project {project}")

    return " ".join(parts)


def _find_additional_repo(additional, repo_name):
    for entry in additional:
        path = entry.get("repo_path", "")
        if os.path.basename(path) == repo_name:
            return entry
    return None


# ---------------------------------------------------------------------------
# Post-processing per step
# ---------------------------------------------------------------------------


def read_sidecar(base_path, step_name):
    """Read step-result.json sidecar. Returns dict or None."""
    sidecar = os.path.join(base_path, step_name, "step-result.json")
    if not os.path.isfile(sidecar):
        return None
    try:
        with open(sidecar) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def post_process(step_name, progress, base_path, options):
    """Run step-specific post-processing.

    Returns dict with warnings and optional action_override.
    """
    warnings = []
    messages = []

    sidecar = read_sidecar(base_path, step_name)
    if sidecar:
        progress["steps"][step_name]["result"] = sidecar
    else:
        warnings.append(f"No step-result.json sidecar found for {step_name}")

    handler = _POST_PROCESSORS.get(step_name)
    if handler:
        result = handler(sidecar, progress, base_path, options)
        warnings.extend(result.get("warnings", []))
        messages.extend(result.get("messages", []))
        if "action_override" in result:
            return {
                "warnings": warnings,
                "messages": messages,
                "action_override": result["action_override"],
            }

    return {"warnings": warnings, "messages": messages}


def _pp_requirements(sidecar, progress, base_path, options):
    warnings = []
    messages = []
    if sidecar and sidecar.get("title"):
        messages.append(f"Requirements extracted: {sidecar['title']}")

    _eval_has_many_requirements_phase1(sidecar, progress, messages, warnings)

    return {"warnings": warnings, "messages": messages}


def _eval_has_many_requirements_phase1(sidecar, progress, messages, warnings):
    """Phase 1: after requirements, decide if quality-gate is needed based on count."""
    qg = progress.get("steps", {}).get("quality-gate")
    if not qg or qg.get("status") not in ("deferred", "pending"):
        return

    req_count = (sidecar or {}).get("requirement_count")
    if req_count is None:
        warnings.append(
            "requirement_count missing from requirements sidecar"
            " — defaulting to quality-gate enabled"
        )
        return

    if req_count < 6:
        qg["status"] = "skipped"
        qg["result"] = {"skip_reason": "few_requirements"}
        messages.append(f"Skipping quality-gate: {req_count} requirements (threshold: 6)")
    else:
        messages.append(f"Requirements: {req_count} requirements discovered")


def _pp_scope_req_audit(sidecar, progress, base_path, options):
    warnings = []
    messages = []
    if sidecar:
        g = sidecar.get("grounded", 0)
        p = sidecar.get("partial", 0)
        a = sidecar.get("absent", 0)
        t = sidecar.get("total", 0)
        rec = sidecar.get("recommendation", "unknown")
        messages.append(
            f"Scope audit: {g} grounded, {p} partial, {a} absent (total {t}), recommendation: {rec}"
        )
        if sidecar.get("discovered_repos_count", 0) > 0:
            count = sidecar["discovered_repos_count"]
            warnings.append(f"Scope audit discovered {count} additional repo(s) in README/docs")
    return {"warnings": warnings, "messages": messages}


def _pp_code_analysis(sidecar, progress, base_path, options):
    messages = []
    if sidecar:
        mc = sidecar.get("module_count", 0)
        rc = sidecar.get("relationship_count", 0)
        langs = sidecar.get("languages_detected", [])
        lang_str = ", ".join(langs)
        messages.append(
            f"Code analysis completed: {mc} modules, {rc} relationships, languages: {lang_str}"
        )
    return {"messages": messages}


def _pp_pr_analysis(sidecar, progress, base_path, options):
    messages = []
    if sidecar:
        pr_num = sidecar.get("pr_number", "?")
        mods = sidecar.get("modules_affected", "?")
        messages.append(f"PR analysis completed: PR #{pr_num} — {mods} modules affected")
    return {"messages": messages}


def _pp_planning(sidecar, progress, base_path, options):
    warnings = []
    messages = []
    module_count = 0

    if sidecar:
        module_count = sidecar.get("module_count", 0)
    else:
        plan_file = os.path.join(base_path, "planning", "plan.md")
        if os.path.isfile(plan_file):
            module_count = _count_modules_fallback(plan_file)

    messages.append(f"Planning completed: {module_count} modules")

    if module_count == 0:
        return {
            "warnings": ["Planning produced 0 modules — the plan may be empty"],
            "messages": messages,
            "action_override": {
                "action": "fail",
                "step": "planning",
                "reason": "Planning produced 0 modules",
                "message": "Workflow failed at planning: 0 modules produced",
            },
        }

    return {"warnings": warnings, "messages": messages}


def _count_modules_fallback(plan_file):
    """Count module specs in plan.md by regex (fallback if sidecar missing)."""
    count = 0
    in_code_block = False
    with open(plan_file) as f:
        for line in f:
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if not in_code_block and re.match(r"^###\s+(?:Module|Update)\b", line):
                count += 1
    return count


def _extract_files_from_sidecar(sidecar):
    """Extract file list from writing sidecar, handling both schema formats."""
    if not sidecar:
        return []
    files = sidecar.get("files", [])
    if files:
        return files
    # Legacy format: files_written with nested assemblies/modules arrays
    fw = sidecar.get("files_written")
    if isinstance(fw, dict):
        out = []
        for key in ("assemblies", "modules", "snippets"):
            out.extend(fw.get(key, []))
        return out
    return []


def _pp_writing(sidecar, progress, base_path, options):
    warnings = []
    messages = []

    files = _extract_files_from_sidecar(sidecar)

    if not files:
        warnings.append("Writing step produced no files")
        if "create-merge-request" in progress.get("steps", {}):
            cm = progress["steps"]["create-merge-request"]
            cm["status"] = "skipped"
            cm["result"] = {
                "schema_version": SCHEMA_VERSION,
                "step": "create-merge-request",
                "ticket": progress["ticket"],
                "completed_at": iso_now(),
                "commit_sha": None,
                "branch": None,
                "pushed": False,
                "url": None,
                "action": "skipped",
                "platform": "unknown",
                "skipped": True,
                "skip_reason": "no_files",
            }
            sidecar_dir = os.path.join(base_path, "create-merge-request")
            os.makedirs(sidecar_dir, exist_ok=True)
            atomic_write_json(os.path.join(sidecar_dir, "step-result.json"), cm["result"])
            messages.append("Skipping create-merge-request: no files to commit")

    # Check if this was a fix cycle (tech review iteration)
    fix_from = progress.get("_tech_review_fix_from")
    if fix_from:
        ticket = progress["ticket"]
        if "technical-review" in progress["steps"]:
            progress["steps"]["technical-review"]["status"] = "pending"
        return {
            "warnings": warnings,
            "messages": messages,
            "action_override": {
                "action": "run_skill",
                "skill": _get_step_skill(progress, "technical-review"),
                "args": build_step_args("technical-review", ticket, base_path, options, progress),
                "step": "technical-review",
                "message": "Fix cycle complete — re-running technical review",
            },
        }

    # Check if this was a quality gate fix cycle
    qg_fix_from = progress.get("_quality_gate_fix_from")
    if qg_fix_from:
        ticket = progress["ticket"]
        if "quality-gate" in progress["steps"]:
            progress["steps"]["quality-gate"]["status"] = "pending"
        return {
            "warnings": warnings,
            "messages": messages,
            "action_override": {
                "action": "run_skill",
                "skill": _get_step_skill(progress, "quality-gate"),
                "args": build_step_args("quality-gate", ticket, base_path, options, progress),
                "step": "quality-gate",
                "message": "Quality gate fix cycle complete — re-running quality gate",
            },
        }

    return {"warnings": warnings, "messages": messages}


def _pp_technical_review(sidecar, progress, base_path, options):
    warnings = []
    messages = []

    confidence = None
    severity = {}
    iteration = 1

    if sidecar:
        confidence = sidecar.get("confidence")
        severity = sidecar.get("severity_counts", {})
        iteration = sidecar.get("iteration", 1)

    if not confidence:
        review_file = os.path.join(base_path, "technical-review", "review.md")
        confidence, severity = _parse_review_fallback(review_file)

    if not confidence:
        return {
            "warnings": ["Could not extract confidence from technical review"],
            "messages": messages,
            "action_override": {
                "action": "fail",
                "step": "technical-review",
                "reason": "Missing required confidence line",
                "message": "Workflow failed at technical-review: confidence not found",
            },
        }

    messages.append(f"Technical review: {confidence} confidence (iteration {iteration})")

    if confidence == "HIGH":
        progress.pop("_tech_review_fix_from", None)
        progress.pop("_tech_review_iteration", None)
        _eval_has_many_requirements_phase2(confidence, progress, messages)
        return {"warnings": warnings, "messages": messages}

    # No agent-fixable work remains: only minor and/or SME-verification items
    # are left. A fix cycle re-runs the writer, which cannot resolve items that
    # need an SME (default values, version-specific behavior, upstream links).
    # Proceed regardless of confidence rather than burning iterations — and,
    # for LOW confidence, avoid failing the workflow over SME-only remainders.
    crit = severity.get("critical", 0)
    sig = severity.get("significant", 0)
    if isinstance(crit, str):
        crit = int(crit)
    if isinstance(sig, str):
        sig = int(sig)

    if crit == 0 and sig == 0:
        progress.pop("_tech_review_fix_from", None)
        progress.pop("_tech_review_iteration", None)
        sme = severity.get("sme", 0)
        if isinstance(sme, str):
            sme = int(sme)
        messages.append(
            f"{confidence} confidence with zero critical/significant issues — proceeding"
        )
        if sme:
            warnings.append(
                f"{sme} item(s) require SME verification — see technical-review/review.md"
            )
        _eval_has_many_requirements_phase2(confidence, progress, messages)
        return {"warnings": warnings, "messages": messages}

    max_iterations = 3
    if iteration >= max_iterations:
        progress.pop("_tech_review_fix_from", None)
        progress.pop("_tech_review_iteration", None)
        _eval_has_many_requirements_phase2(confidence, progress, messages)
        if confidence == "MEDIUM":
            warnings.append(
                f"MEDIUM confidence after {max_iterations} iterations — manual review recommended"
            )
            return {"warnings": warnings, "messages": messages}
        else:
            return {
                "warnings": warnings,
                "messages": messages,
                "action_override": {
                    "action": "fail",
                    "step": "technical-review",
                    "reason": f"LOW confidence after {max_iterations} iterations",
                    "message": (
                        f"Workflow failed: LOW confidence after {max_iterations} review iterations"
                    ),
                },
            }

    # Need fix cycle
    review_path = os.path.join(base_path, "technical-review", "review.md")
    progress["_tech_review_fix_from"] = review_path
    progress["_tech_review_iteration"] = iteration + 1

    ticket = progress["ticket"]
    if "writing" in progress["steps"]:
        progress["steps"]["writing"]["status"] = "pending"

    return {
        "warnings": warnings,
        "messages": messages,
        "action_override": make_step_action(
            step="writing",
            message=f"Iteration {iteration + 1}: applying fixes from technical review",
            ticket=ticket,
            skill=_get_step_skill(progress, "writing"),
            args=build_step_args("writing", ticket, base_path, options, progress),
        ),
    }


def _parse_review_fallback(review_file):
    """Extract confidence and severity from review.md by regex."""
    if not os.path.isfile(review_file):
        return None, {}

    confidence = None
    severity = {}

    with open(review_file) as f:
        for line in f:
            pat = r"(?:Overall\s+)?(?:technical\s+)?confidence[:\s]*\*?\*?\s*(HIGH|MEDIUM|LOW)"
            m = re.search(pat, line, re.IGNORECASE)
            if m:
                confidence = m.group(1).upper()

            m = re.search(
                r"critical[=:]\s*(\d+)[,;\s]+significant[=:]\s*(\d+)[,;\s]+minor[=:]\s*(\d+)[,;\s]+sme[=:]\s*(\d+)",
                line,
                re.IGNORECASE,
            )
            if m:
                severity = {
                    "critical": int(m.group(1)),
                    "significant": int(m.group(2)),
                    "minor": int(m.group(3)),
                    "sme": int(m.group(4)),
                }

    return confidence, severity


def _eval_has_many_requirements_phase2(confidence, progress, messages):
    """Phase 2: after tech-review settles, decide quality-gate status."""
    qg = progress.get("steps", {}).get("quality-gate")
    if not qg:
        return
    if qg.get("status") == "skipped":
        return

    if confidence == "HIGH":
        qg["status"] = "skipped"
        qg["result"] = {"skip_reason": "high_confidence_review"}
        messages.append("Skipping quality-gate: technical review reached HIGH confidence")
    else:
        qg["status"] = "pending"
        messages.append("Quality-gate enabled: technical review did not reach HIGH confidence")


def _pp_security_review(sidecar, progress, base_path, options):
    warnings = []
    messages = []
    if sidecar:
        scanner = sidecar.get("scanner_findings", 0)
        critical = sidecar.get("critical_findings", 0)
        agent = sidecar.get("agent_findings", 0)
        messages.append(
            f"Security review: {scanner} scanner findings,"
            f" {critical} critical, {agent} agent findings"
        )
        if critical > 0:
            warnings.append(
                f"Security review found {critical} critical finding(s) — review before merging"
            )
    return {"warnings": warnings, "messages": messages}


def _pp_quality_gate(sidecar, progress, base_path, options):
    warnings = []
    messages = []

    if not sidecar:
        return {"warnings": ["No step-result.json for quality-gate"], "messages": messages}

    doc_quality = sidecar.get("doc_quality", 0)
    intent_alignment = sidecar.get("intent_alignment", 0)
    passed = sidecar.get("passed", False)
    iteration = sidecar.get("iteration", 1)
    gaps = sidecar.get("gaps", [])

    messages.append(
        f"Quality gate: doc_quality={doc_quality}/5,"
        f" intent_alignment={intent_alignment}/5,"
        f" passed={passed}, gaps={len(gaps)}"
    )

    if intent_alignment >= 4:
        progress.pop("_quality_gate_fix_from", None)
        progress.pop("_quality_gate_iteration", None)
        if doc_quality < 4:
            warnings.append(
                f"Quality gate passed but doc_quality is {doc_quality}/5 — consider improvements"
            )
        return {"warnings": warnings, "messages": messages}

    max_iterations = 2
    if iteration >= max_iterations:
        progress.pop("_quality_gate_fix_from", None)
        progress.pop("_quality_gate_iteration", None)
        if intent_alignment >= 3:
            warnings.append(
                f"Quality gate: intent_alignment={intent_alignment}/5"
                f" after {max_iterations} iterations — accepting with warning"
            )
            return {"warnings": warnings, "messages": messages}
        else:
            return {
                "warnings": warnings,
                "messages": messages,
                "action_override": {
                    "action": "fail",
                    "step": "quality-gate",
                    "reason": (
                        f"intent_alignment={intent_alignment}/5 after {max_iterations} iterations"
                    ),
                    "message": (
                        f"Workflow failed: intent_alignment={intent_alignment}/5"
                        f" after {max_iterations} quality gate iterations"
                    ),
                },
            }

    feedback_file = os.path.join(base_path, "quality-gate", f"feedback-brief-{iteration}.md")
    progress["_quality_gate_fix_from"] = feedback_file
    progress["_quality_gate_iteration"] = iteration + 1

    ticket = progress["ticket"]
    if "writing" in progress["steps"]:
        progress["steps"]["writing"]["status"] = "pending"

    return {
        "warnings": warnings,
        "messages": messages,
        "action_override": make_step_action(
            step="writing",
            message=(f"Quality gate iteration {iteration + 1}: applying fixes from feedback brief"),
            ticket=ticket,
            skill=_get_step_skill(progress, "writing"),
            args=build_step_args("writing", ticket, base_path, options, progress),
        ),
    }


def _pp_pipeline_diagnostics(sidecar, progress, base_path, options):
    warnings = []
    messages = []
    if sidecar:
        pressure = sidecar.get("context_pressure_level", "unknown")
        failures = sidecar.get("failure_count", 0)
        bottlenecks = sidecar.get("bottleneck_count", 0)
        messages.append(
            f"Pipeline diagnostics: context_pressure={pressure},"
            f" failures={failures}, bottlenecks={bottlenecks}"
        )
        high_sev = sidecar.get("high_severity_failure_count", 0)
        if high_sev > 0:
            warnings.append(
                f"Pipeline had {high_sev} high-severity failure(s). Review the diagnostic report"
            )
        if pressure in ("high", "critical"):
            warnings.append(
                f"Context pressure is {pressure}. Consider workflow splitting for future runs"
            )
    return {"warnings": warnings, "messages": messages}


def _pp_create_merge_request(sidecar, progress, base_path, options):
    warnings = []
    messages = []
    if sidecar:
        pushed = sidecar.get("pushed", False)
        skipped = sidecar.get("skipped", False)
        url = sidecar.get("url")
        if not pushed and not skipped:
            warnings.append("create-merge-request: branch was not pushed")
        if url:
            messages.append(f"MR/PR created: {url}")
    return {"warnings": warnings, "messages": messages}


def _pp_create_jira(sidecar, progress, base_path, options):
    messages = []
    if sidecar:
        url = sidecar.get("jira_url")
        key = sidecar.get("jira_key")
        if url:
            messages.append(f"JIRA ticket created: {key} — {url}")
    return {"messages": messages}


_POST_PROCESSORS = {
    "requirements": _pp_requirements,
    "scope-req-audit": _pp_scope_req_audit,
    "code-analysis": _pp_code_analysis,
    "pr-analysis": _pp_pr_analysis,
    "planning": _pp_planning,
    "writing": _pp_writing,
    "technical-review": _pp_technical_review,
    "security-review": _pp_security_review,
    "quality-gate": _pp_quality_gate,
    "pipeline-diagnostics": _pp_pipeline_diagnostics,
    "create-merge-request": _pp_create_merge_request,
    "create-jira": _pp_create_jira,
}


def _get_step_skill(progress, step_name):
    """Look up the skill name for a step from the progress file's stored YAML data."""
    skill = progress.get("_step_skills", {}).get(step_name, f"docs-workflow-{step_name}")
    if ":" in skill:
        skill = skill.split(":", 1)[1]
    return skill


# ---------------------------------------------------------------------------
# Action constructors
# ---------------------------------------------------------------------------


def make_run_skill(skill, args, step, message, warnings=None, messages=None, **extra):
    action = {
        "action": "run_skill",
        "skill": skill,
        "args": args,
        "step": step,
        "message": message,
    }
    if warnings:
        action["warnings"] = warnings
    if messages:
        action["messages"] = messages
    action.update(extra)
    return action


def is_dispatch_eligible(step_name):
    """Return True if a step should be dispatched via prepare-step, not run_skill."""
    return step_name in DISPATCH_STEPS


def make_dispatch(step, message, ticket, warnings=None, messages=None, **extra):
    script = os.path.join(PLUGIN_ROOT, "scripts", "docs_orchestrator.py")
    action = {
        "action": "dispatch",
        "step": step,
        "message": message,
        "prepare": f"python3 {script} prepare-step {ticket} {step}",
    }
    if warnings:
        action["warnings"] = warnings
    if messages:
        action["messages"] = messages
    action.update(extra)
    return action


def make_step_action(step, message, ticket, skill, args, warnings=None, messages=None, **extra):
    """Emit a dispatch action for dispatch-eligible steps, else a run_skill action."""
    if is_dispatch_eligible(step):
        return make_dispatch(step, message, ticket, warnings=warnings, messages=messages, **extra)
    return make_run_skill(
        skill=skill,
        args=args,
        step=step,
        message=message,
        warnings=warnings,
        messages=messages,
        **extra,
    )


def make_complete(progress, warnings=None, messages=None):
    steps_completed = [n for n, s in progress["steps"].items() if s["status"] == "completed"]
    steps_skipped = [n for n, s in progress["steps"].items() if s["status"] == "skipped"]
    steps_deferred = [n for n, s in progress["steps"].items() if s["status"] == "deferred"]

    all_warnings = list(warnings or [])
    if steps_deferred:
        all_warnings.append(
            f"Deferred steps never resolved (source repo not found): {', '.join(steps_deferred)}"
        )

    summary = {
        "steps_completed": steps_completed,
        "steps_skipped": steps_skipped,
        "steps_deferred": steps_deferred,
        "warnings": all_warnings,
    }

    mr_result = (progress["steps"].get("create-merge-request") or {}).get("result") or {}
    summary["mr_url"] = mr_result.get("url")

    jira_result = (progress["steps"].get("create-jira") or {}).get("result") or {}
    summary["jira_url"] = jira_result.get("jira_url")
    summary["jira_key"] = jira_result.get("jira_key")

    planning_result = (progress["steps"].get("planning") or {}).get("result") or {}
    summary["module_count"] = planning_result.get("module_count")

    writing_result = (progress["steps"].get("writing") or {}).get("result") or {}
    files = writing_result.get("files", [])
    summary["file_count"] = len(files) if isinstance(files, list) else 0

    return {
        "action": "complete",
        "summary": summary,
        "message": f"Workflow completed for {progress['ticket']}",
    }


def make_fail(step, reason, message, warnings=None):
    action = {
        "action": "fail",
        "step": step,
        "reason": reason,
        "message": message,
    }
    if warnings:
        action["warnings"] = warnings
    return action


# ---------------------------------------------------------------------------
# Find next step
# ---------------------------------------------------------------------------


def find_next_step(progress):
    """Find the first actionable step. Returns (step_name, step_data) or (None, None)."""
    for name in progress.get("step_order", []):
        step = progress["steps"].get(name, {})
        status = step.get("status", "pending")
        if status in ("pending", "in_progress", "failed"):
            return name, step
    return None, None


def check_input_deps(step_name, progress, yaml_steps_map):
    """Validate that all input dependencies for a step are satisfied."""
    yaml_step = yaml_steps_map.get(step_name, {})
    inputs = yaml_step.get("inputs", [])
    errors = []

    for dep in inputs:
        dep_data = progress["steps"].get(dep)
        if not dep_data:
            continue
        dep_status = dep_data.get("status", "pending")
        if dep_status == "failed":
            errors.append(f"Step '{step_name}' requires '{dep}', but {dep} has status 'failed'")
        elif dep_status in ("pending", "in_progress"):
            errors.append(
                f"Step '{step_name}' requires '{dep}', but {dep} has status '{dep_status}'"
            )

    return errors


# ---------------------------------------------------------------------------
# Resolve workflow YAML path
# ---------------------------------------------------------------------------


def resolve_yaml_path(workflow_name=None):
    """Resolve the workflow YAML file path with fallback chain."""
    workspace = ".agent_workspace"

    if workflow_name:
        if not WORKFLOW_NAME_RE.fullmatch(workflow_name):
            return None
        project_file = os.path.join(workspace, f"docs-{workflow_name}.yaml")
        if os.path.isfile(project_file):
            return project_file
        default_file = os.path.join(DEFAULT_WORKFLOW_DIR, f"docs-{workflow_name}.yaml")
        if os.path.isfile(default_file):
            return default_file
        return None

    project_file = os.path.join(workspace, "docs-workflow.yaml")
    if os.path.isfile(project_file):
        return project_file
    default_file = os.path.join(DEFAULT_WORKFLOW_DIR, "docs-workflow.yaml")
    if os.path.isfile(default_file):
        return default_file
    return None


# ---------------------------------------------------------------------------
# Build options dict from CLI args
# ---------------------------------------------------------------------------


def build_options(args):
    """Build the options dict from parsed CLI arguments."""
    fmt = "mkdocs" if getattr(args, "mkdocs", False) else "adoc"

    docs_repo = getattr(args, "docs_repo_path", None)
    draft = getattr(args, "draft", False)
    if docs_repo and draft:
        print(
            "WARNING: --draft ignored because --docs-repo-path takes precedence.", file=sys.stderr
        )
        draft = False

    return {
        "format": fmt,
        "draft": draft,
        "create_merge_request": getattr(args, "create_merge_request", False),
        "create_jira": getattr(args, "create_jira", None),
        "pr_urls": getattr(args, "pr", None) or [],
        "source": None,
        "additional_sources": [],
        "no_source_repo": getattr(args, "no_source_repo", False),
        "auto_discover_repos": getattr(args, "auto_discover_repos", False),
        "max_secondary_repos": getattr(args, "max_secondary_repos", 3),
        "docs_repo_path": docs_repo,
    }


# ---------------------------------------------------------------------------
# Subcommand: init
# ---------------------------------------------------------------------------


def cmd_init(args):
    ticket = args.ticket
    _validate_ticket(ticket)
    ticket_lower = ticket.lower()
    root = git_root()
    base_path = os.path.join(root, ".agent_workspace", ticket_lower)
    os.makedirs(base_path, exist_ok=True)

    options = build_options(args)

    # Resolve workflow YAML
    yaml_path = resolve_yaml_path(getattr(args, "workflow", None))
    if not yaml_path:
        emit({"action": "fail", "error": True, "message": "No workflow YAML found"})
        sys.exit(1)

    workflow_name, _, yaml_steps, requires = parse_workflow_yaml(yaml_path)

    # Validate YAML
    validation_errors = validate_steps(yaml_steps)
    if validation_errors:
        emit(
            {
                "action": "fail",
                "error": True,
                "message": "Invalid workflow YAML",
                "details": validation_errors,
            }
        )
        sys.exit(1)

    yaml_steps_map = {s["name"]: s for s in yaml_steps}

    # Check requires conditions
    for req in requires:
        if not evaluate_when(req, options):
            emit(
                {
                    "action": "fail",
                    "error": True,
                    "message": f"Workflow requires condition '{req}' which is not met",
                }
            )
            sys.exit(1)

    # Pre-flight source resolution
    repos = getattr(args, "source_code_repo", None)
    pr_urls = options["pr_urls"]

    if not options["no_source_repo"] and (repos or pr_urls):
        exit_code, source_result = call_resolve_source(base_path, repos=repos, pr_urls=pr_urls)
        if exit_code == 0 and source_result.get("status") == "resolved":
            options["source"] = {
                "repo_path": source_result.get("repo_path"),
                "repo_url": source_result.get("repo_url"),
                "ref": source_result.get("ref"),
                "scope": source_result.get("scope"),
            }
            options["additional_sources"] = source_result.get("additional_repos", [])
        elif exit_code == 1:
            emit(
                {
                    "action": "fail",
                    "error": True,
                    "message": source_result.get("message", "Source resolution failed"),
                }
            )
            sys.exit(1)
        # exit_code == 2 (no_source): leave source as None, steps will be deferred

    # Classify steps
    step_order = [s["name"] for s in yaml_steps]

    # Check for existing progress file (resume)
    pfile = progress_path(base_path, workflow_name, ticket_lower)
    progress = read_progress(pfile)

    if progress:
        # Resume: rehydrate source if needed
        if not progress.get("options", {}).get("source"):
            req_step = progress.get("steps", {}).get("requirements", {})
            if req_step.get("status") == "completed":
                exit_code, source_result = call_resolve_source(
                    base_path,
                    progress_file=pfile,
                    scan_requirements=True,
                    skip_deferred=True,
                )
                if exit_code == 0:
                    progress = read_progress(pfile)
                    if not progress:
                        emit(
                            {
                                "action": "fail",
                                "error": True,
                                "message": "Progress file corrupted after source resolution",
                            }
                        )
                        sys.exit(1)

        # Merge new options from CLI (e.g., --create-jira added on resume)
        for key in (
            "create_merge_request",
            "create_jira",
            "auto_discover_repos",
            "max_secondary_repos",
        ):
            new_val = options.get(key)
            if new_val and not progress["options"].get(key):
                progress["options"][key] = new_val

        # Reset in_progress steps (interrupted mid-execution) back to pending
        for step_data in progress["steps"].values():
            if step_data["status"] == "in_progress":
                step_data["status"] = "pending"

        # Verify completed steps still have output on disk
        for step_data in progress["steps"].values():
            if step_data["status"] == "completed" and step_data.get("output"):
                if not os.path.isdir(step_data["output"]):
                    step_data["status"] = "pending"
                    step_data["output"] = None
                    step_data["result"] = None

        resumed = True
        options = progress["options"]
    else:
        # New workflow
        progress = create_progress(
            ticket, workflow_name, base_path, options, yaml_steps, step_order
        )

        for s in yaml_steps:
            status = classify_step(s, options)
            progress["steps"][s["name"]]["status"] = status

        resumed = False

    # Store step skill mapping for later use
    progress["_step_skills"] = {s["name"]: s["skill"] for s in yaml_steps}

    # Write progress + marker
    write_progress(pfile, progress)
    rel_pfile = os.path.relpath(pfile, root)
    write_active_marker(base_path, ticket, workflow_name, rel_pfile)

    # Find next step
    next_name, _ = find_next_step(progress)
    if not next_name:
        # All steps done already
        progress["status"] = "completed"
        write_progress(pfile, progress)
        delete_active_marker(base_path)
        emit(make_complete(progress))
        return

    # Validate input deps for the next step
    dep_errors = check_input_deps(next_name, progress, yaml_steps_map)
    if dep_errors:
        emit({"action": "fail", "error": True, "message": dep_errors[0]})
        sys.exit(1)

    # Mark step in_progress
    progress["steps"][next_name]["status"] = "in_progress"
    write_progress(pfile, progress)

    skill = yaml_steps_map[next_name]["skill"]
    step_args = build_step_args(next_name, ticket, base_path, options, progress)

    if step_args is None:
        print(f"WARNING: skipping step {next_name}: missing required arguments", file=sys.stderr)
        progress["steps"][next_name]["status"] = "skipped"
        write_progress(pfile, progress)
        next_name, _ = find_next_step(progress)
        if not next_name:
            progress["status"] = "completed"
            write_progress(pfile, progress)
            delete_active_marker(base_path)
            emit(make_complete(progress))
            return
        progress["steps"][next_name]["status"] = "in_progress"
        write_progress(pfile, progress)
        skill = yaml_steps_map[next_name]["skill"]
        step_args = build_step_args(next_name, ticket, base_path, options, progress)

    completed = [n for n, s in progress["steps"].items() if s["status"] == "completed"]

    emit(
        make_step_action(
            step=next_name,
            message=(
                f"{'Resuming' if resumed else 'Initialized'}"
                f" workflow {workflow_name} for {ticket}"
                + (f" from {next_name}" if resumed else "")
            ),
            ticket=ticket,
            skill=skill,
            args=step_args,
            resumed=resumed,
            completed_steps=completed,
            progress_file=rel_pfile,
        )
    )


# ---------------------------------------------------------------------------
# Subcommand: step-done
# ---------------------------------------------------------------------------


def cmd_step_done(args):
    ticket = args.ticket
    _validate_ticket(ticket)
    ticket_lower = ticket.lower()
    root = git_root()
    base_path = os.path.join(root, ".agent_workspace", ticket_lower)

    # Find progress file
    pfile = resolve_progress_file(base_path, root)
    if not pfile:
        emit({"action": "fail", "error": True, "message": "No progress file found"})
        sys.exit(1)

    progress = read_progress(pfile)
    if not progress:
        emit({"action": "fail", "error": True, "message": f"Cannot read progress file: {pfile}"})
        sys.exit(1)

    step_name = args.step_name
    options = progress.get("options", {})

    # Verify step exists
    if step_name not in progress.get("steps", {}):
        emit(
            {
                "action": "fail",
                "error": True,
                "message": f"Unknown step '{step_name}' — not in progress file",
            }
        )
        sys.exit(1)

    current_status = progress["steps"][step_name].get("status")
    if getattr(args, "force", False) and current_status == "pending":
        progress["steps"][step_name]["status"] = "in_progress"
        write_progress(pfile, progress)
        current_status = "in_progress"
        print(
            f"WARNING: --force promoted '{step_name}' from pending to in_progress",
            file=sys.stderr,
        )
    if current_status != "in_progress":
        emit(
            {
                "action": "fail",
                "error": True,
                "message": (
                    f"Step '{step_name}' cannot be completed from status '{current_status}'. "
                    "Expected 'in_progress'."
                ),
            }
        )
        sys.exit(1)

    if args.failed:
        progress["steps"][step_name]["status"] = "failed"
        progress["status"] = "failed"
        write_progress(pfile, progress)
        delete_active_marker(base_path)
        delete_stop_counter(pfile)
        emit(make_fail(step_name, "Step reported failure", f"Workflow failed at {step_name}"))
        return

    # Verify output exists
    output_dir = os.path.join(base_path, step_name)
    if os.path.isdir(output_dir):
        progress["steps"][step_name]["output"] = output_dir

    # Mark completed
    progress["steps"][step_name]["status"] = "completed"
    if progress.get("status") == "failed":
        progress["status"] = "in_progress"

    # Run post-processing
    pp_result = post_process(step_name, progress, base_path, options)
    all_warnings = pp_result.get("warnings", [])
    all_messages = pp_result.get("messages", [])

    # Check for action override (fail, fix cycle, etc.)
    if "action_override" in pp_result:
        override = pp_result["action_override"]

        if override["action"] == "fail":
            progress["steps"][step_name]["status"] = "failed"
            progress["status"] = "failed"
            write_progress(pfile, progress)
            delete_active_marker(base_path)
            delete_stop_counter(pfile)
            override["warnings"] = all_warnings
            emit(override)
            return

        if override["action"] in ("run_skill", "dispatch"):
            target_step = override.get("step")
            if target_step and target_step in progress["steps"]:
                progress["steps"][target_step]["status"] = "in_progress"
            write_progress(pfile, progress)
            override["warnings"] = all_warnings
            override["messages"] = all_messages
            emit(override)
            return

    # Normal progression: find next step
    write_progress(pfile, progress)

    # After requirements, resolve source repos discovered in the requirements
    # output and flip deferred source-dependent steps to pending. Run after the
    # write above so resolve_source.py reads a consistent progress file.
    if step_name == "requirements":
        src_messages = resolve_source_post_requirements(base_path, pfile, progress, options)
        all_messages.extend(src_messages)

    # Rebuild yaml_steps_map from stored skills
    yaml_steps_map = {}
    for sname in progress.get("step_order", []):
        yaml_steps_map[sname] = {
            "name": sname,
            "skill": _get_step_skill(progress, sname),
            "inputs": [],  # deps already validated at init
        }

    next_name, _ = find_next_step(progress)
    if not next_name:
        progress["status"] = "completed"
        write_progress(pfile, progress)
        delete_active_marker(base_path)
        delete_stop_counter(pfile)
        emit(make_complete(progress, warnings=all_warnings, messages=all_messages))
        return

    # Mark next step in_progress
    progress["steps"][next_name]["status"] = "in_progress"
    write_progress(pfile, progress)

    skill = _get_step_skill(progress, next_name)
    step_args = build_step_args(next_name, ticket, base_path, options, progress)

    if step_args is None:
        print(f"WARNING: skipping step {next_name}: missing required arguments", file=sys.stderr)
        progress["steps"][next_name]["status"] = "skipped"
        write_progress(pfile, progress)
        next_name, _ = find_next_step(progress)
        if not next_name:
            progress["status"] = "completed"
            write_progress(pfile, progress)
            delete_active_marker(base_path)
            delete_stop_counter(pfile)
            emit(make_complete(progress, warnings=all_warnings, messages=all_messages))
            return
        progress["steps"][next_name]["status"] = "in_progress"
        write_progress(pfile, progress)
        skill = _get_step_skill(progress, next_name)
        step_args = build_step_args(next_name, ticket, base_path, options, progress)

    emit(
        make_step_action(
            step=next_name,
            message=f"{step_name} completed. Next: {next_name}",
            ticket=ticket,
            skill=skill,
            args=step_args,
            warnings=all_warnings,
            messages=all_messages,
        )
    )


# ---------------------------------------------------------------------------
# Subcommand: retry-step
# ---------------------------------------------------------------------------


def cmd_retry_step(args):
    """Reset a failed or stuck step and re-emit its action so the loop retries it.

    Recovery path for steps left in a non-runnable state (e.g. a step marked
    ``failed`` by post-processing, or a workflow halted after a failure).
    Avoids hand-editing the progress JSON.
    """
    ticket = args.ticket
    _validate_ticket(ticket)
    ticket_lower = ticket.lower()
    root = git_root()
    base_path = os.path.join(root, ".agent_workspace", ticket_lower)

    pfile = resolve_progress_file(base_path, root)
    if not pfile:
        emit({"action": "fail", "error": True, "message": "No progress file found"})
        sys.exit(1)

    progress = read_progress(pfile)
    if not progress:
        emit({"action": "fail", "error": True, "message": f"Cannot read progress file: {pfile}"})
        sys.exit(1)

    step_name = args.step_name
    if step_name not in progress.get("steps", {}):
        emit(
            {
                "action": "fail",
                "error": True,
                "message": f"Unknown step '{step_name}' — not in progress file",
            }
        )
        sys.exit(1)

    options = progress.get("options", {})

    # Reset the target step so it re-runs from scratch.
    step = progress["steps"][step_name]
    step["status"] = "in_progress"
    step["output"] = None
    step["result"] = None

    # Un-fail the workflow so the loop continues.
    if progress.get("status") == "failed":
        progress["status"] = "in_progress"

    write_progress(pfile, progress)

    # The active marker and stop counter are removed when a step fails; restore
    # the marker so subsequent commands resolve this workflow, and reset the
    # stop counter for a fresh retry.
    rel_pfile = os.path.relpath(pfile, root)
    write_active_marker(base_path, ticket, progress.get("workflow", "docs-workflow"), rel_pfile)
    delete_stop_counter(pfile)

    skill = _get_step_skill(progress, step_name)
    step_args = build_step_args(step_name, ticket, base_path, options, progress)
    if step_args is None:
        emit(
            {
                "action": "fail",
                "error": True,
                "message": f"Cannot retry '{step_name}': missing required arguments",
            }
        )
        sys.exit(1)

    emit(
        make_step_action(
            step=step_name,
            message=f"Retrying step: {step_name}",
            ticket=ticket,
            skill=skill,
            args=step_args,
            progress_file=rel_pfile,
        )
    )


# ---------------------------------------------------------------------------
# Subcommand: next
# ---------------------------------------------------------------------------


def cmd_next(args):
    ticket = args.ticket
    _validate_ticket(ticket)
    ticket_lower = ticket.lower()
    root = git_root()
    base_path = os.path.join(root, ".agent_workspace", ticket_lower)

    pfile = resolve_progress_file(base_path, root)
    if not pfile:
        emit({"action": "fail", "error": True, "message": "No progress file found"})
        sys.exit(1)

    progress = read_progress(pfile)
    if not progress:
        emit({"action": "fail", "error": True, "message": "Cannot read progress file"})
        sys.exit(1)

    options = progress.get("options", {})
    next_name, _ = find_next_step(progress)

    if not next_name:
        emit(make_complete(progress))
        return

    skill = _get_step_skill(progress, next_name)
    step_args = build_step_args(next_name, ticket, base_path, options, progress)

    if step_args is None:
        print(f"WARNING: skipping step {next_name}: missing required arguments", file=sys.stderr)
        progress["steps"][next_name]["status"] = "skipped"
        write_progress(pfile, progress)
        next_name, _ = find_next_step(progress)
        if not next_name:
            emit(make_complete(progress))
            return
        skill = _get_step_skill(progress, next_name)
        step_args = build_step_args(next_name, ticket, base_path, options, progress)

    emit(
        make_run_skill(
            skill=skill,
            args=step_args,
            step=next_name,
            message=f"Next step: {next_name}",
        )
    )


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------


def cmd_status(args):
    ticket = args.ticket
    _validate_ticket(ticket)
    ticket_lower = ticket.lower()
    root = git_root()
    base_path = os.path.join(root, ".agent_workspace", ticket_lower)

    pfile = resolve_progress_file(base_path, root)
    if not pfile:
        msg = f"No progress file found for {ticket}"
        emit({"action": "status", "found": False, "message": msg})
        return

    progress = read_progress(pfile)
    if not progress:
        emit({"action": "status", "found": False, "message": "Cannot read progress file"})
        return

    steps = progress.get("steps", {})
    total = len(steps)
    completed = sum(1 for s in steps.values() if s.get("status") in ("completed", "skipped"))

    next_name, _ = find_next_step(progress)

    emit(
        {
            "action": "status",
            "found": True,
            "workflow": progress.get("workflow"),
            "ticket": progress.get("ticket"),
            "status": progress.get("status"),
            "progress": f"{completed}/{total}",
            "next_step": next_name,
            "steps": {n: s.get("status") for n, s in steps.items()},
        }
    )


# ---------------------------------------------------------------------------
# prepare-step: build agent dispatch instructions for the main loop
# ---------------------------------------------------------------------------

WRITING_BUILD_SCRIPT = os.path.join(
    PLUGIN_ROOT, "skills", "docs-workflow-writing", "scripts", "build_writing_args.sh"
)
WRITING_PROMPTS_DIR = os.path.join(PLUGIN_ROOT, "skills", "docs-workflow-writing", "prompts")
WRITE_STEP_RESULT_SCRIPT = os.path.join(
    PLUGIN_ROOT, "skills", "docs-workflow-writing", "scripts", "write_step_result.py"
)

_WRITING_DESCRIPTIONS = {
    "fix": "Fix documentation for {ticket}",
    "adoc": "Write adoc documentation for {ticket}",
    "mkdocs": "Write mkdocs documentation for {ticket}",
}


def _run_build_writing_args(ticket, base_path, options, progress):
    """Run build_writing_args.sh and return its parsed JSON config."""
    args_str = build_step_args("writing", ticket, base_path, options, progress)
    cmd = ["bash", WRITING_BUILD_SCRIPT, *shlex.split(args_str)]
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"build_writing_args.sh failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _render_writing_prompt(template, cfg):
    """Render a writing prompt template against the build-script config.

    Handles the two marker patterns used in the prompt templates:
      - ``**[Include only if X]** text`` — keep the paragraph only when X holds
      - ``[If `docs_repo_path` is not null: "text"]`` — inline conditional
    then substitutes ``<PLACEHOLDER>`` tokens with resolved values.

    A ``**[Include only if X]**`` marker's condition is *inherited* by any
    continuation paragraphs that follow it, until the next paragraph that
    starts a new marker or a ``**bold`` / ``[`` directive (which resets the
    block back to unconditional). This mirrors how a human reader groups the
    marker's first paragraph with the un-marked paragraph beneath it.
    """
    flags = {
        "HAS_CODE_ANALYSIS=true": bool(cfg.get("has_code_analysis")),
        "HAS_PR_ANALYSIS=true": bool(cfg.get("has_pr_analysis")),
        "SOURCE_REPO is not null": cfg.get("source_repo_path") is not None,
        "ADDITIONAL_REPO_PATHS is non-empty": bool(cfg.get("additional_repo_paths")),
    }

    kept = []
    current_cond = None  # None = unconditional; True/False = inherited marker state
    for para in re.split(r"\n[ \t]*\n", template):
        stripped = para.lstrip()
        marker = re.match(r"^\*\*\[Include only if (.+?)\]\*\*\s?(.*)$", stripped, re.DOTALL)
        if marker:
            current_cond = flags.get(marker.group(1).strip(), True)
            if current_cond:
                kept.append(marker.group(2))
            continue
        # A new **bold or [ directive ends any inherited conditional block.
        if stripped.startswith("**") or stripped.startswith("["):
            current_cond = None
        if current_cond is not False:
            kept.append(para)
    text = "\n\n".join(kept)

    docs_repo = cfg.get("docs_repo_path")
    text = re.sub(
        r'\[If `docs_repo_path` is not null: "(.*?)"\]',
        lambda match: match.group(1) if docs_repo else "",
        text,
    )

    additional = cfg.get("additional_repo_paths") or []
    additional_analysis = cfg.get("additional_code_analysis_dirs") or []
    substitutions = {
        "<list each path from ADDITIONAL_REPO_PATHS>": ", ".join(additional),
        "<TICKET>": cfg.get("ticket") or "",
        "<INPUT_FILE>": cfg.get("input_file") or "",
        "<CODE_ANALYSIS_DIR>": cfg.get("code_analysis_dir") or "",
        "<PR_ANALYSIS_DIR>": cfg.get("pr_analysis_dir") or "",
        "<SOURCE_REPO>": cfg.get("source_repo_path") or "",
        "<ADDITIONAL_REPO_PATHS>": ", ".join(additional),
        "<ADDITIONAL_CODE_ANALYSIS_DIRS>": ", ".join(additional_analysis),
        "<OUTPUT_FILE>": cfg.get("output_file") or "",
        "<OUTPUT_DIR>": cfg.get("output_dir") or "",
        "<DOCS_REPO_PATH>": docs_repo or "",
        "<FIX_FROM>": cfg.get("fix_from") or "",
    }
    for token, value in substitutions.items():
        text = text.replace(token, value)
    return text


def _prepare_writing(ticket, base_path, options, progress, phase=None):
    cfg = _run_build_writing_args(ticket, base_path, options, progress)
    mode = cfg["mode"]
    fmt = cfg["format"]

    if mode == "fix":
        template_name = "fix.md"
        description = _WRITING_DESCRIPTIONS["fix"].format(ticket=ticket)
    else:
        template_name = f"{mode}-{fmt}.md"
        description = _WRITING_DESCRIPTIONS[fmt].format(ticket=ticket)

    with open(os.path.join(WRITING_PROMPTS_DIR, template_name), encoding="utf-8") as f:
        template = f.read()
    prompt = _render_writing_prompt(template, cfg)

    agent = {
        "type": "docs-skills:docs-writer",
        "prompt": prompt,
        "description": description,
        "background": False,
        "model": None,
        "schema": None,
    }

    finalize = []
    verify = None
    if cfg.get("verify_output"):
        verify = cfg["output_file"]
        sidecar = os.path.join(cfg["output_dir"], "step-result.json")
        finalize.append(
            "python3 {script} --ticket {ticket} --manifest {manifest} "
            "--mode {mode} --format {fmt} --sidecar {sidecar}".format(
                script=shlex.quote(WRITE_STEP_RESULT_SCRIPT),
                ticket=shlex.quote(ticket),
                manifest=shlex.quote(cfg["output_file"]),
                mode=shlex.quote(mode),
                fmt=shlex.quote(fmt),
                sidecar=shlex.quote(sidecar),
            )
        )

    return {
        "agents": [agent],
        "post_commands": [],
        "finalize": finalize,
        "verify": verify,
        "next_phase": None,
    }


PREPARE_STEPS = {
    "writing": _prepare_writing,
}


def cmd_prepare_step(args):
    ticket = args.ticket
    _validate_ticket(ticket)
    ticket_lower = ticket.lower()
    root = git_root()
    base_path = os.path.join(root, ".agent_workspace", ticket_lower)

    pfile = resolve_progress_file(base_path, root)
    if not pfile:
        emit({"action": "fail", "error": True, "message": "No progress file found"})
        sys.exit(1)

    progress = read_progress(pfile)
    if not progress:
        emit({"action": "fail", "error": True, "message": "Cannot read progress file"})
        sys.exit(1)

    step = args.step
    prepare_fn = PREPARE_STEPS.get(step)
    if not prepare_fn:
        emit(
            {
                "action": "fail",
                "error": True,
                "message": f"No prepare function for step '{step}'",
            }
        )
        sys.exit(1)

    options = progress.get("options", {})
    phase = getattr(args, "phase", None)
    try:
        result = prepare_fn(ticket, base_path, options, progress, phase=phase)
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        emit({"action": "fail", "error": True, "message": str(exc)})
        sys.exit(1)

    emit(result)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Docs orchestrator state machine driver")
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize or resume a workflow")
    p_init.add_argument("ticket", help="JIRA ticket ID")
    p_init.add_argument("--workflow", help="Use named workflow variant")
    p_init.add_argument("--pr", nargs="+", help="PR/MR URL(s)")
    p_init.add_argument("--source-code-repo", nargs="+", help="Source repo URL(s) or path(s)")
    p_init.add_argument("--mkdocs", action="store_true", help="Use MkDocs format")
    p_init.add_argument("--draft", action="store_true", help="Draft mode")
    p_init.add_argument("--docs-repo-path", help="Target docs repo path")
    p_init.add_argument("--create-merge-request", action="store_true", help="Create MR/PR")
    p_init.add_argument("--create-jira", help="Create linked JIRA in project")
    p_init.add_argument("--no-source-repo", action="store_true", help="Skip source resolution")
    p_init.add_argument("--auto-discover-repos", action="store_true", help="Auto-discover repos")
    p_init.add_argument("--max-secondary-repos", type=int, default=3, help="Max secondary repos")
    p_init.add_argument("--plugin-root", help="Plugin root directory")

    # step-done
    p_done = sub.add_parser("step-done", help="Record step completion")
    p_done.add_argument("ticket", help="JIRA ticket ID")
    p_done.add_argument("step_name", help="Name of the completed step")
    p_done.add_argument("--failed", action="store_true", help="Mark step as failed")
    p_done.add_argument(
        "--force",
        action="store_true",
        help="Auto-promote pending to in_progress before completing",
    )

    # prepare-step
    p_prepare = sub.add_parser(
        "prepare-step", help="Build agent dispatch instructions for a dispatch-eligible step"
    )
    p_prepare.add_argument("ticket", help="JIRA ticket ID")
    p_prepare.add_argument("step", help="Step name to prepare")
    p_prepare.add_argument(
        "--phase", type=int, default=None, help="Phase number for multi-phase steps"
    )

    # retry-step
    p_retry = sub.add_parser("retry-step", help="Reset a failed/stuck step and retry it")
    p_retry.add_argument("ticket", help="JIRA ticket ID")
    p_retry.add_argument("step_name", help="Name of the step to retry")

    # next
    p_next = sub.add_parser("next", help="Query next action (read-only)")
    p_next.add_argument("ticket", help="JIRA ticket ID")

    # status
    p_status = sub.add_parser("status", help="Query workflow status")
    p_status.add_argument("ticket", help="JIRA ticket ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    handlers = {
        "init": cmd_init,
        "step-done": cmd_step_done,
        "prepare-step": cmd_prepare_step,
        "retry-step": cmd_retry_step,
        "next": cmd_next,
        "status": cmd_status,
    }

    handlers[args.command](args)


if __name__ == "__main__":
    main()
