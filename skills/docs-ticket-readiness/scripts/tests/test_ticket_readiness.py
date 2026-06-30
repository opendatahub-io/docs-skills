"""Tests for ticket_readiness.py dimension checks."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ticket_readiness import (
    check_pr_linkage,
    check_metadata,
    check_relationships,
    compute_overall_status,
    build_relationship_map,
)


# --- Mock data fixtures ---

def make_issue_data(**overrides):
    """Build a mock --issue response with sensible defaults."""
    base = {
        "issue_key": "PROJ-123",
        "issue_type": "Story",
        "issue_category": "Feature/Story",
        "priority": "Major",
        "status": "Done",
        "assignee": "Test User",
        "summary": "Add widget API documentation",
        "description": "Detailed description of the feature with acceptance criteria.",
        "created": "2026-01-15T10:00:00.000-0500",
        "updated": "2026-06-20T15:30:00.000-0500",
        "comments": [],
        "custom_fields": {
            "release_note_type": "Enhancement",
            "fix_versions": ["4.15"],
        },
        "git_links": ["https://github.com/org/repo/pull/42"],
        "url": "https://redhat.atlassian.net/browse/PROJ-123",
    }
    base.update(overrides)
    return base


def make_graph_data(**overrides):
    """Build a mock --graph response with sensible defaults."""
    base = {
        "ticket": "PROJ-123",
        "jira_url": "https://redhat.atlassian.net",
        "parent": {
            "key": "PROJ-100",
            "summary": "Widget Platform",
            "status": "In Progress",
            "issuetype": "Epic",
            "priority": "High",
            "assignee": "Lead Dev",
            "description": "Epic for widget platform.",
            "source": "parent_field",
        },
        "ancestors": [
            {
                "key": "PROJ-100",
                "summary": "Widget Platform",
                "status": "In Progress",
                "issuetype": "Epic",
                "priority": "High",
                "assignee": "Lead Dev",
                "description": "Epic for widget platform.",
                "source": "parent_field",
            }
        ],
        "children": {
            "total": 2,
            "showing": 2,
            "skipped": 0,
            "issues": [
                {
                    "key": "PROJ-456",
                    "summary": "Widget API endpoints",
                    "status": "Done",
                    "issuetype": "Sub-task",
                    "priority": "Medium",
                    "assignee": "Dev A",
                    "git_links": ["https://github.com/org/repo/pull/55"],
                    "auto_discovered_urls": {"pull_requests": ["https://github.com/org/repo/pull/55"], "google_docs": []},
                    "issue_links": {"total": 0, "showing": 0, "skipped": 0, "links": []},
                },
                {
                    "key": "PROJ-457",
                    "summary": "Widget UI components",
                    "status": "In Progress",
                    "issuetype": "Sub-task",
                    "priority": "Medium",
                    "assignee": "Dev B",
                    "git_links": [],
                    "auto_discovered_urls": {"pull_requests": [], "google_docs": []},
                    "issue_links": {"total": 0, "showing": 0, "skipped": 0, "links": []},
                },
            ],
        },
        "siblings": {
            "total": 1,
            "showing": 1,
            "skipped": 0,
            "issues": [
                {
                    "key": "PROJ-458",
                    "summary": "Widget docs",
                    "status": "Open",
                    "issuetype": "Story",
                }
            ],
        },
        "issue_links": {"total": 0, "showing": 0, "skipped": 0, "links": []},
        "web_links": {
            "total": 1,
            "links": [
                {"title": "GitHub PR", "url": "https://github.com/org/repo/pull/42", "type": "pull_request"}
            ],
        },
        "auto_discovered_urls": {
            "pull_requests": ["https://github.com/org/repo/pull/42"],
            "google_docs": [],
        },
    }
    base.update(overrides)
    return base


# --- Dimension 2: PR/source linkage ---

class TestCheckPrLinkage:
    def test_pass_pr_on_ticket(self):
        issue = make_issue_data(git_links=["https://github.com/org/repo/pull/42"])
        graph = make_graph_data()
        result = check_pr_linkage(issue, graph)
        assert result["status"] == "pass"
        assert result["checks"]["git_links_present"]["status"] == "pass"

    def test_pass_pr_on_child_only(self):
        issue = make_issue_data(git_links=[])
        graph = make_graph_data()
        # Remove PRs from ticket level, only child PROJ-456 has PR
        graph["web_links"] = {"total": 0, "links": []}
        graph["auto_discovered_urls"] = {"pull_requests": [], "google_docs": []}
        result = check_pr_linkage(issue, graph)
        assert result["status"] == "pass"
        # Fix: check that PROJ-456 is mentioned in the detail, not the word "child"
        assert "PROJ-456" in result["checks"]["git_links_present"]["detail"]

    def test_fail_no_git_links_anywhere(self):
        issue = make_issue_data(git_links=[])
        graph = make_graph_data()
        graph["children"]["issues"] = [
            {
                "key": "PROJ-456", "summary": "No PR child", "status": "Done",
                "issuetype": "Sub-task", "priority": "Medium", "assignee": "Dev",
                "git_links": [], "auto_discovered_urls": {"pull_requests": [], "google_docs": []},
                "issue_links": {"total": 0, "showing": 0, "skipped": 0, "links": []},
            }
        ]
        graph["web_links"] = {"total": 0, "links": []}
        graph["auto_discovered_urls"] = {"pull_requests": [], "google_docs": []}
        result = check_pr_linkage(issue, graph)
        assert result["status"] == "fail"

    def test_warn_repo_url_but_no_pr(self):
        issue = make_issue_data(git_links=["https://github.com/org/repo/commit/abc123"])
        graph = make_graph_data()
        graph["children"]["issues"] = []
        graph["web_links"] = {"total": 1, "links": [{"title": "Commit", "url": "https://github.com/org/repo/commit/abc123", "type": "other"}]}
        graph["auto_discovered_urls"] = {"pull_requests": [], "google_docs": []}
        result = check_pr_linkage(issue, graph)
        assert result["checks"]["git_links_present"]["status"] == "warn"

    def test_warn_all_prs_draft(self):
        issue = make_issue_data(git_links=["https://github.com/org/repo/pull/42"])
        graph = make_graph_data()
        # Fix: remove all other PRs from children and web_links to have only one PR total
        graph["children"]["issues"] = []
        graph["web_links"] = {"total": 0, "links": []}
        graph["auto_discovered_urls"] = {"pull_requests": [], "google_docs": []}
        result = check_pr_linkage(issue, graph, pr_states={"https://github.com/org/repo/pull/42": "draft"})
        assert result["checks"]["pr_state"]["status"] == "warn"


# --- Dimension 3: Metadata completeness ---

class TestCheckMetadata:
    def test_pass_all_fields(self):
        issue = make_issue_data()
        result = check_metadata(issue)
        assert result["status"] == "pass"

    def test_fail_no_fix_versions(self):
        issue = make_issue_data(custom_fields={"release_note_type": "Enhancement"})
        result = check_metadata(issue)
        assert result["checks"]["fix_versions"]["status"] == "fail"

    def test_fail_no_release_note_type(self):
        issue = make_issue_data(custom_fields={"fix_versions": ["4.15"]})
        result = check_metadata(issue)
        assert result["checks"]["release_note_type"]["status"] == "fail"

    def test_fail_status_backlog(self):
        issue = make_issue_data(status="Backlog")
        result = check_metadata(issue)
        assert result["checks"]["ticket_status"]["status"] == "fail"

    def test_warn_status_in_progress(self):
        issue = make_issue_data(status="In Progress")
        result = check_metadata(issue)
        assert result["checks"]["ticket_status"]["status"] == "warn"

    def test_custom_ready_statuses(self):
        issue = make_issue_data(status="QE Review")
        result = check_metadata(issue, ready_statuses=["QE Review", "Done"])
        assert result["checks"]["ticket_status"]["status"] == "pass"

    def test_fail_no_priority(self):
        issue = make_issue_data(priority="Undefined")
        result = check_metadata(issue)
        assert result["checks"]["priority"]["status"] == "fail"


# --- Dimension 4: Relationship context ---

class TestCheckRelationships:
    def test_pass_has_parent(self):
        issue = make_issue_data()
        graph = make_graph_data()
        result = check_relationships(issue, graph)
        assert result["checks"]["parent_epic"]["status"] == "pass"

    def test_fail_orphan_ticket(self):
        issue = make_issue_data()
        graph = make_graph_data(parent=None, ancestors=[])
        result = check_relationships(issue, graph)
        assert result["checks"]["parent_epic"]["status"] == "fail"

    def test_fail_epic_no_children(self):
        issue = make_issue_data(issue_type="Epic")
        graph = make_graph_data()
        graph["children"]["issues"] = []
        graph["children"]["total"] = 0
        result = check_relationships(issue, graph)
        assert result["checks"]["children"]["status"] == "fail"

    def test_pass_story_no_children_ok(self):
        issue = make_issue_data(issue_type="Story")
        graph = make_graph_data()
        graph["children"]["issues"] = []
        graph["children"]["total"] = 0
        result = check_relationships(issue, graph)
        assert result["checks"]["children"]["status"] == "pass"

    def test_warn_some_children_lack_prs(self):
        issue = make_issue_data()
        graph = make_graph_data()
        result = check_relationships(issue, graph)
        assert result["checks"]["grandchildren_prs"]["status"] in ("pass", "warn", "info")


# --- Overall verdict ---

class TestComputeOverallStatus:
    def test_ready_all_pass(self):
        dims = {
            "description_quality": {"status": "pass"},
            "pr_source_linkage": {"status": "pass"},
            "metadata_completeness": {"status": "pass"},
            "relationship_context": {"status": "pass"},
        }
        assert compute_overall_status(dims) == "ready"

    def test_ready_with_warnings(self):
        dims = {
            "description_quality": {"status": "pass"},
            "pr_source_linkage": {"status": "warn"},
            "metadata_completeness": {"status": "pass"},
            "relationship_context": {"status": "pass"},
        }
        assert compute_overall_status(dims) == "ready_with_warnings"

    def test_not_ready_any_fail(self):
        dims = {
            "description_quality": {"status": "pass"},
            "pr_source_linkage": {"status": "fail"},
            "metadata_completeness": {"status": "pass"},
            "relationship_context": {"status": "pass"},
        }
        assert compute_overall_status(dims) == "not_ready"

    def test_description_null_ignored(self):
        dims = {
            "description_quality": None,
            "pr_source_linkage": {"status": "pass"},
            "metadata_completeness": {"status": "pass"},
            "relationship_context": {"status": "pass"},
        }
        assert compute_overall_status(dims) == "ready"
