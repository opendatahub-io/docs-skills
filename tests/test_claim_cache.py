"""Tests for the tech-review claim cache (Stage 0: measurement, no gating).

Covers plan_extraction.py and the resolve_source_files helper it shares with
prepare_review.py. The behaviour under test is deliberately conservative: every
failure path must fall back to extracting everything, because a wrong plan
costs tokens while a missing claim costs correctness.
"""

import json
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "skills",
    "docs-workflow-tech-review",
    "scripts",
)
PLAN_SCRIPT = os.path.join(SCRIPTS_DIR, "plan_extraction.py")

sys.path.insert(0, SCRIPTS_DIR)

from plan_extraction import (  # noqa: E402
    claim_file_index,
    code_state_matches,
    snapshot_prior_iteration,
)
from prepare_review import resolve_source_files  # noqa: E402


def build_workspace(tmp_path, files=("a.adoc", "b.adoc"), mode="update-in-place"):
    """Create a minimal ticket workspace and return (base_path, draft paths)."""
    base = tmp_path / "ticket"
    writing = base / "writing"
    writing.mkdir(parents=True)
    (base / "technical-review").mkdir()

    drafts = tmp_path / "drafts"
    drafts.mkdir()
    paths = []
    for name in files:
        path = drafts / name
        path.write_text(f"= {name}\n\nThe default timeout is 30 seconds.\n")
        paths.append(str(path))

    sidecar = {"schema_version": 1, "step": "writing", "mode": mode, "files": paths}
    (writing / "step-result.json").write_text(json.dumps(sidecar))
    return base, paths


def write_claims(base, claims):
    path = base / "technical-review" / "claims-list.json"
    path.write_text(json.dumps(claims))
    return path


def run_plan(base, *extra):
    result = subprocess.run(
        [
            sys.executable,
            PLAN_SCRIPT,
            "--base-path",
            str(base),
            "--output-dir",
            str(base / "technical-review"),
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result.stdout


# --- resolve_source_files (shared with prepare_review) ----------------------


def test_resolve_source_files_uses_sidecar_list(tmp_path):
    base, paths = build_workspace(tmp_path)
    assert resolve_source_files(str(base)) == paths


def test_resolve_source_files_filters_non_draft_suffixes(tmp_path):
    base, paths = build_workspace(tmp_path)
    sidecar = json.loads((base / "writing" / "step-result.json").read_text())
    sidecar["files"].append(str(tmp_path / "drafts" / "_topic_map.yml"))
    (base / "writing" / "step-result.json").write_text(json.dumps(sidecar))
    # A topic map yields no claims, so hashing it would only add churn.
    assert resolve_source_files(str(base)) == paths


def test_resolve_source_files_globs_when_not_in_place(tmp_path):
    base, _ = build_workspace(tmp_path, mode="draft")
    (base / "writing" / "draft-one.adoc").write_text("= One\n")
    (base / "writing" / "notes.txt").write_text("ignored\n")
    resolved = resolve_source_files(str(base))
    assert [os.path.basename(p) for p in resolved] == ["draft-one.adoc"]


def test_resolve_source_files_missing_workspace_is_empty(tmp_path):
    assert resolve_source_files(str(tmp_path / "nope")) == []


# --- claim/file join --------------------------------------------------------


def test_claim_file_index_maps_basenames():
    index = claim_file_index(["/x/a.adoc", "/y/b.adoc"])
    assert index == {"a.adoc": "/x/a.adoc", "b.adoc": "/y/b.adoc"}


def test_claim_file_index_drops_ambiguous_basenames():
    # Claims record only a basename, so a duplicate cannot be attributed
    # safely. Dropping it makes the file re-extract rather than risk carrying
    # another file's verdict.
    index = claim_file_index(["/x/dup.adoc", "/y/dup.adoc", "/z/ok.adoc"])
    assert index == {"ok.adoc": "/z/ok.adoc"}


# --- code state -------------------------------------------------------------


def test_code_state_matches_requires_identical_known_state():
    assert code_state_matches({"/r": "abc"}, {"/r": "abc"})
    assert not code_state_matches({"/r": "abc"}, {"/r": "def"})
    assert not code_state_matches({"/r": "abc"}, {"/other": "abc"})
    assert not code_state_matches(None, {"/r": "abc"})


def test_code_state_unknown_never_matches():
    # An unreadable repo must force re-extraction, never a silent cache hit.
    assert not code_state_matches({"/r": "unknown"}, {"/r": "unknown"})


# --- snapshots --------------------------------------------------------------


def test_snapshot_copies_prior_iteration(tmp_path):
    out = tmp_path / "technical-review"
    out.mkdir()
    (out / "claims-list.json").write_text("[]")
    (out / "review.md").write_text("# review\n")
    assert snapshot_prior_iteration(out, 2) == ["claims-list.json", "review.md"]
    assert (out / "iteration-1" / "review.md").read_text() == "# review\n"


def test_snapshot_skips_missing_sources(tmp_path):
    out = tmp_path / "technical-review"
    out.mkdir()
    assert snapshot_prior_iteration(out, 2) is None
    assert not (out / "iteration-1").exists()


def test_snapshot_noop_on_first_iteration(tmp_path):
    out = tmp_path / "technical-review"
    out.mkdir()
    (out / "review.md").write_text("# review\n")
    assert snapshot_prior_iteration(out, 1) is None


# --- plan_extraction end to end --------------------------------------------


def test_report_only_reports_carry_without_gating(tmp_path):
    base, paths = build_workspace(tmp_path)
    write_claims(base, [{"id": "C001", "text": "t", "file": "a.adoc", "line": 3}])

    run_plan(base, "--iteration", "1", "--report-only")
    plan, _ = run_plan(base, "--iteration", "2", "--report-only")

    # Measured truthfully...
    assert plan["carried_claim_count"] == 1
    assert plan["carried_byte_share"] > 0
    # ...but the caller is still told to extract everything.
    assert plan["extract_all"] is True
    assert plan["invalidation_reason"] == "report_only"
    assert plan["files_to_extract"] == paths
    assert not (base / "technical-review" / "carried-claims.json").exists()


def test_gating_partitions_changed_and_unchanged(tmp_path):
    base, paths = build_workspace(tmp_path)
    write_claims(
        base,
        [
            {"id": "C001", "text": "t1", "file": "a.adoc", "line": 3},
            {"id": "C002", "text": "t2", "file": "b.adoc", "line": 3},
        ],
    )
    run_plan(base, "--iteration", "1", "--report-only")

    with open(paths[1], "a") as handle:
        handle.write("\nEdited.\n")

    plan, _ = run_plan(base, "--iteration", "2")
    assert plan["extract_all"] is False
    assert plan["files_to_extract"] == [paths[1]]
    assert plan["unchanged_files"] == [paths[0]]
    assert plan["carried_claim_count"] == 1

    carried = json.loads((base / "technical-review" / "carried-claims.json").read_text())
    assert carried == [{"id": "C001", "text": "t1", "file": "a.adoc", "line": 3}]


def test_first_iteration_extracts_everything(tmp_path):
    base, paths = build_workspace(tmp_path)
    plan, _ = run_plan(base, "--iteration", "1")
    assert plan["extract_all"] is True
    assert plan["invalidation_reason"] == "iteration_1"
    assert plan["files_to_extract"] == paths


def test_missing_manifest_extracts_everything(tmp_path):
    base, paths = build_workspace(tmp_path)
    plan, _ = run_plan(base, "--iteration", "2")
    assert plan["extract_all"] is True
    assert plan["invalidation_reason"] == "no_manifest"
    assert plan["files_to_extract"] == paths


def test_unreadable_manifest_extracts_everything(tmp_path):
    base, _ = build_workspace(tmp_path)
    run_plan(base, "--iteration", "1", "--report-only")
    (base / "technical-review" / "claims-manifest.json").write_text("{ not json")
    plan, _ = run_plan(base, "--iteration", "2")
    assert plan["invalidation_reason"] == "unreadable_manifest"
    assert plan["extract_all"] is True


def test_missing_prior_claims_extracts_everything(tmp_path):
    base, _ = build_workspace(tmp_path)
    write_claims(base, [{"id": "C001", "text": "t", "file": "a.adoc", "line": 3}])
    run_plan(base, "--iteration", "1", "--report-only")
    (base / "technical-review" / "claims-list.json").unlink()
    plan, _ = run_plan(base, "--iteration", "2")
    assert plan["invalidation_reason"] == "no_prior_claims"
    assert plan["extract_all"] is True


def test_code_state_change_extracts_everything(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t"}
    env.update(GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "one"],
        check=True,
        env=env,
    )

    base, _ = build_workspace(tmp_path)
    write_claims(base, [{"id": "C001", "text": "t", "file": "a.adoc", "line": 3}])
    run_plan(base, "--iteration", "1", "--report-only", "--repo", str(repo))

    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "two"],
        check=True,
        env=env,
    )
    plan, _ = run_plan(base, "--iteration", "2", "--repo", str(repo))
    assert plan["invalidation_reason"] == "code_state_changed"
    assert plan["extract_all"] is True
    assert plan["carried_claim_count"] == 0


def test_stale_intermediates_are_removed(tmp_path):
    base, _ = build_workspace(tmp_path)
    out = base / "technical-review"
    (out / "extracted-changed.json").write_text('[{"id": "stale"}]')
    run_plan(base, "--iteration", "1", "--report-only")
    # A failed extractor must not leave last iteration's output to be merged.
    assert not (out / "extracted-changed.json").exists()


def test_file_with_no_claims_is_never_cached_as_claim_free(tmp_path):
    base, paths = build_workspace(tmp_path)
    write_claims(base, [{"id": "C001", "text": "t", "file": "a.adoc", "line": 3}])
    run_plan(base, "--iteration", "1", "--report-only")

    manifest = json.loads((base / "technical-review" / "claims-manifest.json").read_text())
    assert paths[0] in manifest["files"]
    assert paths[1] not in manifest["files"]

    # b.adoc produced nothing, so it must be re-extracted rather than skipped.
    plan, _ = run_plan(base, "--iteration", "2")
    assert plan["files_to_extract"] == [paths[1]]


def test_stdout_never_contains_claim_text(tmp_path):
    base, _ = build_workspace(tmp_path)
    write_claims(
        base,
        [{"id": "C001", "text": "SECRET_CLAIM_TEXT", "file": "a.adoc", "line": 3}],
    )
    run_plan(base, "--iteration", "1", "--report-only")
    _, raw = run_plan(base, "--iteration", "2")
    assert "SECRET_CLAIM_TEXT" not in raw
