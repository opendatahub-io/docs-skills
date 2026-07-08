"""Tests for skills/action-comments/scripts/action_comments.py."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from action_comments import (
    build_sidecar,
    classify_outdated,
    is_editable_path,
    list_artifacts,
    plan_checkout,
    resolve_mode,
    select_workspace,
    validate_pr_url,
)
from schema_helpers import validate_sidecar


class TestResolveMode:
    def test_no_flags_no_env(self):
        assert resolve_mode(False, False, {}) == {
            "ci_mode": False,
            "reason": "no CI flag or CI env var",
        }

    def test_force_ci_flag(self):
        assert resolve_mode(True, False, {})["ci_mode"] is True

    def test_force_no_ci_beats_env(self):
        result = resolve_mode(False, True, {"CI": "true"})
        assert result["ci_mode"] is False

    def test_conflicting_flags_raise(self):
        with pytest.raises(ValueError):
            resolve_mode(True, True, {})

    @pytest.mark.parametrize("var", ["CI", "GITHUB_ACTIONS", "GITLAB_CI"])
    def test_ci_env_vars_detected(self, var):
        result = resolve_mode(False, False, {var: "true"})
        assert result["ci_mode"] is True
        assert var in result["reason"]

    @pytest.mark.parametrize("val", ["false", "0", ""])
    def test_falsey_env_not_ci(self, val):
        assert resolve_mode(False, False, {"CI": val})["ci_mode"] is False


class TestValidatePrUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/o/r/pull/1",
            "https://gitlab.com/g/s/p/merge_requests/9",
            "https://gitlab.example.com/a/b/c/d/merge_requests/12",
        ],
    )
    def test_valid(self, url):
        assert validate_pr_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            None,
            "",
            "https://github.com/o/r/issues/1",
            "ftp://github.com/o/r/pull/1",
            "github.com/o/r/pull/1",
        ],
    )
    def test_invalid(self, url):
        assert validate_pr_url(url) is False


class TestPlanCheckout:
    def test_already_on_target_branch(self):
        assert plan_checkout("feat/x", "feat/x") == {
            "head_ref": "feat/x",
            "on_target_branch": True,
        }

    def test_different_branch(self):
        result = plan_checkout("feat/x", "main")
        assert result["on_target_branch"] is False
        assert result["head_ref"] == "feat/x"

    @pytest.mark.parametrize(
        "ref",
        [
            "",
            "feat/x;rm -rf",
            "feat/x$(whoami)",
            "feat x",
            "feat/x`id`",
        ],
    )
    def test_unsafe_ref_raises(self, ref):
        with pytest.raises(ValueError):
            plan_checkout(ref, "main")

    @pytest.mark.parametrize("ref", ["main", "release-1.2.3", "user/feat_branch", "v1.0"])
    def test_safe_refs_accepted(self, ref):
        assert plan_checkout(ref, "other")["head_ref"] == ref


class TestSelectWorkspace:
    def test_base_path_wins(self):
        assert select_workspace("/repo", "/explicit", "url") == "/explicit"

    def test_no_repo_root(self):
        assert select_workspace(None, None, None) is None

    def test_no_agent_workspace(self, tmp_path):
        assert select_workspace(str(tmp_path), None, None) is None

    def test_single_ticket(self, tmp_path):
        aw = tmp_path / ".agent_workspace" / "PROJ-1"
        aw.mkdir(parents=True)
        assert select_workspace(str(tmp_path), None, None) == str(aw)

    def test_empty_workspace(self, tmp_path):
        (tmp_path / ".agent_workspace").mkdir()
        assert select_workspace(str(tmp_path), None, None) is None

    def test_multiple_tickets_match_by_url(self, tmp_path):
        aw = tmp_path / ".agent_workspace"
        t1 = aw / "PROJ-1" / "create-merge-request"
        t2 = aw / "PROJ-2" / "create-merge-request"
        t1.mkdir(parents=True)
        t2.mkdir(parents=True)
        (t1 / "step-result.json").write_text(json.dumps({"url": "https://x/pull/1"}))
        (t2 / "step-result.json").write_text(json.dumps({"url": "https://x/pull/2"}))
        assert select_workspace(str(tmp_path), None, "https://x/pull/2") == str(aw / "PROJ-2")

    def test_multiple_tickets_no_match(self, tmp_path):
        aw = tmp_path / ".agent_workspace"
        (aw / "PROJ-1").mkdir(parents=True)
        (aw / "PROJ-2").mkdir(parents=True)
        assert select_workspace(str(tmp_path), None, "https://x/pull/9") is None


class TestListArtifacts:
    def test_none_workspace(self):
        result = list_artifacts(None)
        assert result["workspace"] is None
        assert result["artifacts"] == {}

    def test_detects_present_artifacts(self, tmp_path):
        (tmp_path / "requirements").mkdir()
        (tmp_path / "requirements" / "requirements.md").write_text("x")
        result = list_artifacts(str(tmp_path))
        assert result["artifacts"]["requirements"] is True
        assert result["artifacts"]["code_analysis"] is False

    def test_source_repo_resolved(self, tmp_path):
        repo = tmp_path / "cloned"
        repo.mkdir()
        (tmp_path / "source.yaml").write_text(f"repo_path: {repo}\n")
        result = list_artifacts(str(tmp_path))
        assert result["source_repo"] == str(repo)

    def test_source_repo_missing_dir_not_reported(self, tmp_path):
        (tmp_path / "source.yaml").write_text("repo_path: /does/not/exist\n")
        assert list_artifacts(str(tmp_path))["source_repo"] is None


class TestClassifyOutdated:
    def test_position_outdated_signal(self, tmp_path):
        assert classify_outdated({"position_outdated": True, "path": "a.md"}, str(tmp_path))

    def test_missing_file_is_outdated(self, tmp_path):
        assert classify_outdated({"path": "gone.md"}, str(tmp_path))

    def test_existing_file_not_outdated(self, tmp_path):
        (tmp_path / "a.md").write_text("hi")
        assert classify_outdated({"path": "a.md"}, str(tmp_path)) is False

    def test_no_path_not_outdated(self, tmp_path):
        assert classify_outdated({}, str(tmp_path)) is False

    def test_traversal_path_treated_as_outdated(self, tmp_path):
        # A forge-supplied path escaping repo_root must not probe outside it.
        assert classify_outdated({"path": "../../../../etc/passwd"}, str(tmp_path)) is True

    def test_traversal_path_to_real_file_still_skipped(self, tmp_path):
        outside = tmp_path.parent / "secret.txt"
        outside.write_text("x")
        rel = f"../{outside.name}"
        assert classify_outdated({"path": rel}, str(tmp_path)) is True


class TestIsEditablePath:
    @pytest.mark.parametrize(
        "path",
        [
            "docs/guide.adoc",
            "modules/proc_setup.adoc",
            "README.md",
            "assemblies/assembly_install.adoc",
        ],
    )
    def test_allows_doc_paths(self, path, tmp_path):
        allowed, _ = is_editable_path(path, str(tmp_path))
        assert allowed is True

    @pytest.mark.parametrize(
        "path",
        [
            "../../../etc/passwd",  # traversal
            "/etc/passwd",  # absolute escape
            ".gitlab-ci.yml",  # CI config (dotfile)
            ".github/workflows/test.yml",  # CI workflow (dot dir)
            ".git/config",  # git internals
            ".env",  # secrets
            "docs/../.github/workflows/x.yml",  # traversal into CI
            "Makefile",  # code-exec entrypoint
            "Dockerfile",
            "Jenkinsfile",
            "",  # empty
        ],
    )
    def test_blocks_sensitive_and_escaping_paths(self, path, tmp_path):
        allowed, reason = is_editable_path(path, str(tmp_path))
        assert allowed is False
        assert reason

    def test_shape_and_fields(self):
        s = build_sidecar(
            ticket="PROJ-1",
            ci_mode=True,
            comments_resolved=2,
            comments_skipped=1,
            comments_outdated=3,
            comments_replied=2,
            files_modified=["a.md"],
            now="2026-07-07T00:00:00Z",
        )
        assert s["schema_version"] == 1
        assert s["step"] == "action-comments"
        assert s["ticket"] == "PROJ-1"
        assert s["ci_mode"] is True
        assert s["comments_resolved"] == 2
        assert s["files_modified"] == ["a.md"]
        assert s["completed_at"] == "2026-07-07T00:00:00Z"

    def test_default_timestamp_is_iso_z(self):
        s = build_sidecar("T", False, 0, 0, 0, 0, [])
        assert s["completed_at"].endswith("Z")

    def test_conforms_to_output_schema(self):
        s = build_sidecar("PROJ-1", True, 2, 1, 3, 2, ["a.md"])
        validate_sidecar("action-comments", s)
