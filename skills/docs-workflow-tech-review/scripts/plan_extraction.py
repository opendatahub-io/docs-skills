#!/usr/bin/env python3
"""Plan which draft files the claims-extractor needs to read this iteration.

The tech-review loop re-extracts claims from every draft file on every
iteration. Because an LLM writes the claims, an unchanged file yields
differently-worded claims each pass (measured: ~20% reproducible), so the
carry-forward in incremental_claims.py misses and the claim is re-validated.
Worse, the reviewer's evidence base changes shape between iterations, and a
claim flagged in one pass can simply not be extracted in the next.

This script hashes each draft file and compares against a manifest written by
the previous iteration, so extraction can be limited to files that actually
changed and prior claims can be reused verbatim for the rest.

Stage 0 (--report-only) measures without changing behaviour: it writes the
manifest and reports how much *would* have been carried, while still telling
the caller to extract everything. Run it for at least one full pipeline
execution before enabling the gate.

Every failure degrades to extracting everything. A wrong plan costs tokens; a
missing claim costs correctness, so the safe direction is always more work.

stdout carries counts and paths only — never claim text — so claim details stay
out of the orchestrator's context (same discipline as incremental_claims.py).

Usage:
  plan_extraction.py --base-path <path> --output-dir <dir> --iteration <N> \
      [--repo <path>]... [--report-only]
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from prepare_review import resolve_source_files

MANIFEST_NAME = "claims-manifest.json"
MANIFEST_VERSION = 1
CARRIED_NAME = "carried-claims.json"
FRESH_NAME = "extracted-changed.json"
PLAN_NAME = "extraction-plan.json"
CLAIMS_LIST_NAME = "claims-list.json"
REVIEW_NAME = "review.md"

# Repos whose state cannot be determined are recorded as this sentinel. Its
# presence on either side of a comparison forces a full re-extraction: an
# unknown code state must never be treated as an unchanged one.
UNKNOWN_STATE = "unknown"


def claim_file_index(source_files):
    """Map the filenames claims carry back to resolved draft paths.

    The extractor is given absolute paths but records a bare filename in each
    claim's ``file`` field, so a basename is the only join key available.
    incremental_claims.py never noticed because it compares claims to claims,
    with both sides in the same form.

    Where two drafts share a basename the mapping is ambiguous, so those files
    are left out: their claims would otherwise be attributed to whichever file
    happened to be listed first, and a wrong attribution carries a stale
    verdict. Callers treat an unmapped file as changed.
    """
    by_base = {}
    for path in source_files:
        by_base.setdefault(Path(path).name, []).append(path)
    return {base: paths[0] for base, paths in by_base.items() if len(paths) == 1}


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (json.JSONDecodeError, OSError):
        return None


def file_hash(path):
    """SHA-256 of raw file bytes, or None if unreadable.

    Raw bytes, not normalized text: a false cache hit loses a claim, while a
    false miss only re-extracts a file.
    """
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def git_head(repo_path):
    """Return the repo's HEAD sha, or UNKNOWN_STATE if it cannot be read."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_STATE
    if result.returncode != 0:
        return UNKNOWN_STATE
    return result.stdout.strip() or UNKNOWN_STATE


def code_state(repo_paths):
    return {str(Path(r).resolve()): git_head(r) for r in repo_paths}


def code_state_matches(stored, current):
    """True only if both states are known, non-empty, and identical."""
    if not isinstance(stored, dict) or stored.keys() != current.keys():
        return False
    if UNKNOWN_STATE in stored.values() or UNKNOWN_STATE in current.values():
        return False
    return stored == current


def snapshot_prior_iteration(output_dir, iteration):
    """Copy the previous iteration's claims list and review before overwrite.

    Without this only terminal state survives a run, which makes the
    carry-forward rate impossible to measure after the fact. Missing sources
    are skipped: a first iteration has nothing to snapshot.
    """
    if iteration < 2:
        return None
    dest = output_dir / f"iteration-{iteration - 1}"
    copied = []
    for name in (CLAIMS_LIST_NAME, REVIEW_NAME):
        src = output_dir / name
        if src.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / name)
            copied.append(name)
    return copied or None


def snapshot_drafts(output_dir, iteration, source_files):
    """Copy the draft files as they stand at the start of this iteration.

    The hash diff answers "did this file change"; it cannot answer "how much of
    it changed", because a hash of the previous content is not the previous
    content. Diffing consecutive snapshots is the only way to recover that, and
    it decides whether block-level claim identity is worth building: if fix
    passes rewrite most of a changed file, no anchoring scheme can carry its
    claims forward.

    Runs on every iteration, the first included — that snapshot is the baseline
    the second is diffed against. Files are copied under their basename, which
    is how claims refer to them; a colliding basename gets a short digest of its
    full path so nothing is silently overwritten.
    """
    dest = output_dir / f"drafts-iter-{iteration}"
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in source_files:
        src = Path(path)
        if not src.is_file():
            continue
        target = dest / src.name
        if target.exists():
            digest = hashlib.sha256(str(path).encode()).hexdigest()[:8]
            target = dest / f"{src.stem}.{digest}{src.suffix}"
        try:
            shutil.copy2(src, target)
        except OSError:
            continue
        copied += 1
    return copied


def read_manifest(output_dir):
    """Return (files_map, stored_code_state, reason). reason is set on failure."""
    path = output_dir / MANIFEST_NAME
    if not path.is_file():
        return None, None, "no_manifest"
    data = load_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_VERSION:
        return None, None, "unreadable_manifest"
    files = data.get("files")
    if not isinstance(files, dict):
        return None, None, "unreadable_manifest"
    return files, data.get("code_state"), None


def write_manifest(output_dir, hashes, prior_files, current_state, claims, index):
    """Persist hashes plus the claim ids each file produced.

    Claim ids come from the current claims list where available; a file with no
    claims recorded gets no entry, so it is re-extracted next iteration rather
    than cached as permanently claim-free. That distinction matters: extraction
    genuinely drops a file's claims from time to time.
    """
    by_file = {}
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        path = index.get(claim.get("file"))
        if path:
            by_file.setdefault(path, []).append(claim.get("id"))

    files = {}
    for path, digest in hashes.items():
        if digest is None:
            continue
        ids = by_file.get(path)
        if ids:
            files[path] = {"hash": digest, "claim_ids": ids}
        elif isinstance(prior_files, dict) and path in prior_files:
            # Unchanged file we did not re-extract: keep what it produced before.
            files[path] = prior_files[path]

    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(
            {"schema_version": MANIFEST_VERSION, "code_state": current_state, "files": files},
            indent=2,
        )
    )
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-path", required=True, help="Workflow base path for the ticket")
    parser.add_argument("--output-dir", required=True, help="Tech-review output directory")
    parser.add_argument("--iteration", type=int, default=1, help="Review iteration (1-based)")
    parser.add_argument("--repo", action="append", default=[], help="Source repo path (repeatable)")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Measure and write the manifest, but still extract everything",
    )
    args = parser.parse_args()

    base_path = Path(args.base_path)
    if not base_path.is_dir():
        print(f"ERROR: base path not found: {base_path}", file=sys.stderr)
        return 1
    output_dir = Path(args.output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: cannot create output dir: {exc}", file=sys.stderr)
        return 1

    snapshot_prior_iteration(output_dir, args.iteration)

    source_files = resolve_source_files(str(base_path))
    snapshot_drafts(output_dir, args.iteration, source_files)
    hashes = {f: file_hash(f) for f in source_files}
    sizes = {f: (Path(f).stat().st_size if Path(f).is_file() else 0) for f in source_files}
    current_state = code_state(args.repo)

    prior_files, stored_state, reason = read_manifest(output_dir)
    prior_claims = load_json(output_dir / CLAIMS_LIST_NAME)

    if args.iteration < 2:
        reason = "iteration_1"
    elif reason is None and not code_state_matches(stored_state, current_state):
        reason = "code_state_changed"
    elif reason is None and not isinstance(prior_claims, list):
        reason = "no_prior_claims"

    # Partition regardless of the outcome: in report-only mode these counts are
    # the entire point, even though the caller is still told to extract all.
    index = claim_file_index(source_files)
    mapped = set(index.values())

    if reason is None:
        unchanged = [
            f
            for f in source_files
            # A file whose basename is ambiguous cannot have its claims
            # identified, so it is never treated as unchanged.
            if f in mapped
            and hashes[f] is not None
            and isinstance(prior_files.get(f), dict)
            and prior_files[f].get("hash") == hashes[f]
        ]
    else:
        unchanged = []
    unchanged_set = set(unchanged)
    changed = [f for f in source_files if f not in unchanged_set]

    carried = [
        c
        for c in (prior_claims or [])
        if isinstance(c, dict) and index.get(c.get("file")) in unchanged_set
    ]
    total_bytes = sum(sizes.values())
    carried_bytes = sum(sizes[f] for f in unchanged)

    gate_off = args.report_only or reason is not None
    if args.report_only:
        reason = "report_only"

    # Stale intermediates from a prior iteration must never survive into this
    # one: a failed extractor would otherwise leave a file that merges as if it
    # were fresh output.
    for name in (CARRIED_NAME, FRESH_NAME):
        (output_dir / name).unlink(missing_ok=True)

    if not gate_off:
        (output_dir / CARRIED_NAME).write_text(json.dumps(carried, indent=2))

    write_manifest(output_dir, hashes, prior_files, current_state, prior_claims, index)

    plan = {
        "extract_all": gate_off,
        "files_to_extract": source_files if gate_off else changed,
        "unchanged_files": unchanged,
        "carried_claim_count": len(carried),
        "changed_file_count": len(changed),
        "unchanged_file_count": len(unchanged),
        "carried_byte_share": round(carried_bytes / total_bytes, 4) if total_bytes else 0.0,
        "invalidation_reason": reason,
    }

    # Persist the plan so write_step_result.py can fold the carry-forward
    # counters into the step sidecar. Without a durable copy the numbers exist
    # only on stdout, and the carry-forward rate stays unmeasurable across runs
    # — the exact gap that made this work necessary in the first place.
    (output_dir / PLAN_NAME).write_text(json.dumps(plan, indent=2))

    json.dump(plan, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
