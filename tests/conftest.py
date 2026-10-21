"""每例复制初始化数据库：隔离业务数据，又避免重复计算演示密码哈希。"""
import shutil
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app


@pytest.fixture(scope="session")
def seeded_database(tmp_path_factory):
    database = tmp_path_factory.mktemp("seed") / "seed.sqlite3"
    create_app({"TESTING": True, "DATABASE": str(database), "NOW": "2030-01-01T08:00:00"})
    return database


@pytest.fixture
def app(tmp_path, seeded_database):
    database = tmp_path / "test.sqlite3"
    shutil.copyfile(seeded_database, database)
    return create_app({"TESTING": True, "DATABASE": str(database), "NOW": "2030-01-01T08:00:00"})


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="student"):
    response = client.post("/api/login", json={"username": username, "password": "Lab@2026!"})
    assert response.status_code == 200
    return response.json["data"]


def event(client, csrf, source, payload, **extra):
    return client.post("/api/events", json={"source_id": source, "payload": payload, **extra}, headers={"X-CSRF-Token": csrf})


def future_payload(**overrides):
    payload = {"equipment_id": 6, "start_at": "2030-02-01T09:00", "end_at": "2030-02-01T11:00", "purpose": "课程设备实践与数据采集"}
    payload.update(overrides)
    return payload
