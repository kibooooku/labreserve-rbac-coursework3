"""12表→16表必须保留数据、备份旧库且可重复启动。"""
import sqlite3
from pathlib import Path
from app import create_app
from app.db import get_db

FIXTURE = Path(__file__).parent / "fixtures" / "schema_v1.sql"


def test_v1_migration_preserves_all_existing_data_and_backup(tmp_path):
    database = tmp_path / "daily.sqlite3"
    with sqlite3.connect(database) as db:
        db.executescript(FIXTURE.read_text(encoding="utf-8"))
        untouched = {table: db.execute(f"SELECT * FROM {table}").fetchall() for table in ("users", "roles", "user_roles", "operations", "control_objects", "permissions", "role_permissions", "sessions", "event_audit")}
    app = create_app({"TESTING": True, "DATABASE": str(database), "NOW": "2030-01-01T08:00:00"})
    with app.app_context():
        db = get_db()
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 16
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        for table, expected in untouched.items():
            assert [tuple(row) for row in db.execute(f"SELECT * FROM {table}")] == expected
        assert db.execute("SELECT code,name,description FROM equipment WHERE id=11").fetchone()[:] == ("LEG-011", "保留设备", "原设备说明")
        assert db.execute("SELECT created_by,created_at,updated_at FROM equipment WHERE id=11").fetchone()[:] == (None, None, None)
        assert db.execute("SELECT updated_at FROM reservations WHERE id=21").fetchone()[0] is None
        assert db.execute("SELECT name FROM equipment_categories").fetchone()[0] == "原分类"
        assert db.execute("SELECT location FROM laboratories").fetchone()[0] == "原实验室"
        assert db.execute("SELECT status FROM reservations WHERE id=23").fetchone()[0] == "approved"
        assert db.execute("SELECT reviewer_id,note,reviewed_at FROM reservation_reviews WHERE reservation_id=22").fetchone()[:] == (2, "保留审批意见", None)
        assert db.execute("SELECT checkout_by,checkout_condition,returned_by,return_condition,acceptance_result FROM loans WHERE id=31").fetchone()[:] == (None, "", None, "历史归还检查", "unknown")
        assert db.execute("SELECT checkout_condition FROM loans WHERE id=32").fetchone()[0] == "历史借出检查"
        assert db.execute("SELECT equipment_id,started_by,end_at FROM equipment_maintenance").fetchone()[:] == (12, None, None)
    backups = list((tmp_path / "backups").glob("*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 12
        assert backup.execute("SELECT status,condition_note FROM loans WHERE id=31").fetchone() == ("returned", "历史归还检查")
    # 再次启动不会重新迁移或向真实日常库重复灌入演示账号/数据。
    create_app({"TESTING": True, "DATABASE": str(database)})
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 2


def test_empty_v1_fixture_migration_does_not_touch_other_database(tmp_path):
    daily = tmp_path / "real-daily.sqlite3"
    daily.write_bytes(b"THIS IS AN UNRELATED FILE; NEVER RESET IT")
    empty_v1 = tmp_path / "schema-v1-empty.sqlite3"
    with sqlite3.connect(empty_v1) as db:
        db.executescript(FIXTURE.read_text(encoding="utf-8").split("-- TEST DATA")[0])
    app = create_app({"TESTING": True, "DATABASE": str(empty_v1), "NOW": "2030-01-01T08:00:00"})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM equipment").fetchone()[0] == 9
        assert get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 6
    assert daily.read_bytes() == b"THIS IS AN UNRELATED FILE; NEVER RESET IT"
    assert len(list((tmp_path / "backups").glob("schema-v1-empty-*.sqlite3"))) == 1
