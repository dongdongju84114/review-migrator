from __future__ import annotations

import sys
from pathlib import Path

from review_migrator import gui_paths


def test_frozen_app_uses_documents_for_output_dir(monkeypatch, tmp_path):
    exe_path = tmp_path / "ReviewMigratorGUI.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))
    monkeypatch.setattr(gui_paths.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("REVIEW_MIGRATOR_OUTPUT_DIR", raising=False)

    assert gui_paths.default_output_dir() == tmp_path / "Documents" / "ReviewMigrator" / "operator_runs"


def test_frozen_app_uses_env_file_next_to_exe(monkeypatch, tmp_path):
    exe_path = tmp_path / "ReviewMigratorGUI.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_path))
    monkeypatch.delenv("REVIEW_MIGRATOR_ENV_FILE", raising=False)

    assert gui_paths.default_env_file() == tmp_path / ".env"


def test_environment_overrides_gui_paths(monkeypatch, tmp_path):
    output_dir = tmp_path / "runs"
    env_file = tmp_path / "settings.env"
    monkeypatch.setenv("REVIEW_MIGRATOR_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("REVIEW_MIGRATOR_ENV_FILE", str(env_file))

    assert gui_paths.default_output_dir() == output_dir
    assert gui_paths.default_env_file() == env_file
