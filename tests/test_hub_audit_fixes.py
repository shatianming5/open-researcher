"""Tests for hub.py and hub_cmd.py P0+P1 audit fixes."""

from __future__ import annotations

import json
import socket
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ── hub.py _fetch_json fixes ──


class TestFetchJsonErrorHandling:
    """P0: _fetch_json handles socket.timeout, UnicodeDecodeError, empty response."""

    def test_socket_timeout_raises_valueerror(self):
        from open_researcher.hub import _fetch_json

        with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            with pytest.raises(ValueError, match="Timeout"):
                _fetch_json("https://example.com/test.json")

    def test_unicode_decode_error_raises_valueerror(self):
        from open_researcher.hub import _fetch_json

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"\xff\xfe"  # invalid UTF-8

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ValueError, match="Invalid encoding"):
                _fetch_json("https://example.com/test.json")

    def test_empty_response_raises_valueerror(self):
        from open_researcher.hub import _fetch_json

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b""

        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ValueError, match="Empty response"):
                _fetch_json("https://example.com/test.json")

    def test_url_error_reason_none(self):
        from open_researcher.hub import _fetch_json

        exc = urllib.error.URLError(reason=None)
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(ValueError, match="Network error"):
                _fetch_json("https://example.com/test.json")

    def test_valid_json_parses(self):
        from open_researcher.hub import _fetch_json

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"key": "value"}).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _fetch_json("https://example.com/test.json")
            assert result == {"key": "value"}


# ── hub.py fetch_index fixes ──


class TestFetchIndexTypeValidation:
    """P1: fetch_index validates entry types."""

    def test_rejects_non_string_arxiv_id(self):
        from open_researcher.hub import fetch_index

        index_data = {
            "entries": [
                {"arxiv_id": "2507.19457", "folder": "paper1"},
                {"arxiv_id": 12345, "folder": "paper2"},  # non-string
                {"arxiv_id": "2507.19458", "folder": "paper3"},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(index_data).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_index("https://example.com")
            assert "2507.19457" in result
            assert "2507.19458" in result
            # Non-string arxiv_id should be rejected
            assert 12345 not in result

    def test_rejects_empty_folder(self):
        from open_researcher.hub import fetch_index

        index_data = {
            "entries": [
                {"arxiv_id": "2507.19457", "folder": ""},  # empty
                {"arxiv_id": "2507.19458", "folder": "paper2"},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(index_data).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = fetch_index("https://example.com")
            assert "2507.19457" not in result
            assert "2507.19458" in result


# ── hub.py fetch_manifest fixes ──


class TestFetchManifestUrlSafety:
    """P0: fetch_manifest URL-encodes folder name and injects _folder."""

    def test_folder_url_encoded(self):
        from open_researcher.hub import fetch_manifest

        index_data = {
            "entries": [{"arxiv_id": "2507.19457", "folder": "path with spaces"}]
        }
        manifest_data = {"paper": {"title": "Test"}}

        call_count = [0]
        def mock_urlopen(url, **kwargs):
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            call_count[0] += 1
            if call_count[0] == 1:
                resp.read.return_value = json.dumps(index_data).encode("utf-8")
            else:
                # Verify URL is encoded
                assert "path%20with%20spaces" in url
                assert "path with spaces" not in url
                resp.read.return_value = json.dumps(manifest_data).encode("utf-8")
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = fetch_manifest("2507.19457")
            assert result["_folder"] == "path with spaces"
            assert result["paper"]["title"] == "Test"

    def test_folder_field_injected(self):
        from open_researcher.hub import fetch_manifest

        index_data = {"entries": [{"arxiv_id": "2507.19457", "folder": "my-paper"}]}
        manifest_data = {"paper": {"title": "Test"}}

        call_count = [0]
        def mock_urlopen(url, **kwargs):
            resp = MagicMock()
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            call_count[0] += 1
            if call_count[0] == 1:
                resp.read.return_value = json.dumps(index_data).encode("utf-8")
            else:
                resp.read.return_value = json.dumps(manifest_data).encode("utf-8")
            return resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = fetch_manifest("2507.19457")
            assert result["_folder"] == "my-paper"


# ── hub.py manifest_summary type safety ──


class TestManifestSummaryTypeSafety:
    """P1: manifest_summary handles non-dict nested fields."""

    def test_non_dict_paper(self):
        from open_researcher.hub import manifest_summary

        manifest = {"paper": "not a dict", "env": None, "resources": 42}
        result = manifest_summary(manifest)
        assert isinstance(result, str)

    def test_normal_manifest(self):
        from open_researcher.hub import manifest_summary

        manifest = {
            "paper": {"title": "Test Paper", "arxiv_id": "2507.19457"},
            "env": {"manager": "openai", "python": "3.11"},
            "resources": {"gpu": "required"},
            "status": {"verified": True, "verified_count": 3},
        }
        result = manifest_summary(manifest)
        assert "Test Paper" in result
        assert "2507.19457" in result


# ── hub.py manifest_to_bootstrap_overrides type safety ──


class TestManifestOverridesTypeSafety:
    """P1: manifest_to_bootstrap_overrides handles non-dict env/resources."""

    def test_non_dict_env(self):
        from open_researcher.hub import manifest_to_bootstrap_overrides

        result = manifest_to_bootstrap_overrides({"env": "bad", "resources": None})
        assert result == {}

    def test_normal_overrides(self):
        from open_researcher.hub import manifest_to_bootstrap_overrides

        manifest = {
            "env": {"install_command": "pip install -e .", "test_command": "pytest"},
            "resources": {"gpu": "required"},
        }
        result = manifest_to_bootstrap_overrides(manifest)
        assert result["install_command"] == "pip install -e ."
        assert result["smoke_command"] == "pytest"
        assert result["requires_gpu"] is True


# ── hub.py apply_manifest_to_config_yaml atomic write ──


class TestApplyManifestAtomicWrite:
    """P1: apply_manifest_to_config_yaml uses atomic write."""

    def test_writes_config_atomically(self, tmp_path):
        from open_researcher.hub import apply_manifest_to_config_yaml

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"research": {"goal": "test"}}))

        manifest = {
            "paper": {"arxiv_id": "2507.19457"},
            "env": {"install_command": "pip install -e ."},
            "_folder": "my-paper",
        }
        result = apply_manifest_to_config_yaml(manifest, tmp_path)
        assert "install_command" in result

        # Verify file content is valid YAML
        data = yaml.safe_load(config_path.read_text())
        assert data["bootstrap"]["install_command"] == "pip install -e ."
        assert data["bootstrap"]["hub_arxiv_id"] == "2507.19457"

    def test_no_tmp_files_left(self, tmp_path):
        from open_researcher.hub import apply_manifest_to_config_yaml

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"bootstrap": {}}))

        manifest = {
            "paper": {"arxiv_id": "test"},
            "env": {"install_command": "echo test"},
            "_folder": "test-folder",
        }
        apply_manifest_to_config_yaml(manifest, tmp_path)

        # No .tmp files should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []


# ── hub_cmd.py shell injection fix ──


class TestHubCmdShellInjection:
    """P0: install command uses shlex.split instead of shell=True."""

    def test_shlex_split_used(self):
        import inspect

        import open_researcher.hub_cmd as mod

        source = inspect.getsource(mod)
        # Should NOT contain shell=True
        assert "shell=True" not in source
        # Should use shlex.split
        assert "shlex.split" in source


# ── hub_cmd.py temp file cleanup ──


class TestHubCmdTempFileCleanup:
    """P0: Temp file is cleaned up in finally block."""

    def test_cleanup_in_source(self):
        import inspect

        import open_researcher.hub_cmd as mod

        source = inspect.getsource(mod)
        assert "os.unlink(tmp_path)" in source
        assert "finally:" in source


# ── hub_cmd.py broad exception fix ──


class TestHubCmdExceptionHandling:
    """P0: smoke_test.py fetch uses specific exceptions."""

    def test_no_broad_except_exception_in_http(self):
        import inspect

        import open_researcher.hub_cmd as mod

        source = inspect.getsource(mod.install)
        # The HTTP fetch block should use specific exceptions, not broad except.
        # The torch GPU check legitimately uses `except Exception as exc:` (Round 6 P0 fix).
        count = source.count("except Exception as exc:")
        assert count <= 1, f"Found {count} broad except clauses; only the torch GPU check is allowed"


# ── hub_cmd.py subprocess timeout ──


class TestHubCmdSubprocessTimeout:
    """P1: subprocess.run calls have timeout."""

    def test_timeout_in_source(self):
        import inspect

        import open_researcher.hub_cmd as mod

        source = inspect.getsource(mod.install)
        assert "timeout=" in source


# ── hub_cmd.py env_block type safety ──


class TestHubCmdEnvBlockTypeSafety:
    """P1: env_block handles non-dict values."""

    def test_non_dict_env_handled(self):
        # This is a source inspection test since we can't easily invoke CLI
        import inspect

        import open_researcher.hub_cmd as mod

        source = inspect.getsource(mod.install)
        assert "isinstance" in source


# ── hub_cmd.py URL encoding ──


class TestHubCmdUrlEncoding:
    """P1: smoke_test.py URL uses quote() for folder."""

    def test_url_quote_in_source(self):
        import inspect

        import open_researcher.hub_cmd as mod

        source = inspect.getsource(mod.install)
        assert "quote(folder" in source
