"""Tests for pii_scanner.py."""

import json
import textwrap

import pytest
from pii_scanner import (
    _is_comment_line,
    _is_credential_placeholder,
    _is_email_allowed,
    _is_ip_allowed,
    _is_url_allowed,
    _track_block_comment,
    cmd_scan,
    collect_files,
    run,
    scan_file,
    scan_line,
)

# ── IP allowlist ─────────────────────────────────────────────────────────────


class TestIsIpAllowed:
    @pytest.mark.parametrize(
        "ip",
        [
            "192.0.2.1",
            "198.51.100.42",
            "203.0.113.255",
        ],
    )
    def test_rfc5737_documentation_addresses(self, ip):
        assert _is_ip_allowed(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "10.0.0.1",
            "10.255.255.255",
            "192.168.0.1",
            "192.168.1.100",
            "172.16.0.1",
            "172.31.255.255",
        ],
    )
    def test_rfc1918_private_ranges(self, ip):
        assert _is_ip_allowed(ip) is True

    def test_172_outside_private_range_not_allowed(self):
        assert _is_ip_allowed("172.15.0.1") is False
        assert _is_ip_allowed("172.32.0.1") is False

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "255.255.255.255",
        ],
    )
    def test_special_first_octets_allowed(self, ip):
        assert _is_ip_allowed(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.2.3.4",
            "203.1.0.1",
            "192.1.2.3",
        ],
    )
    def test_public_ips_not_allowed(self, ip):
        assert _is_ip_allowed(ip) is False


# ── URL allowlist ────────────────────────────────────────────────────────────


class TestIsUrlAllowed:
    @pytest.mark.parametrize(
        "url",
        [
            "redhat.com",
            "example.com",
            "example.net",
            "example.org",
            "www.example.com",
            "access.redhat.com",
            "https://access.redhat.com",
            "http://www.example.com",
        ],
    )
    def test_exact_allowlist(self, url):
        assert _is_url_allowed(url) is True

    def test_redhat_domain_suffixes(self):
        assert _is_url_allowed("docs.redhat.com") is True
        assert _is_url_allowed("quay.redhat.io") is True
        assert _is_url_allowed("console.redhat.com") is True

    def test_openshift_suffix(self):
        assert _is_url_allowed("apps.openshift.com") is True

    def test_prefix_match(self):
        assert _is_url_allowed("https://access.redhat.com/solutions/12345") is True

    def test_node_example_com(self):
        assert _is_url_allowed("node1.example.com") is True
        assert _is_url_allowed("node42.example.com") is True

    def test_file_extensions_allowed(self):
        assert _is_url_allowed("output.log") is True
        assert _is_url_allowed("archive.tar") is True
        assert _is_url_allowed("config.yaml") is True
        assert _is_url_allowed("script.py") is True

    def test_unknown_external_url_not_allowed(self):
        assert _is_url_allowed("https://internal.corp-site.net/admin") is False
        assert _is_url_allowed("custom-vendor.io") is False


# ── Email allowlist ──────────────────────────────────────────────────────────


class TestIsEmailAllowed:
    def test_allowed_domains(self):
        assert _is_email_allowed("user@example.com") is True
        assert _is_email_allowed("admin@redhat.com") is True
        assert _is_email_allowed("test@example.org") is True

    def test_case_insensitive(self):
        assert _is_email_allowed("User@Example.COM") is True

    def test_disallowed_domain(self):
        assert _is_email_allowed("user@gmail.com") is False
        assert _is_email_allowed("admin@internal.corp") is False


# ── Credential placeholders ──────────────────────────────────────────────────


class TestIsCredentialPlaceholder:
    def test_empty_and_none(self):
        assert _is_credential_placeholder("") is True
        assert _is_credential_placeholder(None) is True

    @pytest.mark.parametrize(
        "val",
        [
            "<password>",
            "{my-secret}",
            "$PASSWORD",
            '"quoted"',
            "'single'",
            "****",
        ],
    )
    def test_prefix_patterns(self, val):
        assert _is_credential_placeholder(val) is True

    @pytest.mark.parametrize(
        "val",
        [
            "changeme",
            "CHANGEME",
            "password",
            "my-password",
            "your-password-here",
            "null",
            "none",
            "replace_me",
            "xxx",
            "example",
            "secret",
        ],
    )
    def test_known_placeholder_words(self, val):
        assert _is_credential_placeholder(val) is True

    def test_trailing_punctuation_stripped(self):
        assert _is_credential_placeholder("changeme.") is True
        assert _is_credential_placeholder("password;") is True

    def test_real_values_not_placeholder(self):
        assert _is_credential_placeholder("ghp_abc123def456ghi789") is False
        assert _is_credential_placeholder("SuperS3cret!2024") is False


# ── Comment detection ────────────────────────────────────────────────────────


class TestIsCommentLine:
    def test_adoc_single_line_comment(self):
        assert _is_comment_line("// This is a comment", "test.adoc") is True

    def test_adoc_block_delimiter_not_single_comment(self):
        assert _is_comment_line("////", "test.adoc") is False
        assert _is_comment_line("//// block", "test.adoc") is False

    def test_adoc_normal_line(self):
        assert _is_comment_line("Some text", "test.adoc") is False

    def test_md_html_comment(self):
        assert _is_comment_line("<!-- comment -->", "test.md") is True

    def test_md_unclosed_html_comment(self):
        assert _is_comment_line("<!-- start of block", "test.md") is False

    def test_xml_comment(self):
        assert _is_comment_line("<!-- comment -->", "test.xml") is True

    def test_indented_comment(self):
        assert _is_comment_line("   // comment", "test.adoc") is True


class TestTrackBlockComment:
    def test_adoc_block_open(self):
        skip, in_block, btype = _track_block_comment("////", False, None, "test.adoc")
        assert skip is True
        assert in_block is True
        assert btype == "adoc"

    def test_adoc_block_close(self):
        skip, in_block, btype = _track_block_comment("////", True, "adoc", "test.adoc")
        assert skip is True
        assert in_block is False
        assert btype is None

    def test_adoc_inside_block(self):
        skip, in_block, btype = _track_block_comment(
            "password=secret123", True, "adoc", "test.adoc"
        )
        assert skip is True
        assert in_block is True

    def test_html_block_open(self):
        skip, in_block, btype = _track_block_comment("<!-- start", False, None, "test.md")
        assert skip is True
        assert in_block is True
        assert btype == "html"

    def test_html_block_close(self):
        skip, in_block, btype = _track_block_comment("end -->", True, "html", "test.md")
        assert skip is True
        assert in_block is False

    def test_not_in_block_no_delimiter(self):
        skip, in_block, btype = _track_block_comment("normal text", False, None, "test.adoc")
        assert skip is False
        assert in_block is False

    def test_adoc_block_not_triggered_for_md(self):
        skip, in_block, btype = _track_block_comment("////", False, None, "test.md")
        assert skip is False
        assert in_block is False

    def test_html_self_closing_not_block(self):
        skip, in_block, btype = _track_block_comment(
            "<!-- self-closing -->", False, None, "test.md"
        )
        assert skip is False
        assert in_block is False


# ── scan_line: IP detection ──────────────────────────────────────────────────


class TestScanLineIP:
    def test_public_ip_detected(self):
        findings = scan_line("Connect to 8.8.8.8 for DNS", 1, "test.adoc")
        assert len(findings) == 1
        assert findings[0]["category"] == "ip"
        assert findings[0]["matched"] == "8.8.8.8"

    def test_private_ip_ignored(self):
        findings = scan_line("Server at 10.0.0.1", 1, "test.adoc")
        ip_findings = [f for f in findings if f["category"] == "ip"]
        assert ip_findings == []

    def test_rfc5737_ip_ignored(self):
        findings = scan_line("Example: 192.0.2.100", 1, "test.adoc")
        ip_findings = [f for f in findings if f["category"] == "ip"]
        assert ip_findings == []

    def test_multiple_ips_on_one_line(self):
        findings = scan_line("Route 8.8.8.8 via 1.1.1.1", 1, "test.adoc")
        ip_findings = [f for f in findings if f["category"] == "ip"]
        assert len(ip_findings) == 2


# ── scan_line: MAC detection ────────────────────────────────────────────────


class TestScanLineMAC:
    def test_colon_mac_detected(self):
        findings = scan_line("MAC: aa:bb:cc:dd:ee:ff", 1, "test.adoc")
        mac_findings = [f for f in findings if f["category"] == "mac"]
        assert len(mac_findings) == 1

    def test_dash_mac_detected(self):
        findings = scan_line("MAC: aa-bb-cc-dd-ee-ff", 1, "test.adoc")
        mac_findings = [f for f in findings if f["category"] == "mac"]
        assert len(mac_findings) == 1

    def test_dot_mac_detected(self):
        findings = scan_line("MAC: aa.bb.cc.dd.ee.ff", 1, "test.adoc")
        mac_findings = [f for f in findings if f["category"] == "mac"]
        assert len(mac_findings) == 1

    def test_allowed_mac_ignored(self):
        findings = scan_line("MAC: 00:00:00:00:00:aa", 1, "test.adoc")
        mac_findings = [f for f in findings if f["category"] == "mac"]
        assert mac_findings == []

    def test_allowed_mac_dash_format_ignored(self):
        findings = scan_line("MAC: 00-00-00-00-00-bb", 1, "test.adoc")
        mac_findings = [f for f in findings if f["category"] == "mac"]
        assert mac_findings == []


# ── scan_line: URL detection ─────────────────────────────────────────────────


class TestScanLineURL:
    def test_external_url_detected(self):
        findings = scan_line("See https://vendor-portal.net/page", 1, "test.adoc")
        url_findings = [f for f in findings if f["category"] == "url"]
        assert len(url_findings) == 1

    def test_redhat_url_ignored(self):
        findings = scan_line("See https://access.redhat.com/docs", 1, "test.adoc")
        url_findings = [f for f in findings if f["category"] == "url"]
        assert url_findings == []

    def test_example_com_ignored(self):
        findings = scan_line("Visit example.com for info", 1, "test.adoc")
        url_findings = [f for f in findings if f["category"] == "url"]
        assert url_findings == []

    def test_file_extension_url_ignored(self):
        findings = scan_line("See config.yaml for details", 1, "test.adoc")
        url_findings = [f for f in findings if f["category"] == "url"]
        assert url_findings == []


# ── scan_line: email detection ───────────────────────────────────────────────


class TestScanLineEmail:
    def test_external_email_detected(self):
        findings = scan_line("Contact user@gmail.com", 1, "test.adoc")
        email_findings = [f for f in findings if f["category"] == "email"]
        assert len(email_findings) == 1
        assert email_findings[0]["matched"] == "user@gmail.com"

    def test_example_email_ignored(self):
        findings = scan_line("Contact user@example.com", 1, "test.adoc")
        email_findings = [f for f in findings if f["category"] == "email"]
        assert email_findings == []

    def test_redhat_email_ignored(self):
        findings = scan_line("Contact admin@redhat.com", 1, "test.adoc")
        email_findings = [f for f in findings if f["category"] == "email"]
        assert email_findings == []


# ── scan_line: internal hostnames ────────────────────────────────────────────


class TestScanLineHostname:
    def test_internal_hostname_detected(self):
        findings = scan_line("Connect to server1.internal", 1, "test.adoc")
        host_findings = [f for f in findings if f["category"] == "internal_hostname"]
        assert len(host_findings) == 1

    def test_corp_hostname_detected(self):
        findings = scan_line("Use proxy.corp for access", 1, "test.adoc")
        host_findings = [f for f in findings if f["category"] == "internal_hostname"]
        assert len(host_findings) == 1

    def test_local_hostname_detected(self):
        findings = scan_line("DNS: myhost.local", 1, "test.adoc")
        host_findings = [f for f in findings if f["category"] == "internal_hostname"]
        assert len(host_findings) == 1

    def test_eng_redhat_detected(self):
        findings = scan_line("Build at ci.eng.redhat.com", 1, "test.adoc")
        host_findings = [f for f in findings if f["category"] == "internal_hostname"]
        assert len(host_findings) == 1

    def test_lab_eng_redhat_detected(self):
        findings = scan_line("lab.eng.bos.redhat.com is internal", 1, "test.adoc")
        host_findings = [f for f in findings if f["category"] == "internal_hostname"]
        assert len(host_findings) == 1


# ── scan_line: credentials ───────────────────────────────────────────────────


class TestScanLineCredentials:
    def test_password_with_real_value(self):
        findings = scan_line("password=SuperS3cret!", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert len(cred_findings) == 1
        assert cred_findings[0]["severity"] == "critical"

    def test_password_with_placeholder_ignored(self):
        findings = scan_line("password=changeme", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert cred_findings == []

    def test_password_with_angle_bracket_ignored(self):
        findings = scan_line("password=<your-password>", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert cred_findings == []

    def test_secret_with_real_value(self):
        findings = scan_line("secret: myS3cretValue99", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert len(cred_findings) == 1

    def test_secret_with_placeholder_ignored(self):
        findings = scan_line("secret: <my-secret>", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert cred_findings == []

    def test_token_long_string_detected(self):
        token = "ghp_" + "a" * 30
        findings = scan_line(f"token={token}", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert len(cred_findings) == 1

    def test_token_short_string_ignored(self):
        findings = scan_line("token=short", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert cred_findings == []

    def test_bearer_token_detected(self):
        token = "eyJhbGciOiJIUzI1NiJ9_" + "x" * 20
        findings = scan_line(f"Authorization: Bearer {token}", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert len(cred_findings) == 1

    def test_private_key_header_detected(self):
        findings = scan_line("-----BEGIN PRIVATE KEY-----", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert len(cred_findings) == 1
        assert "PRIVATE KEY" in cred_findings[0]["matched"]

    def test_rsa_private_key_header_detected(self):
        findings = scan_line("-----BEGIN RSA PRIVATE KEY-----", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert len(cred_findings) == 1

    def test_password_case_insensitive(self):
        findings = scan_line("PASSWORD=RealS3cret!", 1, "test.adoc")
        cred_findings = [f for f in findings if f["category"] == "credential"]
        assert len(cred_findings) == 1


# ── scan_line: comment skipping ──────────────────────────────────────────────


class TestScanLineCommentSkipping:
    def test_adoc_comment_skipped(self):
        findings = scan_line("// password=RealS3cret!", 1, "test.adoc")
        assert findings == []

    def test_md_html_comment_skipped(self):
        findings = scan_line("<!-- password=RealS3cret! -->", 1, "test.md")
        assert findings == []

    def test_non_comment_not_skipped(self):
        findings = scan_line("password=RealS3cret!", 1, "test.adoc")
        assert len(findings) > 0


# ── scan_line: hostname/URL dedup ────────────────────────────────────────────


class TestScanLineHostnameUrlDedup:
    def test_hostname_suppresses_url_finding(self):
        findings = scan_line("Use https://server.internal/path", 1, "test.adoc")
        categories = [f["category"] for f in findings]
        assert "internal_hostname" in categories
        # The URL dedup uses substring check — the hostname finding's matched
        # text should suppress the URL finding for the same string
        url_findings = [f for f in findings if f["category"] == "url"]
        assert url_findings == []


# ── scan_file ────────────────────────────────────────────────────────────────


class TestScanFile:
    def test_scan_clean_file(self, tmp_path):
        f = tmp_path / "clean.adoc"
        f.write_text("= Clean Document\n\nNo sensitive data here.\n")
        findings = scan_file(str(f))
        assert findings == []

    def test_scan_file_with_findings(self, tmp_path):
        f = tmp_path / "dirty.adoc"
        f.write_text("Connect to 8.8.8.8 for DNS.\n")
        findings = scan_file(str(f))
        assert len(findings) == 1
        assert findings[0]["category"] == "ip"

    def test_scan_unreadable_file(self, tmp_path):
        findings = scan_file(str(tmp_path / "nonexistent.adoc"))
        assert len(findings) == 1
        assert findings[0]["category"] == "scan_error"

    def test_scan_file_line_numbers(self, tmp_path):
        f = tmp_path / "multi.adoc"
        f.write_text("line one\npassword=RealValue!\nline three\n")
        findings = scan_file(str(f))
        cred = [f for f in findings if f["category"] == "credential"]
        assert cred[0]["line"] == 2

    def test_block_comment_skipped_in_scan_file(self, tmp_path):
        f = tmp_path / "commented.adoc"
        f.write_text(
            textwrap.dedent("""\
            = Document

            ////
            password=SuperS3cret!
            8.8.8.8
            user@gmail.com
            ////

            Normal content here.
        """)
        )
        findings = scan_file(str(f))
        assert findings == []

    def test_html_block_comment_skipped(self, tmp_path):
        f = tmp_path / "commented.md"
        f.write_text(
            textwrap.dedent("""\
            # Document

            <!--
            password=SuperS3cret!
            8.8.8.8
            -->

            Normal content here.
        """)
        )
        findings = scan_file(str(f))
        assert findings == []

    def test_encoding_warning(self, tmp_path):
        f = tmp_path / "bad.adoc"
        f.write_bytes(b"Some text \xff\xfe more text\n")
        findings = scan_file(str(f))
        warn = [f for f in findings if f["category"] == "scan_warning"]
        assert len(warn) == 1

    def test_content_after_block_comment_scanned(self, tmp_path):
        f = tmp_path / "after_block.adoc"
        f.write_text(
            textwrap.dedent("""\
            ////
            safe inside comment
            ////

            password=RealValue!
        """)
        )
        findings = scan_file(str(f))
        cred = [f for f in findings if f["category"] == "credential"]
        assert len(cred) == 1


# ── collect_files ────────────────────────────────────────────────────────────


class TestCollectFiles:
    def test_collects_matching_files(self, tmp_path):
        modules = tmp_path / "modules"
        modules.mkdir()
        (modules / "guide.adoc").write_text("content")
        (modules / "readme.md").write_text("content")
        (modules / "script.py").write_text("content")

        files = collect_files(str(tmp_path), ["modules"], [".adoc", ".md"])
        names = [f.name for f in files]
        assert "guide.adoc" in names
        assert "readme.md" in names
        assert "script.py" not in names

    def test_skips_missing_subdirectory(self, tmp_path):
        files = collect_files(str(tmp_path), ["nonexistent"], [".adoc"])
        assert files == []

    def test_path_traversal_blocked(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal"):
            collect_files(str(tmp_path), ["../.."], [".adoc"])

    def test_recursive_collection(self, tmp_path):
        nested = tmp_path / "modules" / "sub" / "deep"
        nested.mkdir(parents=True)
        (nested / "file.adoc").write_text("content")

        files = collect_files(str(tmp_path), ["modules"], [".adoc"])
        assert len(files) == 1
        assert files[0].name == "file.adoc"


# ── cmd_scan ─────────────────────────────────────────────────────────────────


class TestCmdScan:
    def test_clean_scan(self, tmp_path):
        f = tmp_path / "clean.adoc"
        f.write_text("= Clean\n\nNothing here.\n")
        result = cmd_scan([f])
        assert result["summary"]["files_scanned"] == 1
        assert result["summary"]["total_findings"] == 0
        assert result["summary"]["files_with_findings"] == 0

    def test_scan_with_findings(self, tmp_path):
        f = tmp_path / "dirty.adoc"
        f.write_text("Connect to 8.8.8.8\npassword=RealValue!\n")
        result = cmd_scan([f])
        assert result["summary"]["total_findings"] >= 2
        assert result["summary"]["files_with_findings"] == 1
        assert "ip" in result["summary"]["by_category"]
        assert "credential" in result["summary"]["by_category"]

    def test_severity_counts(self, tmp_path):
        f = tmp_path / "mixed.adoc"
        f.write_text("8.8.8.8\npassword=RealS3cret!\n")
        result = cmd_scan([f])
        assert result["summary"]["by_severity"]["warning"] >= 1
        assert result["summary"]["by_severity"]["critical"] >= 1


# ── run (CLI integration) ───────────────────────────────────────────────────


class TestRun:
    def _make_args(
        self, paths=None, docs_dir=None, scan_dirs="modules,topics", file_types=".adoc,.md"
    ):
        """Build a namespace matching argparse output."""
        import argparse

        return argparse.Namespace(
            paths=paths or [],
            docs_dir=docs_dir,
            scan_dirs=scan_dirs,
            file_types=file_types,
        )

    def test_exit_code_0_clean(self, tmp_path, capsys):
        f = tmp_path / "clean.adoc"
        f.write_text("= Clean document\n")
        args = self._make_args(paths=[str(f)])
        code = run(args)
        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["summary"]["total_findings"] == 0

    def test_exit_code_1_warnings(self, tmp_path, capsys):
        f = tmp_path / "warn.adoc"
        f.write_text("Connect to 8.8.8.8\n")
        args = self._make_args(paths=[str(f)])
        code = run(args)
        assert code == 1

    def test_exit_code_2_critical(self, tmp_path, capsys):
        f = tmp_path / "crit.adoc"
        f.write_text("password=SuperS3cret!2024\n")
        args = self._make_args(paths=[str(f)])
        code = run(args)
        assert code == 2

    def test_invalid_path_exits(self, tmp_path):
        args = self._make_args(paths=[str(tmp_path / "nope.adoc")])
        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code == 1

    def test_docs_dir_mode(self, tmp_path, capsys):
        modules = tmp_path / "modules"
        modules.mkdir()
        (modules / "guide.adoc").write_text("8.8.8.8\n")
        args = self._make_args(
            docs_dir=str(tmp_path),
            scan_dirs="modules",
            file_types=".adoc",
        )
        code = run(args)
        assert code == 1

    def test_docs_dir_not_a_directory(self, tmp_path):
        args = self._make_args(docs_dir=str(tmp_path / "nope"))
        with pytest.raises(SystemExit) as exc_info:
            run(args)
        assert exc_info.value.code == 1

    def test_json_output_format(self, tmp_path, capsys):
        f = tmp_path / "test.adoc"
        f.write_text("= Doc\n")
        args = self._make_args(paths=[str(f)])
        run(args)
        output = json.loads(capsys.readouterr().out)
        assert "command" in output
        assert "summary" in output
        assert "findings" in output

    def test_no_paths_no_docs_dir(self, capsys):
        args = self._make_args()
        code = run(args)
        assert code == 0


# ── Finding structure ────────────────────────────────────────────────────────


class TestFindingStructure:
    REQUIRED_KEYS = {"file", "line", "category", "matched", "context", "severity", "suggestion"}

    def test_finding_has_all_keys(self):
        findings = scan_line("8.8.8.8", 1, "test.adoc")
        assert len(findings) == 1
        assert set(findings[0].keys()) == self.REQUIRED_KEYS

    def test_credential_finding_severity_is_critical(self):
        findings = scan_line("password=RealS3cret!", 1, "test.adoc")
        cred = [f for f in findings if f["category"] == "credential"]
        assert all(f["severity"] == "critical" for f in cred)

    def test_ip_finding_severity_is_warning(self):
        findings = scan_line("8.8.8.8", 1, "test.adoc")
        assert findings[0]["severity"] == "warning"


# ── TLD regex coverage ──────────────────────────────────────────────────────


class TestTLDCoverage:
    def test_long_tld_detected(self):
        findings = scan_line("Visit custom.technology for info", 1, "test.adoc")
        url_findings = [f for f in findings if f["category"] == "url"]
        assert len(url_findings) == 1

    def test_two_char_tld_detected(self):
        findings = scan_line("See custom.io for docs", 1, "test.adoc")
        url_findings = [f for f in findings if f["category"] == "url"]
        assert len(url_findings) == 1

    def test_single_char_not_tld(self):
        findings = scan_line("version.1 is fine", 1, "test.adoc")
        url_findings = [f for f in findings if f["category"] == "url"]
        assert url_findings == []
