"""Tests for git_pr_reader.py reply_to_comment functionality."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from git_pr_reader import GitHubReviewAPI, GitLabReviewAPI, cmd_reply


class TestGitHubReplyToComment:
    """Tests for GitHubReviewAPI.reply_to_comment()."""

    def _make_api(self):
        with patch.object(GitHubReviewAPI, "__init__", lambda self, *a, **kw: None):
            api = GitHubReviewAPI.__new__(GitHubReviewAPI)
        api._pr = MagicMock()
        return api

    def test_success(self):
        api = self._make_api()

        ok, err = api.reply_to_comment(comment_id=42, body="LGTM")

        assert ok is True
        assert err == ""
        api._pr.create_review_comment_reply.assert_called_once_with(42, "LGTM")

    def test_api_error(self):
        api = self._make_api()
        api._pr.create_review_comment_reply.side_effect = RuntimeError("rate limited")

        ok, err = api.reply_to_comment(comment_id=42, body="LGTM")

        assert ok is False
        assert "rate limited" in err

    def test_discussion_id_accepted_but_ignored(self):
        api = self._make_api()

        ok, err = api.reply_to_comment(comment_id=42, body="ok", discussion_id="abc123")

        assert ok is True
        api._pr.create_review_comment_reply.assert_called_once_with(42, "ok")


class TestGitLabReplyToComment:
    """Tests for GitLabReviewAPI.reply_to_comment()."""

    def _make_api(self):
        with patch.object(GitLabReviewAPI, "__init__", lambda self, *a, **kw: None):
            api = GitLabReviewAPI.__new__(GitLabReviewAPI)
        api._mr = MagicMock()
        return api

    def test_success(self):
        api = self._make_api()
        mock_discussion = MagicMock()
        api._mr.discussions.get.return_value = mock_discussion

        ok, err = api.reply_to_comment(comment_id=1, body="Fixed", discussion_id="abc123")

        assert ok is True
        assert err == ""
        api._mr.discussions.get.assert_called_once_with("abc123")
        mock_discussion.notes.create.assert_called_once_with({"body": "Fixed"})

    def test_missing_discussion_id(self):
        api = self._make_api()

        ok, err = api.reply_to_comment(comment_id=1, body="Fixed")

        assert ok is False
        assert "discussion_id is required" in err

    def test_discussion_not_found(self):
        api = self._make_api()
        api._mr.discussions.get.side_effect = Exception("404 Not Found")

        ok, err = api.reply_to_comment(comment_id=1, body="Fixed", discussion_id="bad")

        assert ok is False
        assert "404" in err

    def test_notes_create_error(self):
        api = self._make_api()
        mock_discussion = MagicMock()
        mock_discussion.notes.create.side_effect = RuntimeError("forbidden")
        api._mr.discussions.get.return_value = mock_discussion

        ok, err = api.reply_to_comment(comment_id=1, body="Fixed", discussion_id="abc123")

        assert ok is False
        assert "forbidden" in err


class TestCmdReply:
    """Tests for cmd_reply() CLI handler."""

    def _make_args(self, **overrides):
        defaults = {
            "pr_url": "https://github.com/owner/repo/pull/1",
            "comment_id": 42,
            "discussion_id": None,
            "body": "Applied the fix.",
            "signoff": "",
            "dry_run": False,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    @patch("git_pr_reader.GitReviewAPI.from_url")
    def test_github_success(self, mock_from_url):
        mock_api = MagicMock(spec=GitHubReviewAPI)
        mock_api.reply_to_comment.return_value = (True, "")
        mock_from_url.return_value = mock_api

        result = cmd_reply(self._make_args())

        assert result == 0
        mock_api.reply_to_comment.assert_called_once_with(
            comment_id=42,
            body="Applied the fix.",
            discussion_id=None,
        )

    @patch("git_pr_reader.GitReviewAPI.from_url")
    def test_github_missing_comment_id(self, mock_from_url):
        mock_api = MagicMock(spec=GitHubReviewAPI)
        mock_from_url.return_value = mock_api

        result = cmd_reply(self._make_args(comment_id=None))

        assert result == 1
        mock_api.reply_to_comment.assert_not_called()

    @patch("git_pr_reader.GitReviewAPI.from_url")
    def test_gitlab_success(self, mock_from_url):
        mock_api = MagicMock(spec=GitLabReviewAPI)
        mock_api.reply_to_comment.return_value = (True, "")
        mock_from_url.return_value = mock_api

        args = self._make_args(
            pr_url="https://gitlab.com/group/project/-/merge_requests/1",
            comment_id=None,
            discussion_id="abc123",
        )
        result = cmd_reply(args)

        assert result == 0
        mock_api.reply_to_comment.assert_called_once_with(
            comment_id=0,
            body="Applied the fix.",
            discussion_id="abc123",
        )

    @patch("git_pr_reader.GitReviewAPI.from_url")
    def test_gitlab_missing_discussion_id(self, mock_from_url):
        mock_api = MagicMock(spec=GitLabReviewAPI)
        mock_from_url.return_value = mock_api

        args = self._make_args(
            pr_url="https://gitlab.com/group/project/-/merge_requests/1",
            comment_id=None,
            discussion_id=None,
        )
        result = cmd_reply(args)

        assert result == 1
        mock_api.reply_to_comment.assert_not_called()

    @patch("git_pr_reader.GitReviewAPI.from_url")
    def test_dry_run(self, mock_from_url):
        mock_api = MagicMock(spec=GitHubReviewAPI)
        mock_from_url.return_value = mock_api

        result = cmd_reply(self._make_args(dry_run=True))

        assert result == 0
        mock_api.reply_to_comment.assert_not_called()

    @patch("git_pr_reader.GitReviewAPI.from_url")
    def test_signoff_appended(self, mock_from_url):
        mock_api = MagicMock(spec=GitHubReviewAPI)
        mock_api.reply_to_comment.return_value = (True, "")
        mock_from_url.return_value = mock_api

        result = cmd_reply(self._make_args(signoff="Claude Code action-comments (CI)"))

        assert result == 0
        call_body = mock_api.reply_to_comment.call_args.kwargs["body"]
        assert "Applied the fix." in call_body
        assert "\U0001f916 Claude Code action-comments (CI)" in call_body

    @patch("git_pr_reader.GitReviewAPI.from_url")
    def test_no_signoff_when_empty(self, mock_from_url):
        mock_api = MagicMock(spec=GitHubReviewAPI)
        mock_api.reply_to_comment.return_value = (True, "")
        mock_from_url.return_value = mock_api

        result = cmd_reply(self._make_args(signoff=""))

        assert result == 0
        call_body = mock_api.reply_to_comment.call_args.kwargs["body"]
        assert call_body == "Applied the fix."

    @patch("git_pr_reader.GitReviewAPI.from_url")
    def test_failure_returns_1(self, mock_from_url):
        mock_api = MagicMock(spec=GitHubReviewAPI)
        mock_api.reply_to_comment.return_value = (False, "API error")
        mock_from_url.return_value = mock_api

        result = cmd_reply(self._make_args())

        assert result == 1

    @patch("git_pr_reader.GitReviewAPI.from_url")
    def test_invalid_url(self, mock_from_url):
        mock_from_url.side_effect = ValueError("Unsupported URL")

        result = cmd_reply(self._make_args(pr_url="https://example.com/bad"))

        assert result == 1
