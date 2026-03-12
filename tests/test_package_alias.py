"""Tests for the legacy `open_researcher` compatibility shim."""

import open_researcher
import paperfarm


def test_legacy_package_shim_exposes_version():
    assert open_researcher.__version__ == paperfarm.__version__


def test_legacy_cli_import_still_works():
    from open_researcher.cli import app as legacy_app

    assert legacy_app.info.name == "PaperFarm"
