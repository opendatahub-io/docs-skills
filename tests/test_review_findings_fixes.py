"""What the whole-branch review found, pinned so it cannot come back.

Each test here reproduces one finding. They are grouped by the file they are
about rather than by severity, because that is where a reader looking for them
will be.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
for _path in (
    _ENGINE,
    REPO_ROOT / "skills" / "docs-plan" / "scripts",
    REPO_ROOT / "skills" / "docs-repo-analyze" / "scripts",
    REPO_ROOT / "skills" / "docs-write" / "scripts",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import analyze  # noqa: E402
import plan  # noqa: E402
import write  # noqa: E402
from lib.md import changeset  # noqa: E402

# ----------------------------------------------------------------- C1: subject


def _registry(*names):
    return {
        "language": "python",
        "module_count": len(names),
        "modules": {name: {"kind": "library", "file_count": 1, "paths": [name]} for name in names},
        "registry_hash": "sha256:x",
    }


def test_a_subject_narrows_the_registry_to_the_modules_it_names():
    """`--subject` was declared, documented and passed on every topic run, and
    read by nothing: a topic run paid the whole-repository read it exists to
    avoid."""
    registry = _registry("pkg/kvcache", "pkg/scheduler", "pkg/telemetry")
    narrowed = analyze.narrow_subject(registry, "hierarchical KV cache tiering")
    assert set(narrowed["modules"]) == {"pkg/kvcache"}
    assert narrowed["module_count"] == 1


def test_a_subject_matching_nothing_keeps_the_whole_registry():
    """Targeting that matches nothing is worse than reading whole: it hands the
    writer an empty surface and calls it the public API."""
    registry = _registry("pkg/queue", "pkg/scheduler")
    narrowed = analyze.narrow_subject(registry, "quantum entanglement")
    assert set(narrowed["modules"]) == {"pkg/queue", "pkg/scheduler"}


def test_an_empty_subject_keeps_the_whole_registry():
    registry = _registry("pkg/queue")
    assert analyze.narrow_subject(registry, "") is registry


# ------------------------------------------------------------- C2: update path


def _deliverable(**over):
    base = {
        "path": "configure-the-registry.md",
        "type": "procedure",
        "title": "Configure the registry",
        "rationale": "r",
        "sources": [],
    }
    base.update(over)
    return base


def test_an_update_may_name_a_nested_page_that_exists():
    """The planner is handed nested paths by `docs_inventory`, and most docs
    trees have subdirectories. Rejecting them removed the update path."""
    kept, rejected, _ = plan.validate(
        [_deliverable(kind="update", path="guides/install.md")],
        {"guides/install.md"},
    )
    assert rejected == [], rejected
    assert kept[0]["path"] == "guides/install.md"


def test_an_update_naming_a_page_that_is_not_there_is_rejected():
    kept, rejected, _ = plan.validate(
        [_deliverable(kind="update", path="guides/gone.md")], {"guides/install.md"}
    )
    assert kept == [] and len(rejected) == 1


def test_an_update_path_may_not_escape_the_docs_tree():
    """`_escapes` in the writer is the backstop; this is the gate."""
    kept, rejected, _ = plan.validate(
        [_deliverable(kind="update", path="../../etc/passwd.md")], {"guides/install.md"}
    )
    assert kept == [] and len(rejected) == 1


def test_a_new_page_still_has_to_be_a_flat_kebab_case_name():
    """A `new` path is joined onto the changeset directory, so a separator in
    it decides where the file lands."""
    kept, rejected, _ = plan.validate([_deliverable(kind="new", path="guides/new.md")], set())
    assert kept == [] and len(rejected) == 1


# ------------------------------------------------- C3: a repo with no modules


def test_a_registry_with_no_modules_is_nothing_to_do_not_a_failure(tmp_path):
    """A repository the tool cannot analyse must not report `a step failed`:
    CI reads exit 3 as something broke, and nothing broke."""
    (tmp_path / "notes.txt").write_text("not code\n")
    out = tmp_path / ".docs-gen"
    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "docs-repo-analyze" / "scripts" / "analyze.py"),
            "--repo",
            str(tmp_path),
            "--out",
            str(out),
            "--llm-cmd",
            "cat",
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 1, f"{done.returncode}: {done.stderr}"
    assert "Traceback" not in done.stderr


def test_the_whole_chain_reports_nothing_to_write_for_a_repo_it_cannot_read(tmp_path):
    (tmp_path / "notes.txt").write_text("not code\n")
    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "docs" / "scripts" / "build.py"),
            "--repo",
            str(tmp_path),
            "--out",
            str(tmp_path / ".docs-gen"),
            "--llm-cmd",
            "cat",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 1, f"{done.returncode}: {done.stderr}"
    assert "a step failed" not in done.stderr


# ---------------------------------------------------------- I1/I2: the index


def test_the_changeset_index_does_not_render_retired_fields():
    """`index.md` is the one artifact a run leaves under docs/ for a person."""
    report = {
        "results": [
            {
                "deliverable": "install.md",
                "kind": "update",
                "path": "docs/guides/install.md",
                "status": "written",
                "summary": "corrected the port",
            }
        ]
    }
    text = changeset.index(report)
    assert "Targeting" not in text
    assert "section" not in text
    assert "docs/guides/install.md" in text


def test_the_written_summary_names_the_page_an_update_changed():
    results = [
        {
            "deliverable": "install.md",
            "kind": "update",
            "path": "docs/guides/install.md",
            "status": "written",
        }
    ]
    lines = write.summarize(results)
    assert lines == ["- docs/guides/install.md: updated"]


# ---------------------------------------------------- I3/I4: the writer's args


def test_document_mode_accepts_its_own_flags():
    """Both modes parse through one parser, so a flag of either is reachable."""
    parser = write.build_parser()
    args = parser.parse_args(["--repo", ".", "--documents", "docs/README.md"])
    assert args.documents == ["docs/README.md"]


def test_plan_mode_flags_are_reachable_too():
    parser = write.build_parser()
    args = parser.parse_args(["--repo", ".", "--plan", "p.json", "--topic", "t"])
    assert args.plan == "p.json" and args.topic == "t"


def test_the_repair_loop_default_is_the_key_the_loop_reads(tmp_path):
    """A caller entering through `run_plan` got one attempt where both CLIs
    default to three, because the seeded key was not the one read."""
    report = write.run_plan(
        tmp_path,
        {"deliverables": []},
        docs_dir="docs",
        llm_cmd=None,
        out=tmp_path / "out",
    )
    assert report["written"] == 0
    parser = write.build_parser()
    assert parser.parse_args(["--repo", "."]).vale_attempts == 3


# ------------------------------------------------------- I6: a safe default


def test_an_unmarked_draft_is_kept_rather_than_deleted(tmp_path):
    """`ownership.ownership` reads an unmarked file as `manual`. A second
    reading that calls it deletable is the ownership contract disagreeing with
    itself, on the destructive side."""
    changeset_dir = tmp_path / "docs" / "changeset-x"
    (changeset_dir / "new").mkdir(parents=True)
    stray = changeset_dir / "new" / "handwritten.md"
    stray.write_text("# Notes\n\nNo frontmatter.\n")
    records = changeset.prune(tmp_path, changeset_dir, [])
    assert stray.is_file(), records
    assert [r["status"] for r in records] == ["kept"]


def test_the_writer_refuses_to_prune_when_no_changeset_was_named(tmp_path):
    """The documented default pointed `--changeset` at docs_dir itself, so a
    direct invocation pruned the documentation tree."""
    parser = write.build_parser()
    assert parser.parse_args(["--repo", "."]).changeset is None


# ------------------------------------------------------- I7: no reaching out


def test_the_package_cannot_clone_a_repository():
    """The spec's first line: everything that reaches outside the repository
    goes. Nothing in either chain calls this, and a skill that advertises it
    tells an agent the reach is supported."""
    source = (_ENGINE / "lib" / "git" / "git_context.py").read_text()
    assert "def clone(" not in source
    assert "refs/pull/" not in source
    skill = (REPO_ROOT / "skills" / "docs-git-context" / "SKILL.md").read_text()
    assert "clone" not in skill.lower()


# ------------------------------------------------- I8: bootstrap failure mode


def test_bootstrap_reports_a_failed_snapshot_rather_than_raising():
    """The first run against a new repository is the one most likely to hit an
    extractor problem, and it ended in a traceback."""
    source = (REPO_ROOT / "skills" / "docs-sync" / "scripts" / "sync.py").read_text()
    opens = source.index("if args.bootstrap:")
    bootstrap = source[opens : source.index("    else:", opens)]
    assert "try:" in bootstrap, bootstrap


# ------------------------------------------------------------ Minor: residue


def test_no_retired_exit_code_constant_survives():
    source = (REPO_ROOT / "skills" / "docs" / "scripts" / "build.py").read_text()
    assert "INCOMPLETE" not in source


def test_every_schema_identifier_is_this_package():
    for script in sorted((REPO_ROOT / "skills").rglob("*.py")):
        assert "docs-orc/" not in script.read_text(), script


def test_the_standalone_model_default_is_pi():
    """The package dropped the Claude Code plugin; a standalone invocation
    should not still spawn `claude -p`."""
    for rel in (
        "skills/docs-write/scripts/write.py",
        "skills/docs-query-code/scripts/query.py",
        "skills/docs-engine/scripts/lib/run/step.py",
    ):
        assert 'DOCS_LLM_CMD", "claude -p"' not in (REPO_ROOT / rel).read_text(), rel


def test_the_generator_stamp_is_derived_from_the_package_version():
    """Three copies of the stamp had already drifted to two versions, and it is
    how a reader tells which version wrote the page in front of them."""
    from lib.run import engine

    version = json.loads((REPO_ROOT / "package.json").read_text())["version"]
    assert engine.GENERATOR == f"docs-skills/{version}"
    for rel in (
        "skills/docs-write/scripts/write.py",
        "skills/docs-changelog/scripts/changelog.py",
    ):
        assert "GENERATOR = " not in (REPO_ROOT / rel).read_text(), rel


def test_the_numbered_section_splicer_is_gone():
    """`lib/md/sections.py` split a published guide on its dotted section
    numbers, for the update path that read an `rhd` cache. That path went, and
    nothing called any of its five names afterwards: the one reference left was
    a `SectionError` in an except tuple that could no longer be raised.
    """
    assert not (_ENGINE / "lib" / "md" / "sections.py").exists()
    assert not (REPO_ROOT / "tests" / "test_sections.py").exists()
    for script in sorted((REPO_ROOT / "skills").rglob("*.py")):
        source = script.read_text()
        assert "sections.SectionError" not in source, script
        assert "import sections" not in source, script
