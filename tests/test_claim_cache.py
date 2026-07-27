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
from pathlib import Path

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


# --- merge_extraction (Stage 1) ---------------------------------------------

MERGE_SCRIPT = os.path.join(SCRIPTS_DIR, "merge_extraction.py")

from merge_extraction import id_number, renumber  # noqa: E402


def run_merge(base, *extra):
    result = subprocess.run(
        [
            sys.executable,
            MERGE_SCRIPT,
            "--base-path",
            str(base),
            "--output-dir",
            str(base / "technical-review"),
            *extra,
        ],
        capture_output=True,
        text=True,
    )
    return result


def write_fresh(base, claims):
    (base / "technical-review" / "extracted-changed.json").write_text(json.dumps(claims))


def test_id_number_parses_every_observed_format():
    # All three have come out of the identical extractor prompt.
    assert id_number("claim-1") == 1
    assert id_number("C001") == 1
    assert id_number("B042") == 42
    assert id_number("17") == 17
    assert id_number("no-digits") == 0
    assert id_number(None) == 0


def test_renumber_discards_agent_ids():
    fresh = [{"id": "claim-1", "text": "a"}, {"id": "C001", "text": "b"}]
    out = renumber(fresh, 5)
    assert [c["id"] for c in out] == ["C005", "C006"]
    assert [c["text"] for c in out] == ["a", "b"]


def test_merge_renumbers_fresh_past_carried_ids(tmp_path):
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
    run_plan(base, "--iteration", "2")

    # The extractor returns ids that collide with the carried claim's id.
    write_fresh(base, [{"id": "C001", "text": "fresh", "file": "b.adoc", "line": 9}])
    result = run_merge(base)
    assert result.returncode == 0, result.stderr

    claims = json.loads((base / "technical-review" / "claims-list.json").read_text())
    ids = [c["id"] for c in claims]
    assert ids == ["C001", "C002"], ids
    assert len(set(ids)) == len(ids), "collision would misattribute a verdict"
    # The carried claim keeps its identity; the fresh one was renumbered.
    assert claims[0]["text"] == "t1"
    assert claims[1]["text"] == "fresh"


def test_merge_fails_loudly_when_extractor_produced_nothing(tmp_path):
    base, paths = build_workspace(tmp_path)
    write_claims(base, [{"id": "C001", "text": "t1", "file": "a.adoc", "line": 3}])
    run_plan(base, "--iteration", "1", "--report-only")
    with open(paths[1], "a") as handle:
        handle.write("\nEdited.\n")
    run_plan(base, "--iteration", "2")

    # No extracted-changed.json written at all.
    result = run_merge(base)
    assert result.returncode == 1
    assert "Refusing" in result.stderr
    # Must not leave a claims list that silently dropped the changed file.
    stale = json.loads((base / "technical-review" / "claims-list.json").read_text())
    assert stale == [{"id": "C001", "text": "t1", "file": "a.adoc", "line": 3}]


def test_merge_keeps_carried_manifest_entries(tmp_path):
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
    run_plan(base, "--iteration", "2")
    write_fresh(base, [{"id": "x", "text": "fresh", "file": "b.adoc", "line": 9}])
    run_merge(base)

    manifest = json.loads((base / "technical-review" / "claims-manifest.json").read_text())
    # Unchanged file keeps its entry, changed file gets a refreshed one.
    assert paths[0] in manifest["files"]
    assert paths[1] in manifest["files"]
    assert manifest["files"][paths[1]]["claim_ids"] == ["C002"]


def test_merge_omits_files_that_returned_no_claims(tmp_path):
    base, paths = build_workspace(tmp_path)
    write_claims(base, [{"id": "C001", "text": "t1", "file": "a.adoc", "line": 3}])
    run_plan(base, "--iteration", "1", "--report-only")
    with open(paths[1], "a") as handle:
        handle.write("\nEdited.\n")
    run_plan(base, "--iteration", "2")

    # Extractor read b.adoc but produced nothing for it.
    write_fresh(base, [])
    assert run_merge(base).returncode == 0
    manifest = json.loads((base / "technical-review" / "claims-manifest.json").read_text())
    assert paths[1] not in manifest["files"], "would cache the file as claim-free"


def test_end_to_end_carry_forward_reaches_incremental_claims(tmp_path):
    """The whole point: a carried claim keeps its prior verdict.

    Drives the real scripts rather than mocks — if the join or the verbatim
    copy regresses, carry-forward silently returns to zero and only this test
    notices.
    """
    base, paths = build_workspace(tmp_path)
    out = base / "technical-review"
    write_claims(
        base,
        [
            {"id": "C001", "text": "unchanged claim", "file": "a.adoc", "line": 3},
            {"id": "C002", "text": "stale claim", "file": "b.adoc", "line": 3},
        ],
    )
    run_plan(base, "--iteration", "1", "--report-only")

    # Prior validation, as merge_verdicts.py would have written it.
    (out / "claim-validation.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "id": "C001",
                        "text": "unchanged claim",
                        "file": "a.adoc",
                        "line": 3,
                        "verdict": "unsupported",
                        "evidence": "contradicts config.go:12",
                    }
                ],
                "summary": {},
            }
        )
    )

    with open(paths[1], "a") as handle:
        handle.write("\nEdited.\n")
    run_plan(base, "--iteration", "2")
    write_fresh(base, [{"id": "whatever", "text": "reworded claim", "file": "b.adoc", "line": 9}])
    assert run_merge(base).returncode == 0

    subprocess.run(
        [
            sys.executable,
            os.path.join(SCRIPTS_DIR, "incremental_claims.py"),
            "--claims-list",
            str(out / "claims-list.json"),
            "--prior-validation",
            str(out / "claim-validation.json"),
            "--output-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    carryover = json.loads((out / "batch-verdict-carryover.json").read_text())
    to_validate = json.loads((out / "claims-to-validate.json").read_text())

    # The unchanged file's claim keeps its verdict without re-validation...
    assert len(carryover) == 1
    assert carryover[0]["claim_id"] == "C001"
    assert carryover[0]["verdict"] == "unsupported"
    # ...and only the changed file's claim is re-validated.
    assert [c["file"] for c in to_validate] == ["b.adoc"]


# --- sidecar instrumentation ------------------------------------------------


def _load_tech_review_step_result():
    """Load this skill's write_step_result by path.

    Several skills ship a module of that name, and conftest puts all their
    script dirs on sys.path — a bare import binds whichever one is imported
    first and poisons sys.modules for the other suites.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "tech_review_write_step_result",
        os.path.join(SCRIPTS_DIR, "write_step_result.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


read_claim_cache = _load_tech_review_step_result().read_claim_cache


def test_read_claim_cache_extracts_counters_only(tmp_path):
    plan = tmp_path / "extraction-plan.json"
    plan.write_text(
        json.dumps(
            {
                "extract_all": False,
                "files_to_extract": ["/x/a.adoc"],
                "unchanged_files": ["/x/b.adoc"],
                "carried_claim_count": 47,
                "changed_file_count": 1,
                "unchanged_file_count": 1,
                "carried_byte_share": 0.61,
                "invalidation_reason": None,
            }
        )
    )
    cache = read_claim_cache(str(plan))
    assert cache["carried_claim_count"] == 47
    assert cache["carried_byte_share"] == 0.61
    # File lists stay out of the sidecar the orchestrator reads every step.
    assert "files_to_extract" not in cache
    assert "unchanged_files" not in cache


def test_read_claim_cache_tolerates_missing_or_broken_plan(tmp_path):
    # Instrumentation must never fail the tech-review step.
    assert read_claim_cache("") is None
    assert read_claim_cache(str(tmp_path / "nope.json")) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json")
    assert read_claim_cache(str(bad)) is None
    empty = tmp_path / "empty.json"
    empty.write_text("{}")
    assert read_claim_cache(str(empty)) is None


# --- draft snapshots (Phase 2 measurement input) ----------------------------

from plan_extraction import snapshot_drafts  # noqa: E402


def test_draft_snapshot_taken_on_every_iteration(tmp_path):
    base, paths = build_workspace(tmp_path)
    run_plan(base, "--iteration", "1", "--report-only")
    # Iteration 1 is the baseline the second is diffed against, so it must be
    # captured even though there is nothing to compare it with yet.
    snap1 = base / "technical-review" / "drafts-iter-1"
    assert sorted(p.name for p in snap1.iterdir()) == ["a.adoc", "b.adoc"]

    with open(paths[1], "a") as handle:
        handle.write("\nEdited.\n")
    run_plan(base, "--iteration", "2")

    snap2 = base / "technical-review" / "drafts-iter-2"
    assert (snap1 / "a.adoc").read_text() == (snap2 / "a.adoc").read_text()
    assert (snap1 / "b.adoc").read_text() != (snap2 / "b.adoc").read_text()


def test_draft_snapshot_measures_edit_size(tmp_path):
    """The snapshot exists to answer 'how much of the file changed'."""
    base, paths = build_workspace(tmp_path)
    Path(paths[0]).write_text("\n".join(f"line {i}" for i in range(20)) + "\n")
    run_plan(base, "--iteration", "1", "--report-only")

    lines = Path(paths[0]).read_text().splitlines()
    lines[3] = "line 3 corrected"
    Path(paths[0]).write_text("\n".join(lines) + "\n")
    run_plan(base, "--iteration", "2")

    before = (base / "technical-review" / "drafts-iter-1" / "a.adoc").read_text().splitlines()
    after = (base / "technical-review" / "drafts-iter-2" / "a.adoc").read_text().splitlines()
    changed = sum(1 for x, y in zip(before, after) if x != y)
    assert changed == 1
    assert changed / len(before) < 0.1


def test_draft_snapshot_does_not_overwrite_colliding_basenames(tmp_path):
    out = tmp_path / "technical-review"
    out.mkdir()
    one = tmp_path / "x" / "dup.adoc"
    two = tmp_path / "y" / "dup.adoc"
    for path, body in ((one, "from x\n"), (two, "from y\n")):
        path.parent.mkdir(parents=True)
        path.write_text(body)

    assert snapshot_drafts(out, 1, [str(one), str(two)]) == 2
    bodies = sorted(p.read_text() for p in (out / "drafts-iter-1").iterdir())
    assert bodies == ["from x\n", "from y\n"]


def test_draft_snapshot_skips_missing_files(tmp_path):
    out = tmp_path / "technical-review"
    out.mkdir()
    real = tmp_path / "real.adoc"
    real.write_text("content\n")
    assert snapshot_drafts(out, 1, [str(real), str(tmp_path / "gone.adoc")]) == 1
