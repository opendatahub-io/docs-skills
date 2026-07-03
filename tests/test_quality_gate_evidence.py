"""Tests for inline evidence check functions in quality_gate.py."""

import json
from pathlib import Path

from quality_gate import extract_key_terms


class TestExtractKeyTerms:
    def test_extracts_technical_terms(self):
        terms = extract_key_terms("Users can configure GPU memory limits")
        assert "configure" in terms
        assert "gpu" in terms
        assert "memory" in terms
        assert "limits" in terms

    def test_filters_stopwords(self):
        terms = extract_key_terms("The user should be able to document the feature")
        assert "user" not in terms
        assert "should" not in terms
        assert "document" not in terms
        assert "feature" not in terms

    def test_preserves_hyphenated_compounds(self):
        terms = extract_key_terms("Configure the rate-limiter for API endpoints")
        assert "rate-limiter" in terms
        assert "api" in terms
        assert "endpoints" in terms

    def test_caps_at_eight_terms(self):
        text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo"
        terms = extract_key_terms(text)
        assert len(terms) <= 8

    def test_deduplicates(self):
        terms = extract_key_terms("deploy the deployment deployer")
        assert terms.count("deploy") <= 1

    def test_empty_input(self):
        assert extract_key_terms("") == []

    def test_short_tokens_filtered(self):
        terms = extract_key_terms("an ok it do go")
        assert len(terms) == 0


from quality_gate import check_registry_evidence


class TestCheckRegistryEvidence:
    def _registry(self):
        return [
            {"module": "auth", "purpose": "Authentication and session management"},
            {"module": "gpu-allocator", "purpose": "GPU memory allocation and resource limits"},
            {"module": "api-gateway", "purpose": "HTTP request routing and rate limiting"},
        ]

    def test_grounded_on_two_term_match(self):
        status, module = check_registry_evidence(
            ["gpu", "memory", "limits"], self._registry()
        )
        assert status == "grounded"
        assert module == "gpu-allocator"

    def test_partial_on_single_term_match(self):
        status, module = check_registry_evidence(
            ["authentication"], self._registry()
        )
        assert status == "partial"
        assert module == "auth"

    def test_absent_on_no_match(self):
        status, module = check_registry_evidence(
            ["kubernetes", "operator", "reconciler"], self._registry()
        )
        assert status == "absent"
        assert module is None

    def test_empty_registry(self):
        status, module = check_registry_evidence(["gpu", "memory"], [])
        assert status == "absent"

    def test_empty_terms(self):
        status, module = check_registry_evidence([], self._registry())
        assert status == "absent"

    def test_matches_module_name_not_just_purpose(self):
        status, module = check_registry_evidence(
            ["api-gateway", "routing"], self._registry()
        )
        assert status == "grounded"
        assert module == "api-gateway"


from quality_gate import check_grep_evidence


class TestCheckGrepEvidence:
    def test_grounded_on_many_hits(self, tmp_path):
        for i in range(6):
            f = tmp_path / f"mod{i}.py"
            f.write_text(f"class GpuAllocator{i}: pass\n")
        status = check_grep_evidence(["gpuallocator"], tmp_path)
        assert status == "grounded"

    def test_partial_on_few_hits(self, tmp_path):
        (tmp_path / "one.py").write_text("allocator = True\n")
        status = check_grep_evidence(["allocator"], tmp_path)
        assert status == "partial"

    def test_absent_on_no_hits(self, tmp_path):
        (tmp_path / "empty.py").write_text("x = 1\n")
        status = check_grep_evidence(["nonexistent-term"], tmp_path)
        assert status == "absent"

    def test_handles_missing_directory(self, tmp_path):
        status = check_grep_evidence(["term"], tmp_path / "nope")
        assert status == "absent"


from quality_gate import build_inline_evidence, read_analysis_path


class TestReadAnalysisPath:
    def test_returns_path_from_sidecar(self, tmp_path):
        ca = tmp_path / "code-analysis"
        ca.mkdir()
        (ca / "step-result.json").write_text(
            json.dumps({"repo_analysis_path": "/data/analysis"})
        )
        assert read_analysis_path(tmp_path) == "/data/analysis"

    def test_returns_none_when_missing(self, tmp_path):
        assert read_analysis_path(tmp_path) is None

    def test_returns_none_on_bad_json(self, tmp_path):
        ca = tmp_path / "code-analysis"
        ca.mkdir()
        (ca / "step-result.json").write_text("not json")
        assert read_analysis_path(tmp_path) is None


class TestBuildInlineEvidence:
    def _setup(self, tmp_path):
        """Create minimal pipeline fixture: discovery.json + registry + repo."""
        # requirements/discovery.json
        req = tmp_path / "requirements"
        req.mkdir()
        (req / "discovery.json").write_text(json.dumps({
            "requirements": [
                {"id": "REQ-001", "title": "GPU memory allocation",
                 "one_line_summary": "Configure GPU memory limits for workloads"},
                {"id": "REQ-002", "title": "Authentication flow",
                 "one_line_summary": "Session-based authentication for API access"},
                {"id": "REQ-003", "title": "Quantum flux capacitor",
                 "one_line_summary": "Enable quantum flux processing"},
            ]
        }))
        # code-analysis sidecar pointing to analysis path
        ca = tmp_path / "code-analysis"
        ca.mkdir()
        analysis = tmp_path / "analysis"
        analysis.mkdir()
        (ca / "step-result.json").write_text(json.dumps({
            "repo_analysis_path": str(analysis)
        }))
        # module registry
        reg_dir = analysis / "module-registry"
        reg_dir.mkdir(parents=True)
        (reg_dir / "registry.json").write_text(json.dumps([
            {"module": "gpu-allocator",
             "purpose": "GPU memory allocation and resource limits"},
            {"module": "auth",
             "purpose": "Authentication and session management"},
        ]))
        # mock source repo with one Python file
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "auth.py").write_text("class SessionManager: pass\n")
        return repo

    def test_grounded_from_registry(self, tmp_path):
        repo = self._setup(tmp_path)
        result = build_inline_evidence(tmp_path, repo)
        reqs = {r["id"]: r for r in result["requirements"]}
        assert reqs["REQ-001"]["status"] == "grounded"

    def test_partial_from_registry(self, tmp_path):
        repo = self._setup(tmp_path)
        result = build_inline_evidence(tmp_path, repo)
        reqs = {r["id"]: r for r in result["requirements"]}
        assert reqs["REQ-002"]["status"] == "partial"

    def test_absent_no_evidence(self, tmp_path):
        repo = self._setup(tmp_path)
        result = build_inline_evidence(tmp_path, repo)
        reqs = {r["id"]: r for r in result["requirements"]}
        assert reqs["REQ-003"]["status"] == "absent"

    def test_returns_none_without_discovery(self, tmp_path):
        assert build_inline_evidence(tmp_path, tmp_path) is None

    def test_works_without_registry(self, tmp_path):
        """Falls back to grep when registry is missing."""
        req = tmp_path / "requirements"
        req.mkdir()
        (req / "discovery.json").write_text(json.dumps({
            "requirements": [
                {"id": "REQ-001", "title": "SessionManager auth",
                 "one_line_summary": "Session-based auth"},
            ]
        }))
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "auth.py").write_text("class SessionManager: pass\n")
        result = build_inline_evidence(tmp_path, repo)
        assert result is not None
        assert result["requirements"][0]["status"] in ("grounded", "partial")

    def test_works_without_repo(self, tmp_path):
        """Returns unknown when no repo path available."""
        req = tmp_path / "requirements"
        req.mkdir()
        (req / "discovery.json").write_text(json.dumps({
            "requirements": [
                {"id": "REQ-001", "title": "GPU allocation",
                 "one_line_summary": "Configure GPU limits"},
            ]
        }))
        result = build_inline_evidence(tmp_path, None)
        assert result["requirements"][0]["status"] == "unknown"


import subprocess
import sys

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "docs-workflow-quality-gate"
    / "scripts"
    / "quality_gate.py"
)


def _build_pipeline_fixture(tmp_path):
    """Create a complete pipeline fixture for verify --classify with inline evidence."""
    # requirements/discovery.json with AC items
    req = tmp_path / "requirements"
    req.mkdir()
    (req / "discovery.json").write_text(json.dumps({
        "ticket_summary": "Test ticket",
        "requirements": [
            {
                "id": "REQ-001",
                "title": "GPU memory allocation",
                "one_line_summary": "Configure GPU memory limits",
                "acceptance_criteria": [
                    "Users can configure GPU memory limits",
                    "Documentation includes GPU allocation procedure",
                ],
            },
            {
                "id": "REQ-002",
                "title": "Quantum entanglement",
                "one_line_summary": "Enable quantum processing",
                "acceptance_criteria": [
                    "Quantum processing is documented",
                ],
            },
        ],
    }))

    # writing/step-result.json pointing to a doc file
    writing = tmp_path / "writing"
    writing.mkdir()
    doc = writing / "proc-gpu.adoc"
    doc.write_text(
        "= GPU Memory Configuration\n\n"
        "To configure GPU memory limits, set the memory_limit parameter.\n"
    )
    (writing / "step-result.json").write_text(json.dumps({
        "files": [str(doc)], "mode": "draft"
    }))

    # code-analysis sidecar with analysis path
    ca = tmp_path / "code-analysis"
    ca.mkdir()
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    (ca / "step-result.json").write_text(json.dumps({
        "repo_analysis_path": str(analysis)
    }))

    # module registry
    reg = analysis / "module-registry"
    reg.mkdir(parents=True)
    (reg / "registry.json").write_text(json.dumps([
        {"module": "gpu-allocator", "purpose": "GPU memory allocation and resource limits"},
    ]))

    # mock source repo
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "gpu.py").write_text("class GpuAllocator: pass\n")

    return repo


class TestVerifyClassifyWithInlineEvidence:
    def test_inline_evidence_used_when_no_scope_req_audit(self, tmp_path):
        """When no evidence-status.json exists and --repo is passed,
        inline evidence check should produce grounded/absent classifications."""
        repo = _build_pipeline_fixture(tmp_path)

        # Step 1: prepare the coverage prompt + manifest
        r1 = subprocess.run(
            [sys.executable, str(SCRIPT), "verify",
             "--ticket", "TEST-1", "--base-path", str(tmp_path),
             "--prepare"],
            capture_output=True, text=True,
        )
        assert r1.returncode == 0, r1.stderr

        # Write mock coverage results (agent output)
        qg = tmp_path / "quality-gate"
        (qg / "coverage-results.json").write_text(json.dumps([
            {"id": "REQ-001_AC00", "covered": True,
             "quote": "To configure GPU memory limits, set the memory_limit parameter."},
            {"id": "REQ-001_AC01", "covered": False, "quote": None},
            {"id": "REQ-002_AC00", "covered": False, "quote": None},
        ]))

        # Step 2: classify with --repo (triggers inline evidence)
        r2 = subprocess.run(
            [sys.executable, str(SCRIPT), "verify",
             "--ticket", "TEST-1", "--base-path", str(tmp_path),
             "--classify", "--repo", str(repo)],
            capture_output=True, text=True,
        )
        assert r2.returncode == 0, r2.stderr

        coverage = json.loads((qg / "coverage-check.json").read_text())
        items = {it["id"]: it for it in coverage["items"]}
        # REQ-001_AC00 should be covered
        assert items["REQ-001_AC00"]["classification"] == "covered"
        # REQ-001_AC01 uncovered, but REQ-001 is grounded -> real_defect
        assert items["REQ-001_AC01"]["evidence_status"] == "grounded"
        assert items["REQ-001_AC01"]["classification"] == "real_defect"
        # REQ-002_AC00 uncovered, REQ-002 has no code evidence -> absent
        assert items["REQ-002_AC00"]["evidence_status"] == "absent"
        assert items["REQ-002_AC00"]["classification"] == "correctly_absent"
