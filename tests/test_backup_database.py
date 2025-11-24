"""
Unit tests for the database backup script.

Tests cover the main backup and cleanup functions to ensure reliability
and correct error handling.
"""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the functions to test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from backup_database import backup_database, cleanup_old_backups


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, data TEXT)")
    conn.execute("INSERT INTO test_table (data) VALUES ('test data')")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def backup_dir(tmp_path):
    """Create a temporary backup directory."""
    return tmp_path / "backups"


class TestBackupDatabase:
    """Tests for the backup_database function."""

    def test_basic_backup(self, temp_db, backup_dir):
        """Test that a basic backup is created successfully."""
        backup_file = backup_database(
            db_path=str(temp_db),
            backup_dir=str(backup_dir),
            keep_days=0  # Disable cleanup for this test
        )

        # Check backup file exists
        assert backup_file.exists()
        assert backup_file.is_file()

        # Check backup is in correct directory
        assert backup_file.parent == backup_dir

        # Check filename format (should contain timestamp)
        assert "backup_" in backup_file.name
        assert backup_file.suffix == ".db"

        # Verify backup contains the data
        conn = sqlite3.connect(backup_file)
        cursor = conn.execute("SELECT data FROM test_table")
        result = cursor.fetchone()
        assert result[0] == "test data"
        conn.close()

    def test_backup_creates_directory(self, temp_db, backup_dir):
        """Test that backup directory is created if it doesn't exist."""
        assert not backup_dir.exists()

        backup_database(
            db_path=str(temp_db),
            backup_dir=str(backup_dir),
            keep_days=0
        )

        assert backup_dir.exists()
        assert backup_dir.is_dir()

    def test_backup_nonexistent_database(self, backup_dir):
        """Test that backing up a nonexistent database raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            backup_database(
                db_path="nonexistent.db",
                backup_dir=str(backup_dir),
                keep_days=0
            )

    def test_backup_preserves_file_size(self, temp_db, backup_dir):
        """Test that backup file size matches source database."""
        original_size = temp_db.stat().st_size

        backup_file = backup_database(
            db_path=str(temp_db),
            backup_dir=str(backup_dir),
            keep_days=0
        )

        backup_size = backup_file.stat().st_size
        assert backup_size == original_size

    def test_multiple_backups_have_different_timestamps(self, temp_db, backup_dir):
        """Test that multiple backups create unique files."""
        backup1 = backup_database(
            db_path=str(temp_db),
            backup_dir=str(backup_dir),
            keep_days=0
        )

        # Small delay to ensure different timestamp
        import time
        time.sleep(1)

        backup2 = backup_database(
            db_path=str(temp_db),
            backup_dir=str(backup_dir),
            keep_days=0
        )

        assert backup1 != backup2
        assert backup1.exists() and backup2.exists()


class TestCleanupOldBackups:
    """Tests for the cleanup_old_backups function."""

    def create_test_backup(self, backup_dir, days_old, db_name="test"):
        """Helper to create a test backup file with specific age."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"{db_name}_backup_{timestamp}.db"
        backup_file.touch()

        # Set modification time to simulate old file
        old_time = (datetime.now() - timedelta(days=days_old)).timestamp()
        import os
        os.utime(backup_file, (old_time, old_time))

        return backup_file

    def test_cleanup_removes_old_backups(self, backup_dir):
        """Test that old backups are removed."""
        backup_dir.mkdir()

        # Create backups of different ages
        old_backup = self.create_test_backup(backup_dir, days_old=10)
        recent_backup = self.create_test_backup(backup_dir, days_old=2)

        # Cleanup backups older than 7 days
        deleted = cleanup_old_backups(backup_dir, keep_days=7, db_name="test")

        # Old backup should be deleted
        assert not old_backup.exists()
        assert old_backup in deleted

        # Recent backup should still exist
        assert recent_backup.exists()
        assert recent_backup not in deleted

    def test_cleanup_keeps_recent_backups(self, backup_dir):
        """Test that recent backups are preserved."""
        backup_dir.mkdir()

        # Create recent backups
        backup1 = self.create_test_backup(backup_dir, days_old=1)
        backup2 = self.create_test_backup(backup_dir, days_old=3)

        # Cleanup backups older than 7 days
        deleted = cleanup_old_backups(backup_dir, keep_days=7, db_name="test")

        assert len(deleted) == 0
        assert backup1.exists()
        assert backup2.exists()

    def test_cleanup_with_no_backups(self, backup_dir):
        """Test cleanup when no backups exist."""
        backup_dir.mkdir()

        deleted = cleanup_old_backups(backup_dir, keep_days=7, db_name="test")

        assert len(deleted) == 0

    def test_cleanup_only_removes_matching_db_name(self, backup_dir):
        """Test that cleanup only removes backups for specified database."""
        backup_dir.mkdir()

        # Create backups for different databases
        test_backup = self.create_test_backup(backup_dir, days_old=10, db_name="test")
        other_backup = self.create_test_backup(backup_dir, days_old=10, db_name="other")

        # Cleanup only "test" database backups
        deleted = cleanup_old_backups(backup_dir, keep_days=7, db_name="test")

        # Only test backup should be deleted
        assert not test_backup.exists()
        assert other_backup.exists()
        assert len(deleted) == 1


class TestIntegration:
    """Integration tests for backup with cleanup."""

    def test_backup_with_cleanup(self, temp_db, backup_dir):
        """Test full backup workflow with automatic cleanup."""
        backup_dir.mkdir()

        # Create an old backup manually
        old_backup = backup_dir / "test_backup_20200101_120000.db"
        old_backup.touch()
        old_time = (datetime.now() - timedelta(days=40)).timestamp()
        import os
        os.utime(old_backup, (old_time, old_time))

        # Run backup with cleanup enabled
        new_backup = backup_database(
            db_path=str(temp_db),
            backup_dir=str(backup_dir),
            keep_days=30
        )

        # New backup should exist
        assert new_backup.exists()

        # Old backup should be removed (older than 30 days)
        assert not old_backup.exists()
