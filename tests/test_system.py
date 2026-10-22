"""验证权限和业务边界，包含真实多连接竞争与整条借还流程。"""
import csv
import io
import sqlite3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from app.db import get_db
from app.auth import token_hash
from conftest import event, future_payload, login


def test_seed_login_password_hash_and_session_cookie(app, client):
    identity = login(client)
    assert identity["user"]["username"] == "student"
    assert "reservation:create" in identity["permissions"]
    response = client.post("/api/login", json={"username": "student", "password": "Lab@2026!"})
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    raw_cookie = client.get_cookie("labreserve_session").value
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT password_hash FROM users WHERE username='student'").fetchone()[0] != "Lab@2026!"
        assert db.execute("SELECT 1 FROM sessions WHERE token_hash=?", (raw_cookie,)).fetchone() is None
        assert db.execute("SELECT 1 FROM sessions WHERE token_hash=?", (token_hash(raw_cookie),)).fetchone()


def test_seed_loan_timestamps_follow_reservation_history(app):
    with app.app_context():
        rows = get_db().execute("SELECT r.created_at,r.start_at,r.end_at,l.checkout_at,l.returned_at,CASE WHEN l.returned_at IS NULL THEN 'borrowed' ELSE 'returned' END AS status FROM loans l JOIN reservations r ON r.id=l.reservation_id").fetchall()
        assert {row["status"] for row in rows} == {"borrowed", "returned"}
        clock = datetime.fromisoformat(app.config["NOW"])
        for row in rows:
            created, start, end, checkout = [datetime.fromisoformat(row[field]) for field in ("created_at", "start_at", "end_at", "checkout_at")]
            assert created < start <= checkout < end and checkout <= clock
            if row["status"] == "returned":
                assert checkout <= datetime.fromisoformat(row["returned_at"]) <= end < clock
            else:
                assert row["returned_at"] is None and clock < end


@pytest.mark.parametrize("username", ["student", "teacher", "keeper", "admin", "auditor", "multi"])
def test_all_seed_accounts_can_log_in(client, username):
    assert login(client, username)["user"]["username"] == username


def test_anonymous_wrong_password_and_logout(client):
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login", json={"username": "student", "password": "wrong"}).status_code == 401
    auth = login(client)
    assert client.post("/api/logout").status_code == 403
    assert client.post("/api/logout", headers={"X-CSRF-Token": auth["csrf_token"]}).status_code == 200
    assert client.get("/api/me").status_code == 401


def test_seven_rbac_tables_and_composite_foreign_keys(app):
    with app.app_context():
        db = get_db()
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"users", "roles", "user_roles", "operations", "control_objects", "permissions", "role_permissions"}.issubset(names)
        assert len(names) == 16
        permissions_pk = {r[1] for r in db.execute("PRAGMA table_info(permissions)") if r[5]}
        assert permissions_pk == {"operation_id", "object_id"}
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO user_roles VALUES (9999,1)")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO role_permissions VALUES (1,9999,9999)")


def test_multi_role_union_and_student_data_scope(app, client):
    auth = login(client, "multi")
    assert {r["code"] for r in auth["user"]["roles"]} == {"student", "teacher"}
    assert "reservation:approve" in auth["permissions"] and "reservation:create" in auth["permissions"]
    assert len(client.get("/api/reservations").json["data"]) == 7
    login(client, "student")
    rows = client.get("/api/reservations").json["data"]
    assert rows and all(row["user_id"] == 1 for row in rows)
    assert client.get("/api/audit").status_code == 403
    assert client.get("/api/rbac").status_code == 403


def test_fixed_registry_ignores_forged_authorization_fields(client):
    auth = login(client)
    response = event(client, auth["csrf_token"], "reservation.approve", {"id": 1}, object_code="equipment", operation_code="view", handler="save_role_permissions")
    assert response.status_code == 403
    unknown = event(client, auth["csrf_token"], "business.delete_all", {})
    assert unknown.status_code == 400


def test_csrf_and_cross_origin_are_blocked(app, client):
    auth = login(client)
    assert client.post("/api/events", json={"source_id": "reservation.submit", "payload": future_payload()}).status_code == 403
    response = client.post("/api/events", json={"source_id": "reservation.submit", "payload": future_payload()}, headers={"X-CSRF-Token": auth["csrf_token"], "Origin": "https://attacker.example"})
    assert response.status_code == 403
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 7
        assert get_db().execute("SELECT COUNT(*) FROM event_audit WHERE outcome='denied'").fetchone()[0] == 2


def test_complete_submit_approve_checkout_return_flow(app):
    student, teacher, keeper = [app.test_client() for _ in range(3)]
    s, t, k = login(student), login(teacher, "teacher"), login(keeper, "keeper")
    submitted = event(student, s["csrf_token"], "reservation.submit", future_payload())
    assert submitted.status_code == 200
    rid = submitted.json["data"]["id"]
    assert submitted.json["data"]["status"] == "pending"
    assert event(keeper, k["csrf_token"], "loan.checkout", {"reservation_id": rid}).status_code == 409
    assert event(teacher, t["csrf_token"], "reservation.approve", {"id": rid, "note": "课程用途合规"}).json["data"]["status"] == "approved"
    checked = event(keeper, k["csrf_token"], "loan.checkout", {"reservation_id": rid, "condition_note": "附件齐全"})
    assert checked.status_code == 200 and checked.json["data"]["status"] == "borrowed"
    lid = checked.json["data"]["id"]
    assert event(keeper, k["csrf_token"], "loan.checkout", {"reservation_id": rid}).status_code == 409
    returned = event(keeper, k["csrf_token"], "loan.return", {"id": lid, "condition_note": "归还完好"})
    assert returned.status_code == 200 and returned.json["data"]["returned_at"]
    assert event(keeper, k["csrf_token"], "loan.return", {"id": lid, "condition_note": "重复"}).status_code == 409
    rows = student.get("/api/reservations").json["data"]
    assert next(row for row in rows if row["id"] == rid)["status"] == "returned"


def test_self_review_and_cross_owner_cancel_are_forbidden(app):
    multi = app.test_client()
    auth = login(multi, "multi")
    rid = event(multi, auth["csrf_token"], "reservation.submit", future_payload()).json["data"]["id"]
    assert event(multi, auth["csrf_token"], "reservation.approve", {"id": rid}).json["error"]["code"] == "SELF_REVIEW_FORBIDDEN"
    assert event(multi, auth["csrf_token"], "reservation.cancel", {"id": 1}).status_code == 403
    student = app.test_client()
    student_auth = login(student)
    assert event(student, student_auth["csrf_token"], "reservation.cancel", {"id": rid}).status_code == 403


def test_overlap_half_open_interval_and_cancel_frees_slot(client):
    auth = login(client)
    first = event(client, auth["csrf_token"], "reservation.submit", future_payload())
    assert first.status_code == 200
    assert event(client, auth["csrf_token"], "reservation.submit", future_payload()).status_code == 409
    assert event(client, auth["csrf_token"], "reservation.submit", future_payload(start_at="2030-02-01T11:00", end_at="2030-02-01T12:00")).status_code == 200
    assert event(client, auth["csrf_token"], "reservation.cancel", {"id": first.json["data"]["id"]}).status_code == 200
    assert event(client, auth["csrf_token"], "reservation.submit", future_payload()).status_code == 200


@pytest.mark.parametrize("overrides", [
    {"equipment_id": 5}, {"start_at": "2029-12-31T09:00"},
    {"end_at": "2030-02-01T09:00"}, {"start_at": "2030-02-30T09:00"},
    {"start_at": "2030-02-01T09:00+08:00"}, {"start_at": "2030-02-01T09:00:01"},
    {"purpose": ""}, {"equipment_id": True}, {"equipment_id": "1 OR 1=1"},
])
def test_invalid_reservation_never_mutates(app, client, overrides):
    auth = login(client)
    response = event(client, auth["csrf_token"], "reservation.submit", future_payload(**overrides))
    assert response.status_code in (400, 409)
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 7
        assert get_db().execute("SELECT outcome FROM event_audit ORDER BY id DESC LIMIT 1").fetchone()[0] == "invalid"


def test_physical_device_blocks_second_checkout_even_for_different_dates(app):
    student, teacher, keeper = [app.test_client() for _ in range(3)]
    s, t, k = login(student), login(teacher, "teacher"), login(keeper, "keeper")
    ids = []
    for day in (1, 2):
        payload = future_payload(start_at=f"2030-02-0{day}T09:00", end_at=f"2030-02-0{day}T11:00")
        rid = event(student, s["csrf_token"], "reservation.submit", payload).json["data"]["id"]
        assert event(teacher, t["csrf_token"], "reservation.approve", {"id": rid}).status_code == 200
        ids.append(rid)
    assert event(keeper, k["csrf_token"], "loan.checkout", {"reservation_id": ids[0]}).status_code == 200
    assert event(keeper, k["csrf_token"], "loan.checkout", {"reservation_id": ids[1]}).status_code == 409


@pytest.mark.parametrize("clock", ["2030-02-01T11:00:00", "2030-02-01T11:00:01"])
def test_checkout_rejects_half_open_end_and_expired_reservation(app, clock):
    student, teacher, keeper = [app.test_client() for _ in range(3)]
    s, t, k = login(student), login(teacher, "teacher"), login(keeper, "keeper")
    rid = event(student, s["csrf_token"], "reservation.submit", future_payload()).json["data"]["id"]
    assert event(teacher, t["csrf_token"], "reservation.approve", {"id": rid}).status_code == 200
    app.config["NOW"] = clock
    # 该用例把业务时钟推进一个月；重新登录以避免被会话过期先拦截。
    k = login(keeper, "keeper")
    assert event(keeper, k["csrf_token"], "loan.checkout", {"reservation_id": rid}).status_code == 409


def test_concurrent_overlapping_submissions_serialize(app):
    barrier = Barrier(2)
    clients = [app.test_client(), app.test_client()]
    identities = [login(c) for c in clients]

    def submit(index):
        barrier.wait(timeout=10)
        return event(clients[index], identities[index]["csrf_token"], "reservation.submit", future_payload()).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, (0, 1)))
    assert sorted(results) == [200, 409]
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM reservations WHERE equipment_id=6 AND start_at='2030-02-01T09:00'").fetchone()[0] == 1


def test_permission_revocation_affects_existing_cookie_session(app):
    student, admin = app.test_client(), app.test_client()
    s, a = login(student), login(admin, "admin")
    matrix = admin.get("/api/rbac").json["data"]
    original = matrix["role_permissions"]["1"]
    keys = [key for key in original if key != "reservation:create"]
    saved = event(admin, a["csrf_token"], "rbac.save_permissions", {"role_id": 1, "permissions": keys})
    assert saved.status_code == 200
    with app.app_context():
        assert get_db().execute("SELECT target_id FROM event_audit ORDER BY id DESC LIMIT 1").fetchone()[0] == "1"
    assert "reservation:create" not in student.get("/api/me").json["data"]["permissions"]
    assert event(student, s["csrf_token"], "reservation.submit", future_payload()).status_code == 403
    assert event(admin, a["csrf_token"], "rbac.save_permissions", {"role_id": 1, "permissions": original}).status_code == 200
    assert event(student, s["csrf_token"], "reservation.submit", future_payload()).status_code == 200


def test_page_permission_is_independent_of_business_permission(app):
    student, admin = app.test_client(), app.test_client()
    login(student)
    a = login(admin, "admin")
    original = admin.get("/api/rbac").json["data"]["role_permissions"]["1"]
    keys = [key for key in original if key != "page.equipment:view"]
    assert event(admin, a["csrf_token"], "rbac.save_permissions", {"role_id": 1, "permissions": keys}).status_code == 200
    assert "equipment:view" in student.get("/api/me").json["data"]["permissions"]
    assert student.get("/api/equipment").status_code == 403


def test_permission_matrix_rejects_undefined_pairs_atomically(client):
    a = login(client, "admin")
    before = client.get("/api/rbac").json["data"]["role_permissions"]["1"]
    response = event(client, a["csrf_token"], "rbac.save_permissions", {"role_id": 1, "permissions": ["equipment:approve"]})
    assert response.status_code == 400
    assert client.get("/api/rbac").json["data"]["role_permissions"]["1"] == before


def test_admin_lockout_guards_and_dynamic_role_assignment(app, client):
    a = login(client, "admin")
    assert event(client, a["csrf_token"], "rbac.save_permissions", {"role_id": 4, "permissions": []}).status_code == 409
    assert event(client, a["csrf_token"], "rbac.assign_roles", {"user_id": 4, "role_ids": [1]}).status_code == 409
    for ids in ([], [1, 1], [9999], [True]):
        assert event(client, a["csrf_token"], "rbac.assign_roles", {"user_id": 1, "role_ids": ids}).status_code == 400
    student = app.test_client()
    login(student)
    assert event(client, a["csrf_token"], "rbac.assign_roles", {"user_id": 1, "role_ids": [1, 2]}).status_code == 200
    assert "reservation:approve" in student.get("/api/me").json["data"]["permissions"]


def test_auditor_can_read_registry_but_cannot_mutate(client):
    auth = login(client, "auditor")
    registry = client.get("/api/events").json["data"]
    assert len(registry["bindings"]) == 15
    assert {b["source_id"] for b in registry["bindings"]} >= {"reservation.submit", "loan.return", "rbac.save_permissions"}
    assert event(client, auth["csrf_token"], "reservation.submit", future_payload()).status_code == 403


def test_csv_bom_formula_escape_and_export_authorization(app):
    student, admin = app.test_client(), app.test_client()
    s, _ = login(student), login(admin, "admin")
    formula = '=HYPERLINK("https://example.invalid","test")'
    assert event(student, s["csrf_token"], "reservation.submit", future_payload(purpose=formula)).status_code == 200
    assert student.get("/api/export/reservations").status_code == 403
    response = admin.get("/api/export/reservations")
    assert response.status_code == 200 and response.data.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(response.data.decode("utf-8-sig"))))
    assert any("'" + formula in row for row in rows)


def test_equipment_validation_and_maintenance_guard(client):
    k = login(client, "keeper")
    payload = {"code": "EQ-099", "name": "实验电源", "category": "电子测量", "location": "B205", "status": "available", "description": "课程新增设备"}
    created = event(client, k["csrf_token"], "equipment.save", payload)
    assert created.status_code == 200
    assert event(client, k["csrf_token"], "equipment.save", payload).status_code == 409
    payload.update(id=1, code="EQ-001", status="maintenance")
    assert event(client, k["csrf_token"], "equipment.save", payload).status_code == 409


def test_rejection_requires_note_and_audit_never_contains_secrets(app, client):
    t = login(client, "teacher")
    assert event(client, t["csrf_token"], "reservation.reject", {"id": 1, "note": ""}).status_code == 400
    assert event(client, t["csrf_token"], "reservation.reject", {"id": 1, "note": "请补充安全措施"}).status_code == 200
    assert event(client, t["csrf_token"], "reservation.approve", {"id": 1}).status_code == 409
    auditor = login(client, "auditor")
    audit_text = client.get("/api/audit").get_data(as_text=True)
    assert "Lab@2026!" not in audit_text
    assert t["csrf_token"] not in audit_text and auditor["csrf_token"] not in audit_text
    assert '"accepted"' in audit_text and '"invalid"' in audit_text
