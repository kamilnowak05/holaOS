# ruff: noqa: S101

from __future__ import annotations

import sqlite3
from pathlib import Path

from sandbox_agent_runtime import runtime_local_state as state_module


def test_workspace_registry_round_trip_uses_hidden_identity_file(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("HOLABOSS_RUNTIME_DB_PATH", str(db_path))
    monkeypatch.setattr(state_module, "WORKSPACE_ROOT", str(workspace_root))

    created = state_module.create_workspace(
        workspace_id="workspace-1",
        name="Acme",
        harness="opencode",
        status="active",
    )

    identity_path = workspace_root / "workspace-1" / ".holaboss" / "workspace_id"
    assert identity_path.is_file()
    assert identity_path.read_text(encoding="utf-8").strip() == "workspace-1"
    assert created.id == "workspace-1"
    assert state_module.get_workspace("workspace-1") == created
    assert [record.id for record in state_module.list_workspaces()] == ["workspace-1"]

    with state_module.runtime_db_connection() as conn:
        tables = {
            str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        row = conn.execute("SELECT workspace_path FROM workspaces WHERE id = ?", ("workspace-1",)).fetchone()
    assert "workspaces" in tables
    assert row is not None
    assert Path(str(row["workspace_path"])) == workspace_root / "workspace-1"


def test_runtime_schema_migrates_workspace_rows_to_registry_and_identity_file(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("HOLABOSS_RUNTIME_DB_PATH", str(db_path))
    monkeypatch.setattr(state_module, "WORKSPACE_ROOT", str(workspace_root))

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE workspaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            harness TEXT,
            main_session_id TEXT,
            error_message TEXT,
            onboarding_status TEXT NOT NULL,
            onboarding_session_id TEXT,
            onboarding_completed_at TEXT,
            onboarding_completion_summary TEXT,
            onboarding_requested_at TEXT,
            onboarding_requested_by TEXT,
            created_at TEXT,
            updated_at TEXT,
            deleted_at_utc TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO workspaces (
            id, name, status, harness, main_session_id, error_message,
            onboarding_status, onboarding_session_id, onboarding_completed_at,
            onboarding_completion_summary, onboarding_requested_at, onboarding_requested_by,
            created_at, updated_at, deleted_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "workspace-legacy",
            "Legacy",
            "active",
            "opencode",
            "session-1",
            None,
            "not_required",
            None,
            None,
            None,
            None,
            None,
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
            None,
        ),
    )
    conn.commit()
    conn.close()

    rows = state_module.list_workspaces()

    assert [record.id for record in rows] == ["workspace-legacy"]
    identity_path = workspace_root / "workspace-legacy" / ".holaboss" / "workspace_id"
    assert identity_path.is_file()
    assert identity_path.read_text(encoding="utf-8").strip() == "workspace-legacy"

    with state_module.runtime_db_connection() as conn_after:
        tables = {
            str(row["name"])
            for row in conn_after.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        row = conn_after.execute("SELECT workspace_path FROM workspaces WHERE id = ?", ("workspace-legacy",)).fetchone()
    assert "workspaces" in tables
    assert row is not None
    assert Path(str(row["workspace_path"])) == workspace_root / "workspace-legacy"


def test_workspace_dir_recovers_when_folder_is_renamed(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("HOLABOSS_RUNTIME_DB_PATH", str(db_path))
    monkeypatch.setattr(state_module, "WORKSPACE_ROOT", str(workspace_root))

    state_module.create_workspace(workspace_id="workspace-1", name="Acme", harness="opencode", status="active")
    original_path = workspace_root / "workspace-1"
    renamed_path = workspace_root / "workspace-renamed"
    original_path.rename(renamed_path)

    resolved = state_module.workspace_dir("workspace-1")

    assert resolved == renamed_path
    with state_module.runtime_db_connection() as conn:
        row = conn.execute("SELECT workspace_path FROM workspaces WHERE id = ?", ("workspace-1",)).fetchone()
    assert row is not None
    assert Path(str(row["workspace_path"])) == renamed_path


def test_get_workspace_recovers_missing_row_from_identity_file(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("HOLABOSS_RUNTIME_DB_PATH", str(db_path))
    monkeypatch.setenv("SANDBOX_AGENT_HARNESS", "opencode")
    monkeypatch.setattr(state_module, "WORKSPACE_ROOT", str(workspace_root))

    state_module.create_workspace(workspace_id="workspace-1", name="Acme", harness="opencode", status="active")
    with state_module.runtime_db_connection() as conn:
        conn.execute("DELETE FROM workspaces WHERE id = ?", ("workspace-1",))

    recovered = state_module.get_workspace("workspace-1")

    assert recovered is not None
    assert recovered.id == "workspace-1"
    assert recovered.name == "workspace-1"
    assert recovered.harness == "opencode"
    assert recovered.status == "active"
    with state_module.runtime_db_connection() as conn:
        row = conn.execute(
            "SELECT id, workspace_path, harness, status FROM workspaces WHERE id = ?",
            ("workspace-1",),
        ).fetchone()
    assert row is not None
    assert str(row["id"]) == "workspace-1"
    assert Path(str(row["workspace_path"])) == workspace_root / "workspace-1"
    assert str(row["harness"]) == "opencode"
    assert str(row["status"]) == "active"
