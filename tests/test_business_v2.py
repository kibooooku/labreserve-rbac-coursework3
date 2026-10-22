"""16表业务模型的跨表一致性、实体设备、维护与权限回归。"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from app.db import get_db
from conftest import event, future_payload, login


def create_catalog(client, csrf):
    lab = event(client, csrf, "laboratory.save", {"code": "LAB-NEW", "name": "新建实验室", "location": "实验楼 E101", "manager_id": 3, "description": "独立业务测试"})
    category = event(client, csrf, "category.save", {"code": "CAT-NEW", "name": "新建分类", "description": "独立分类档案"})
    assert lab.status_code == category.status_code == 200
    return lab.json["data"]["id"], category.json["data"]["id"]


def asset_payload(laboratory_id=1, category_id=1, **overrides):
    payload = {"code": "ASSET-100", "name": "课程同型号设备", "model": "MODEL-100", "laboratory_id": laboratory_id, "category_id": category_id, "location": "E101 一号柜", "lifecycle_status": "active", "description": "每台设备拥有独立资产编号"}
    payload.update(overrides)
    return payload


def approved_booking(student, admin, s, a, **overrides):
    response = event(student, s, "reservation.submit", future_payload(**overrides))
    assert response.status_code == 200, response.json
    rid = response.json["data"]["id"]
    reviewed = event(admin, a, "reservation.approve", {"id": rid, "note": "需求审核通过"})
    assert reviewed.status_code == 200
    return rid


@pytest.mark.parametrize("source,payload", [
    ("laboratory.save", {"code": "NO", "name": "不可创建", "location": "A001"}),
    ("laboratory.set_active", {"id": 1, "active": False}),
    ("category.save", {"code": "NO", "name": "不可创建"}),
    ("category.set_active", {"id": 1, "active": False}),
    ("maintenance.start", {"equipment_id": 6, "reason": "不可操作"}),
    ("maintenance.end", {"id": 1, "result": "不可操作"}),
])
def test_new_events_all_require_equipment_update_and_log_denial(app, client, source, payload):
    s = login(client)
    assert client.get("/api/equipment/metadata").status_code == 200
    assert client.get("/api/maintenance").status_code == 200
    response = event(client, s["csrf_token"], source, payload)
    assert response.status_code == 403
    with app.app_context():
        row = get_db().execute("SELECT source_id,object_code,operation_code,outcome FROM event_audit ORDER BY id DESC LIMIT 1").fetchone()
        assert tuple(row) == (source, "equipment", "update", "denied")


def test_catalog_assets_enable_disable_and_foreign_keys(app, client):
    k = login(client, "keeper")
    csrf = k["csrf_token"]
    lab_id, category_id = create_catalog(client, csrf)
    first = event(client, csrf, "equipment.save", asset_payload(lab_id, category_id)).json["data"]
    second = event(client, csrf, "equipment.save", asset_payload(lab_id, category_id, code="ASSET-101")).json["data"]
    assert first["id"] != second["id"] and first["model"] == second["model"]
    assert first["created_by"] == 3 and first["created_at"] == first["updated_at"] == "2030-01-01T08:00:00"
    assert event(client, csrf, "equipment.save", asset_payload(lab_id, category_id)).status_code == 409
    assert event(client, csrf, "category.set_active", {"id": category_id, "active": False}).status_code == 200
    assets = client.get("/api/equipment").json["data"]
    assert next(r for r in assets if r["id"] == first["id"])["status"] == "disabled"
    assert event(client, csrf, "reservation.submit", future_payload(equipment_id=first["id"])).status_code == 409
    assert event(client, csrf, "category.set_active", {"id": category_id, "active": True}).status_code == 200
    assert event(client, csrf, "laboratory.set_active", {"id": lab_id, "active": False}).status_code == 200
    assert event(client, csrf, "equipment.save", asset_payload(lab_id, category_id, code="ASSET-102")).status_code == 409
    assert event(client, csrf, "laboratory.set_active", {"id": lab_id, "active": True}).status_code == 200
    assert event(client, csrf, "equipment.save", asset_payload(lab_id, category_id, code="ASSET-102")).status_code == 200
    with app.app_context():
        db = get_db()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM laboratories WHERE id=?", (lab_id,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE equipment SET category_id=99999 WHERE id=?", (first["id"],))
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_live_reservations_block_parent_disable_and_equipment_retirement(app):
    student, keeper = app.test_client(), app.test_client()
    s, k = login(student), login(keeper, "keeper")
    response = event(student, s["csrf_token"], "reservation.submit", future_payload())
    assert response.status_code == 200
    device = next(row for row in keeper.get("/api/equipment").json["data"] if row["id"] == 6)
    for source, identity in (("laboratory.set_active", device["laboratory_id"]), ("category.set_active", device["category_id"])):
        assert event(keeper, k["csrf_token"], source, {"id": identity, "active": False}).status_code == 409
    device["lifecycle_status"] = "retired"
    assert event(keeper, k["csrf_token"], "equipment.save", device).status_code == 409
    assert event(keeper, k["csrf_token"], "maintenance.start", {"equipment_id": 6, "reason": "维护冲突"}).status_code == 409


def test_independent_final_review_and_four_stored_states(app):
    student, admin = app.test_client(), app.test_client()
    s, a = login(student), login(admin, "admin")
    rid = approved_booking(student, admin, s["csrf_token"], a["csrf_token"])
    record = next(r for r in student.get("/api/reservations").json["data"] if r["id"] == rid)
    assert record["workflow_status"] == "approved" and record["review_decision"] == "approved" and record["reviewed_at"]
    assert record["updated_at"] == record["reviewed_at"] == "2030-01-01T08:00:00"
    assert event(admin, a["csrf_token"], "reservation.reject", {"id": rid, "note": "禁止二次终审"}).status_code == 409
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM reservation_reviews WHERE reservation_id=?", (rid,)).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO reservation_reviews(reservation_id,reviewer_id,decision,note,reviewed_at) VALUES (?,4,'rejected','重复终审','2030-01-01T08:00:00')", (rid,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE reservations SET status='borrowed' WHERE id=?", (rid,))


def test_return_preserves_checkout_inspection_and_frees_original_slot(app):
    student, admin = app.test_client(), app.test_client()
    s, a = login(student), login(admin, "admin")
    rid = approved_booking(student, admin, s["csrf_token"], a["csrf_token"])
    loan = event(admin, a["csrf_token"], "loan.checkout", {"reservation_id": rid, "checkout_condition": "借出：镜头完好、附件两件"}).json["data"]
    assert loan["checkout_by"] == 4 and loan["checkout_condition"] == "借出：镜头完好、附件两件"
    assert event(student, s["csrf_token"], "reservation.cancel", {"id": rid}).status_code == 409
    returned = event(admin, a["csrf_token"], "loan.return", {"id": loan["id"], "return_condition": "归还：镜头清洁、附件齐全", "acceptance_result": "passed"})
    assert returned.status_code == 200
    row = returned.json["data"]
    assert row["checkout_condition"] == loan["checkout_condition"]
    assert row["checkout_by"] == row["returned_by"] == 4 and row["return_condition"] != row["checkout_condition"]
    assert event(student, s["csrf_token"], "reservation.submit", future_payload()).status_code == 200
    # 预约存储状态只描述申请/审批；API结合借还记录派生已归还。
    with app.app_context():
        assert get_db().execute("SELECT status FROM reservations WHERE id=?", (rid,)).fetchone()[0] == "approved"
        assert get_db().execute("SELECT returned_at FROM loans WHERE reservation_id=?", (rid,)).fetchone()[0]
    record = next(r for r in student.get("/api/reservations").json["data"] if r["id"] == rid)
    assert record["status"] == "returned" and record["workflow_status"] == "approved"


def test_maintenance_complete_history_and_unique_open_record(app, client):
    k = login(client, "keeper")
    csrf = k["csrf_token"]
    opened = event(client, csrf, "maintenance.start", {"equipment_id": 6, "reason": "温度传感器校准"})
    assert opened.status_code == 200
    mid = opened.json["data"]["id"]
    assert opened.json["data"]["started_by"] == 3 and opened.json["data"]["status"] == "open"
    assert event(client, csrf, "reservation.submit", future_payload()).status_code == 409
    assert event(client, csrf, "maintenance.start", {"equipment_id": 6, "reason": "重复维护"}).status_code == 409
    with app.app_context():
        with pytest.raises(sqlite3.IntegrityError):
            get_db().execute("INSERT INTO equipment_maintenance(equipment_id,start_at,reason) VALUES (6,'2030-01-01T08:00:00','重复')")
    assert event(client, csrf, "maintenance.end", {"id": mid, "result": ""}).status_code == 400
    closed = event(client, csrf, "maintenance.end", {"id": mid, "result": "校准完成，检测通过"})
    assert closed.status_code == 200 and closed.json["data"]["ended_by"] == 3
    assert event(client, csrf, "maintenance.end", {"id": mid, "result": "再次完成"}).status_code == 409
    assert event(client, csrf, "reservation.submit", future_payload()).status_code == 200


def test_damaged_return_automatically_blocks_asset_until_maintenance_finishes(app):
    student, admin = app.test_client(), app.test_client()
    s, a = login(student), login(admin, "admin")
    rid = approved_booking(student, admin, s["csrf_token"], a["csrf_token"])
    lid = event(admin, a["csrf_token"], "loan.checkout", {"reservation_id": rid, "checkout_condition": "借出检查完好"}).json["data"]["id"]
    returned = event(admin, a["csrf_token"], "loan.return", {"id": lid, "return_condition": "镜头外壳出现裂纹", "acceptance_result": "damaged"})
    assert returned.status_code == 200
    mid = returned.json["data"]["maintenance_id"]
    assert mid
    device = next(r for r in student.get("/api/equipment").json["data"] if r["id"] == 6)
    assert device["status"] == "maintenance"
    assert event(student, s["csrf_token"], "reservation.submit", future_payload()).status_code == 409
    assert event(admin, a["csrf_token"], "maintenance.end", {"id": mid, "result": "更换外壳并复检通过"}).status_code == 200
    assert event(student, s["csrf_token"], "reservation.submit", future_payload()).status_code == 200


def test_invalid_return_rolls_back_without_losing_checkout(app):
    student, admin = app.test_client(), app.test_client()
    s, a = login(student), login(admin, "admin")
    rid = approved_booking(student, admin, s["csrf_token"], a["csrf_token"])
    lid = event(admin, a["csrf_token"], "loan.checkout", {"reservation_id": rid, "checkout_condition": "原借出检查"}).json["data"]["id"]
    assert event(admin, a["csrf_token"], "loan.return", {"id": lid, "return_condition": "未知结果", "acceptance_result": "unknown"}).status_code == 400
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT returned_at,checkout_condition FROM loans WHERE id=?", (lid,)).fetchone()[:] == (None, "原借出检查")
        assert db.execute("SELECT COUNT(*) FROM equipment_maintenance WHERE loan_id=?", (lid,)).fetchone()[0] == 0


def test_concurrent_maintenance_starts_serialize(app):
    barrier = Barrier(2)
    clients = [app.test_client(), app.test_client()]
    identities = [login(c, "keeper") for c in clients]

    def start(index):
        barrier.wait(timeout=10)
        return event(clients[index], identities[index]["csrf_token"], "maintenance.start", {"equipment_id": 6, "reason": "并发校准申请"}).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(start, (0, 1)))
    assert sorted(results) == [200, 409]
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM equipment_maintenance WHERE equipment_id=6 AND end_at IS NULL").fetchone()[0] == 1


def test_retired_asset_cannot_be_reactivated_and_legacy_failure_is_atomic(app, client):
    k = login(client, "keeper")
    csrf = k["csrf_token"]
    fresh = event(client, csrf, "equipment.save", asset_payload()).json["data"]
    fresh["lifecycle_status"] = "retired"
    assert event(client, csrf, "equipment.save", fresh).status_code == 200
    fresh["lifecycle_status"] = "active"
    assert event(client, csrf, "equipment.save", fresh).status_code == 409
    original = next(r for r in client.get("/api/equipment").json["data"] if r["id"] == 1)
    legacy = {**original, "name": "失败事务不能保存这个名称", "status": "maintenance"}
    assert event(client, csrf, "equipment.save", legacy).status_code == 409
    with app.app_context():
        assert get_db().execute("SELECT name FROM equipment WHERE id=1").fetchone()[0] == original["name"]
