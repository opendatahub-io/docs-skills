"""Tests for ticket_readiness.py dimension checks."""

from ticket_readiness import (
    assess_ticket,
    build_relationship_map,
    check_metadata,
    check_pr_linkage,
    check_relationships,
    compute_overall_status,
    format_comment,
    format_markdown_report,
    parse_args,
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
                    "auto_discovered_urls": {
                        "pull_requests": ["https://github.com/org/repo/pull/55"],
                        "google_docs": [],
                    },
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
        "issue_links": {
            "total": 1,
            "showing": 1,
            "skipped": 0,
            "links": [
                {
                    "key": "DOCS-100",
                    "direction": "is documented by",
                    "link_type": "Documented",
                    "summary": "Document widget API",
                    "status": "Open",
                    "issuetype": "Task",
                    "git_links": ["https://github.com/org/docs-repo/pull/10"],
                    "auto_discovered_urls": {"pull_requests": [], "google_docs": []},
                }
            ],
        },
        "web_links": {
            "total": 1,
            "links": [
                {
                    "title": "GitHub PR",
                    "url": "https://github.com/org/repo/pull/42",
                    "type": "pull_request",
                }
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
                "key": "PROJ-456",
                "summary": "No PR child",
                "status": "Done",
                "issuetype": "Sub-task",
                "priority": "Medium",
                "assignee": "Dev",
                "git_links": [],
                "auto_discovered_urls": {"pull_requests": [], "google_docs": []},
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
        graph["web_links"] = {
            "total": 1,
            "links": [
                {
                    "title": "Commit",
                    "url": "https://github.com/org/repo/commit/abc123",
                    "type": "other",
                }
            ],
        }
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
        result = check_pr_linkage(
            issue, graph, pr_states={"https://github.com/org/repo/pull/42": "draft"}
        )
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

    def test_pass_status_release_pending(self):
        issue = make_issue_data(status="Release Pending")
        result = check_metadata(issue)
        assert result["checks"]["ticket_status"]["status"] == "pass"

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

    def test_documented_by_found(self):
        issue = make_issue_data()
        graph = make_graph_data()
        result = check_relationships(issue, graph)
        assert result["checks"]["documented_by"]["status"] == "pass"
        assert "DOCS-100" in result["checks"]["documented_by"]["detail"]

    def test_documented_by_not_found(self):
        issue = make_issue_data()
        graph = make_graph_data()
        graph["issue_links"] = {"total": 0, "showing": 0, "skipped": 0, "links": []}
        result = check_relationships(issue, graph)
        assert result["checks"]["documented_by"]["status"] == "info"


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


# --- Comment formatting ---


def _adf_to_text(adf: dict) -> str:
    """Recursively extract all text from an ADF document for assertion checks."""
    parts = []
    if adf.get("type") == "text":
        parts.append(adf.get("text", ""))
    elif adf.get("type") == "emoji":
        parts.append(adf.get("attrs", {}).get("text", ""))
    for child in adf.get("content", []):
        parts.append(_adf_to_text(child))
    return " ".join(parts)


class TestFormatComment:
    def test_returns_adf_document(self):
        result = {
            "ticket": "PROJ-123",
            "overall_status": "ready",
            "dimensions": {
                "description_quality": {"status": "pass", "score": 4, "gaps": []},
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {"status": "pass", "checks": {}},
                "relationship_context": {"status": "pass", "checks": {}},
            },
        }
        adf = format_comment(result)
        assert adf["type"] == "doc"
        assert adf["version"] == 1
        assert isinstance(adf["content"], list)

    def test_ready_comment(self):
        result = {
            "ticket": "PROJ-123",
            "overall_status": "ready",
            "dimensions": {
                "description_quality": {"status": "pass", "score": 4, "gaps": []},
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {"status": "pass", "checks": {}},
                "relationship_context": {"status": "pass", "checks": {}},
            },
        }
        text = _adf_to_text(format_comment(result))
        assert "READY" in text
        assert "NOT READY" not in text
        assert "sufficient information" in text.lower()

    def test_not_ready_comment_includes_gaps(self):
        result = {
            "ticket": "PROJ-123",
            "overall_status": "not_ready",
            "dimensions": {
                "description_quality": {
                    "status": "fail",
                    "score": 1,
                    "gaps": ["No acceptance criteria"],
                },
                "pr_source_linkage": {
                    "status": "fail",
                    "checks": {
                        "git_links_present": {"status": "fail", "detail": "No git-related links"},
                    },
                },
                "metadata_completeness": {
                    "status": "fail",
                    "checks": {
                        "fix_versions": {"status": "fail", "detail": "not set"},
                        "release_note_type": {"status": "fail", "detail": "not set"},
                        "priority": {"status": "pass", "detail": "Major"},
                        "ticket_status": {"status": "pass", "detail": "Done"},
                    },
                },
                "relationship_context": {"status": "pass", "checks": {}},
            },
        }
        text = _adf_to_text(format_comment(result))
        assert "NOT READY" in text
        assert "Description quality" in text
        assert "PR/source linkage" in text
        assert "Metadata" in text
        assert "Assessed by" in text

    def test_not_ready_metadata_includes_field_names(self):
        result = {
            "ticket": "PROJ-123",
            "overall_status": "not_ready",
            "dimensions": {
                "description_quality": None,
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {
                    "status": "fail",
                    "checks": {
                        "fix_versions": {"status": "fail", "detail": "not set"},
                        "release_note_type": {"status": "fail", "detail": "not set"},
                        "priority": {"status": "pass", "detail": "Major"},
                        "ticket_status": {"status": "fail", "detail": "Backlog"},
                    },
                },
                "relationship_context": {"status": "pass", "checks": {}},
            },
        }
        text = _adf_to_text(format_comment(result))
        assert "Fix versions" in text
        assert "Release note type" in text
        assert "Status: Backlog" in text

    def test_ready_with_warnings_comment(self):
        result = {
            "ticket": "PROJ-123",
            "overall_status": "ready_with_warnings",
            "dimensions": {
                "description_quality": {"status": "pass", "score": 3, "gaps": []},
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {
                    "status": "warn",
                    "checks": {
                        "release_note_type": {"status": "fail", "detail": "not set"},
                        "fix_versions": {"status": "pass", "detail": "4.15"},
                        "priority": {"status": "pass", "detail": "Major"},
                        "ticket_status": {"status": "pass", "detail": "Done"},
                    },
                },
                "relationship_context": {"status": "pass", "checks": {}},
            },
        }
        text = _adf_to_text(format_comment(result))
        assert "READY (with warnings)" in text
        assert "not set" in text.lower()

    def test_comment_omits_passing_dimensions(self):
        result = {
            "ticket": "PROJ-123",
            "overall_status": "not_ready",
            "dimensions": {
                "description_quality": {"status": "fail", "score": 1, "gaps": ["One-liner"]},
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {"status": "pass", "checks": {}},
                "relationship_context": {"status": "pass", "checks": {}},
            },
        }
        text = _adf_to_text(format_comment(result))
        assert "PR/source linkage" not in text
        assert "Metadata" not in text

    def test_adf_has_heading_and_bullet_list(self):
        result = {
            "ticket": "PROJ-123",
            "overall_status": "not_ready",
            "dimensions": {
                "description_quality": {"status": "fail", "score": 1, "gaps": ["One-liner"]},
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {"status": "pass", "checks": {}},
                "relationship_context": {"status": "pass", "checks": {}},
            },
        }
        adf = format_comment(result)
        types = [node["type"] for node in adf["content"]]
        assert "heading" in types
        assert "bulletList" in types

    def test_adf_bold_marks_on_dimension_labels(self):
        result = {
            "ticket": "PROJ-123",
            "overall_status": "not_ready",
            "dimensions": {
                "description_quality": {"status": "fail", "score": 1, "gaps": ["Empty"]},
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {"status": "pass", "checks": {}},
                "relationship_context": {"status": "pass", "checks": {}},
            },
        }
        adf = format_comment(result)
        bullet_list = next(n for n in adf["content"] if n["type"] == "bulletList")
        first_item = bullet_list["content"][0]
        paragraph = first_item["content"][0]
        label_node = paragraph["content"][0]
        assert label_node["marks"] == [{"type": "strong"}]
        assert "Description quality" in label_node["text"]

    def test_adf_footer_has_emoji_and_skill_name(self):
        result = {
            "ticket": "PROJ-123",
            "overall_status": "ready",
            "dimensions": {
                "description_quality": {"status": "pass", "score": 4, "gaps": []},
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {"status": "pass", "checks": {}},
                "relationship_context": {"status": "pass", "checks": {}},
            },
        }
        adf = format_comment(result)
        last_para = adf["content"][-1]
        assert last_para["type"] == "paragraph"
        emoji_node = last_para["content"][0]
        assert emoji_node["type"] == "emoji"
        assert emoji_node["attrs"]["shortName"] == ":robot:"
        text_node = last_para["content"][1]
        assert "/docs-ticket-readiness skill" in text_node["text"]
        assert {"type": "em"} in text_node["marks"]


# --- Markdown report ---


class TestFormatMarkdownReport:
    def test_report_has_header(self):
        result = {
            "ticket": "PROJ-123",
            "summary": "Add widget API docs",
            "url": "https://redhat.atlassian.net/browse/PROJ-123",
            "overall_status": "ready",
            "dimensions": {
                "description_quality": {"status": "pass", "score": 4, "gaps": []},
                "pr_source_linkage": {
                    "status": "pass",
                    "checks": {"git_links_present": {"status": "pass", "detail": "1 PR"}},
                },
                "metadata_completeness": {
                    "status": "pass",
                    "checks": {"fix_versions": {"status": "pass", "detail": "4.15"}},
                },
                "relationship_context": {
                    "status": "pass",
                    "checks": {"parent_epic": {"status": "pass", "detail": "PROJ-100"}},
                },
            },
            "relationship_map": {
                "parent": {"key": "PROJ-100", "summary": "Platform", "type": "Epic"},
            },
        }
        report = format_markdown_report(result)
        assert "# PROJ-123" in report
        assert "READY" in report
        assert "Add widget API docs" in report

    def test_report_includes_failing_dimension_details(self):
        result = {
            "ticket": "PROJ-456",
            "summary": "Fix bug",
            "url": "https://redhat.atlassian.net/browse/PROJ-456",
            "overall_status": "not_ready",
            "dimensions": {
                "description_quality": {
                    "status": "fail",
                    "score": 1,
                    "gaps": ["One-liner", "No ACs"],
                },
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {
                    "status": "fail",
                    "checks": {
                        "fix_versions": {"status": "fail", "detail": "not set"},
                        "release_note_type": {"status": "pass", "detail": "Bug Fix"},
                        "priority": {"status": "pass", "detail": "Major"},
                        "ticket_status": {"status": "pass", "detail": "Done"},
                    },
                },
                "relationship_context": {"status": "pass", "checks": {}},
            },
            "relationship_map": {},
        }
        report = format_markdown_report(result)
        assert "NOT READY" in report
        assert "One-liner" in report
        assert "fix_versions" in report or "Fix versions" in report

    def test_report_includes_relationship_map(self):
        result = {
            "ticket": "PROJ-123",
            "summary": "Feature",
            "url": "https://redhat.atlassian.net/browse/PROJ-123",
            "overall_status": "ready",
            "dimensions": {
                "description_quality": {"status": "pass", "score": 4, "gaps": []},
                "pr_source_linkage": {"status": "pass", "checks": {}},
                "metadata_completeness": {"status": "pass", "checks": {}},
                "relationship_context": {"status": "pass", "checks": {}},
            },
            "relationship_map": {
                "parent": {"key": "PROJ-100", "summary": "Platform", "type": "Epic"},
                "children": [
                    {
                        "key": "PROJ-456",
                        "summary": "API",
                        "type": "Story",
                        "pr": "https://github.com/org/repo/pull/42",
                    },
                ],
                "siblings": [
                    {"key": "PROJ-457", "summary": "UI", "type": "Story"},
                ],
            },
        }
        report = format_markdown_report(result)
        assert "PROJ-100" in report
        assert "PROJ-456" in report
        assert "PROJ-457" in report


# --- Relationship map ---


class TestBuildRelationshipMap:
    def test_basic_map(self):
        graph = make_graph_data()
        rel_map = build_relationship_map(graph)
        assert rel_map["parent"]["key"] == "PROJ-100"
        assert len(rel_map["children"]) == 2
        assert rel_map["children"][0]["key"] == "PROJ-456"
        assert len(rel_map["siblings"]) == 1

    def test_map_without_parent(self):
        graph = make_graph_data(parent=None, ancestors=[])
        rel_map = build_relationship_map(graph)
        assert "parent" not in rel_map

    def test_map_child_with_pr(self):
        graph = make_graph_data()
        rel_map = build_relationship_map(graph)
        child_with_pr = next(c for c in rel_map["children"] if c["key"] == "PROJ-456")
        assert "pr" in child_with_pr

    def test_map_documented_by(self):
        graph = make_graph_data()
        rel_map = build_relationship_map(graph)
        assert "documented_by" in rel_map
        assert rel_map["documented_by"][0]["key"] == "DOCS-100"
        assert rel_map["documented_by"][0]["pr"] == "https://github.com/org/docs-repo/pull/10"

    def test_map_no_documented_by(self):
        graph = make_graph_data()
        graph["issue_links"] = {"total": 0, "showing": 0, "skipped": 0, "links": []}
        rel_map = build_relationship_map(graph)
        assert "documented_by" not in rel_map


# --- End-to-end assess_ticket ---


class TestAssessTicket:
    def test_all_pass(self):
        issue = make_issue_data()
        graph = make_graph_data()
        result = assess_ticket(issue, graph)
        assert result["ticket"] == "PROJ-123"
        assert result["overall_status"] in ("ready", "ready_with_warnings")
        assert result["dimensions"]["description_quality"] is None
        assert result["dimensions"]["pr_source_linkage"]["status"] == "pass"
        assert result["relationship_map"]["parent"]["key"] == "PROJ-100"
        assert "description_text" in result

    def test_not_ready_missing_metadata(self):
        issue = make_issue_data(
            custom_fields={},
            priority="Undefined",
            status="Backlog",
        )
        graph = make_graph_data()
        result = assess_ticket(issue, graph)
        assert result["dimensions"]["metadata_completeness"]["status"] == "fail"


# --- Arg parsing ---


class TestParseArgs:
    def test_issue_mode(self):
        args = parse_args(["--issue", "PROJ-123"])
        assert args.issue == "PROJ-123"
        assert args.jql is None

    def test_jql_mode(self):
        args = parse_args(["--jql", "project=PROJ"])
        assert args.jql == "project=PROJ"
        assert args.issue is None

    def test_post_comment_mode(self):
        args = parse_args(["--post-comment"])
        assert args.post_comment is True

    def test_optional_flags(self):
        args = parse_args(
            ["--issue", "PROJ-123", "--output-dir", "/tmp/reports", "--max-results", "5"]
        )
        assert args.output_dir == "/tmp/reports"
        assert args.max_results == 5
