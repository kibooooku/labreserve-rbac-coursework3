"""Independent behavioral review; every test owns a temporary SQLite database."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
import shutil

import pytest

from app import create_app
from app.db import get_db
from app.errors import DomainError


CLOCK = datetime(2026, 10, 22, 10, 0)
PASSWORD = "Lab@2026!"


@pytest.fixture(scope="session")
def review_seeded_database(tmp_path_factory):
    path = tmp_path_factory.mktemp("independent_seed") / "seed.sqlite3"
    create_app({"TESTING": True, "DATABASE": str(path), "NOW": CLOCK})
    return path


@pytest.fixture
def app(tmp_path, review_seeded_database):
    path = tmp_path / "review.sqlite3"
    shutil.copyfile(review_seeded_database, path)
    return create_app({"TESTING": True, "DATABASE": str(path), "NOW": CLOCK})


def login(app, username):
    client = app.test_client()
    response = client.post("/api/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    return client, response.get_json()["data"]


def event(account, source, payload, **envelope):
    client, identity = account
    return client.post("/api/events", json={"source_id": source, "payload": payload, **envelope},
                       headers={"X-CSRF-Token": identity["csrf_token"]})


def rows(app, sql, parameters=()):
    with app.app_context():
        return [dict(r) for r in get_db().execute(sql, parameters).fetchall()]


def execute(app, sql, parameters=()):
    with app.app_context():
        get_db().execute(sql, parameters)


def role_id(app, code):
    return rows(app, "SELECT id FROM roles WHERE code=?", (code,))[0]["id"]


def user_id(app, username):
    return rows(app, "SELECT id FROM users WHERE username=?", (username,))[0]["id"]


def permissions(admin, rid):
    response = admin[0].get("/api/rbac")
    assert response.status_code == 200
    return response.get_json()["data"]["role_permissions"][str(rid)]


def reservation(account, equipment_id=1, days=10, **updates):
    start = CLOCK + timedelta(days=days)
    payload = {"equipment_id": equipment_id, "start_at": start.isoformat(timespec="minutes"),
               "end_at": (start + timedelta(hours=1)).isoformat(timespec="minutes"),
               "purpose": "独立审查临时测试"}
    payload.update(updates)
    response = event(account, "reservation.submit", payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def approved(account, teacher, equipment_id=1, days=10):
    record = reservation(account, equipment_id, days)
    response = event(teacher, "reservation.approve", {"id": record["id"]})
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]


def race(accounts, source, payloads):
    barrier = Barrier(len(accounts))

    def send(index):
        barrier.wait(timeout=10)
        return event(accounts[index], source, payloads[index])

    with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
        return list(executor.map(send, range(len(accounts))))


def test_existing_session_loses_revoked_permission_immediately(app):
    student, teacher, admin = (login(app, name) for name in ("student", "teacher", "admin"))
    record = reservation(student)
    rid = role_id(app, "teacher")
    keys = permissions(admin, rid)
    assert "reservation:approve" in teacher[1]["permissions"]
    response = event(admin, "rbac.save_permissions", {"role_id": rid, "permissions": [key for key in keys if key != "reservation:approve"]})
    assert response.status_code == 200
    denied = event(teacher, "reservation.approve", {"id": record["id"]})
    assert denied.status_code == 403
    assert "reservation:approve" not in teacher[0].get("/api/me").get_json()["data"]["permissions"]
    assert rows(app, "SELECT status FROM reservations WHERE id=?", (record["id"],))[0]["status"] == "pending"
    audit = rows(app, "SELECT outcome,object_code,operation_code FROM event_audit ORDER BY id DESC LIMIT 1")[0]
    assert audit == {"outcome": "denied", "object_code": "reservation", "operation_code": "approve"}


def test_saved_permissions_survive_application_recreation_without_reseeding(app):
    student, admin = login(app, "student"), login(app, "admin")
    rid = role_id(app, "student")
    keys = [key for key in permissions(admin, rid) if key != "reservation:create"]
    assert event(admin, "rbac.save_permissions", {"role_id": rid, "permissions": keys}).status_code == 200
    raw_cookie = student[0].get_cookie("labreserve_session").value
    original_count = rows(app, "SELECT COUNT(*) AS n FROM reservations")[0]["n"]
    rebuilt = create_app({"TESTING": True, "DATABASE": app.config["DATABASE"], "NOW": CLOCK})
    client = rebuilt.test_client()
    client.set_cookie("labreserve_session", raw_cookie)
    identity = client.get("/api/me")
    assert identity.status_code == 200
    assert "reservation:create" not in identity.get_json()["data"]["permissions"]
    start = CLOCK + timedelta(days=10)
    payload = {"equipment_id": 1, "start_at": start.isoformat(timespec="minutes"),
               "end_at": (start + timedelta(hours=1)).isoformat(timespec="minutes"), "purpose": "应用重建后的持久化检查"}
    assert event((client, identity.get_json()["data"]), "reservation.submit", payload).status_code == 403
    assert rows(rebuilt, "SELECT COUNT(*) AS n FROM reservations")[0]["n"] == original_count


def test_existing_session_tracks_role_assignment_and_removal(app):
    student, multi, admin = (login(app, name) for name in ("student", "multi", "admin"))
    student_role, teacher_role = role_id(app, "student"), role_id(app, "teacher")
    uid = student[1]["user"]["id"]
    first = reservation(multi, days=10)
    assert event(student, "reservation.approve", {"id": first["id"]}).status_code == 403
    assert event(admin, "rbac.assign_roles", {"user_id": uid, "role_ids": [student_role, teacher_role]}).status_code == 200
    identity = student[0].get("/api/me").get_json()["data"]
    assert {r["code"] for r in identity["user"]["roles"]} == {"student", "teacher"}
    assert event(student, "reservation.approve", {"id": first["id"]}).status_code == 200
    second = reservation(multi, days=11)
    assert event(admin, "rbac.assign_roles", {"user_id": uid, "role_ids": [student_role]}).status_code == 200
    assert event(student, "reservation.approve", {"id": second["id"]}).status_code == 403


@pytest.mark.parametrize("username", ["teacher", "multi"])
def test_self_review_forbidden_even_with_review_permission(app, username):
    account = login(app, username)
    record = reservation(account)
    for source, extra in [("reservation.approve", {}), ("reservation.reject", {"note": "拒绝本人申请"})]:
        response = event(account, source, {"id": record["id"], **extra})
        assert response.status_code == 403
        assert response.get_json()["error"]["code"] == "SELF_REVIEW_FORBIDDEN"
    assert rows(app, "SELECT status FROM reservations WHERE id=?", (record["id"],))[0]["status"] == "pending"


def test_ownership_is_enforced_per_action_not_only_in_list(app):
    student, multi, admin = (login(app, name) for name in ("student", "multi", "admin"))
    own, other = reservation(student), reservation(multi, days=11)
    assert all(r["user_id"] == student[1]["user"]["id"] for r in student[0].get("/api/reservations").get_json()["data"])
    denial = event(student, "reservation.cancel", {"id": other["id"], "user_id": student[1]["user"]["id"]})
    assert denial.status_code == 403
    assert denial.get_json()["error"]["code"] == "OWNERSHIP_FORBIDDEN"
    assert event(student, "reservation.cancel", {"id": own["id"]}).status_code == 200
    assert event(admin, "reservation.cancel", {"id": other["id"]}).status_code == 200


def test_fixed_binding_ignores_forged_authorization_fields(app):
    student = login(app, "student")
    response = event(student, "equipment.save", {"object_code": "reservation", "operation_code": "create", "handler": "submit_reservation"},
                     object_code="reservation", operation_code="create", handler="submit_reservation")
    assert response.status_code == 403
    audit = rows(app, "SELECT object_code,operation_code,outcome FROM event_audit ORDER BY id DESC LIMIT 1")[0]
    assert audit == {"object_code": "equipment", "operation_code": "update", "outcome": "denied"}
    assert event(student, "business.submit_reservation", {}).status_code == 400
    record = reservation(student, user_id=user_id(app, "admin"), status="approved", reviewer_id=user_id(app, "teacher"))
    assert record["user_id"] == student[1]["user"]["id"]
    assert record["status"] == "pending" and record["reviewer_name"] is None


def test_page_menu_and_business_permissions_are_independent(app):
    teacher, admin = login(app, "teacher"), login(app, "admin")
    rid = role_id(app, "teacher")
    keys = permissions(admin, rid)
    without_menu = [key for key in keys if key != "menu.reservations:view"]
    assert event(admin, "rbac.save_permissions", {"role_id": rid, "permissions": without_menu}).status_code == 200
    assert teacher[0].get("/api/reservations").status_code == 200
    without_page = [key for key in without_menu if key != "page.reservations:view"]
    assert event(admin, "rbac.save_permissions", {"role_id": rid, "permissions": without_page}).status_code == 200
    assert teacher[0].get("/api/reservations").status_code == 403
    assert "reservation:approve" in teacher[0].get("/api/me").get_json()["data"]["permissions"]


def test_mid_transaction_domain_failure_rolls_back_and_keeps_audit(app, monkeypatch):
    from app import business
    keeper = login(app, "keeper")
    original = rows(app, "SELECT description FROM equipment WHERE id=1")[0]["description"]

    def partial_then_fail(actor, payload):
        get_db().execute("UPDATE equipment SET description='must rollback' WHERE id=1")
        raise DomainError("独立审查模拟提交前失败", 409, "REVIEW_FAULT")

    monkeypatch.setattr(business, "save_equipment", partial_then_fail)
    response = event(keeper, "equipment.save", {"id": 1})
    assert response.status_code == 409
    assert rows(app, "SELECT description FROM equipment WHERE id=1")[0]["description"] == original
    audit = rows(app, "SELECT outcome,detail FROM event_audit ORDER BY id DESC LIMIT 1")[0]
    assert audit["outcome"] == "invalid" and "模拟提交前失败" in audit["detail"]


def test_success_audit_failure_cannot_commit_business_write(app, monkeypatch):
    from app import business, events
    keeper = login(app, "keeper")
    original = rows(app, "SELECT description FROM equipment WHERE id=1")[0]["description"]
    real_audit = events.write_audit

    def update(actor, payload):
        get_db().execute("UPDATE equipment SET description='must rollback' WHERE id=1")
        return {"id": 1}

    def failed_success_audit(source, binding, actor, outcome, detail, target_id=None):
        if outcome == "accepted":
            raise RuntimeError("injected audit write failure")
        return real_audit(source, binding, actor, outcome, detail, target_id)

    monkeypatch.setattr(business, "save_equipment", update)
    monkeypatch.setattr(events, "write_audit", failed_success_audit)
    response = event(keeper, "equipment.save", {"id": 1})
    assert response.status_code == 500
    assert response.get_json()["error"]["code"] == "INTERNAL_ERROR"
    assert "injected audit" not in response.get_data(as_text=True)
    assert rows(app, "SELECT description FROM equipment WHERE id=1")[0]["description"] == original
    assert rows(app, "SELECT outcome FROM event_audit ORDER BY id DESC LIMIT 1")[0]["outcome"] == "invalid"


def test_concurrent_overlapping_reservations_have_one_winner(app):
    student, multi = login(app, "student"), login(app, "multi")
    start = CLOCK + timedelta(days=12)
    payload = {"equipment_id": 1, "start_at": start.isoformat(timespec="minutes"),
               "end_at": (start + timedelta(hours=1)).isoformat(timespec="minutes"), "purpose": "并发占用检查"}
    responses = race([student, multi], "reservation.submit", [payload, payload])
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(rows(app, "SELECT id FROM reservations WHERE purpose='并发占用检查'")) == 1


def test_concurrent_nonoverlapping_checkouts_still_protect_one_physical_device(app):
    student, teacher, keeper, admin = (login(app, name) for name in ("student", "teacher", "keeper", "admin"))
    first, second = approved(student, teacher, days=10), approved(student, teacher, days=11)
    responses = race([keeper, admin], "loan.checkout", [{"reservation_id": first["id"]}, {"reservation_id": second["id"]}])
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(rows(app, "SELECT l.id FROM loans l JOIN reservations r ON r.id=l.reservation_id WHERE r.equipment_id=1 AND l.returned_at IS NULL")) == 1
    assert len(rows(app, "SELECT id FROM reservations WHERE id IN (?,?) AND status='approved'", (first["id"], second["id"]))) == 2
    displayed = student[0].get("/api/reservations").get_json()["data"]
    assert sum(r["status"] == "borrowed" for r in displayed if r["id"] in (first["id"], second["id"])) == 1


def test_concurrent_returns_are_not_double_applied(app):
    student, teacher, keeper, admin = (login(app, name) for name in ("student", "teacher", "keeper", "admin"))
    record = approved(student, teacher)
    checkout = event(keeper, "loan.checkout", {"reservation_id": record["id"]})
    assert checkout.status_code == 200
    lid = checkout.get_json()["data"]["id"]
    responses = race([keeper, admin], "loan.return", [{"id": lid, "condition_note": "并发归还甲"}, {"id": lid, "condition_note": "并发归还乙"}])
    assert sorted(r.status_code for r in responses) == [200, 409]
    returned = rows(app, "SELECT returned_at,return_condition,checkout_condition,returned_by FROM loans WHERE id=?", (lid,))[0]
    assert returned["returned_at"] and returned["returned_by"] in (keeper[1]["user"]["id"], admin[1]["user"]["id"])
    assert returned["return_condition"] in ("并发归还甲", "并发归还乙")
    assert rows(app, "SELECT status FROM reservations WHERE id=?", (record["id"],))[0]["status"] == "approved"
    assert next(r for r in student[0].get("/api/reservations").get_json()["data"] if r["id"] == record["id"])["status"] == "returned"


def test_maintenance_blocks_submission_and_preserves_existing_reservations(app):
    student, keeper = login(app, "student"), login(app, "keeper")
    start = CLOCK + timedelta(days=10)
    response = event(student, "reservation.submit", {"equipment_id": 5, "start_at": start.isoformat(timespec="minutes"), "end_at": (start + timedelta(hours=1)).isoformat(timespec="minutes"), "purpose": "维护设备检查"})
    assert response.status_code == 409
    reservation(student)
    equipment = keeper[0].get("/api/equipment").get_json()["data"][0]
    equipment["status"] = "maintenance"
    assert event(keeper, "equipment.save", equipment).status_code == 409
    assert rows(app, "SELECT lifecycle_status FROM equipment WHERE id=1")[0]["lifecycle_status"] == "active"
    assert not rows(app, "SELECT id FROM equipment_maintenance WHERE equipment_id=1 AND end_at IS NULL")
    assert keeper[0].get("/api/equipment").get_json()["data"][0]["status"] == "available"


def test_checkout_defensively_checks_maintenance_after_approval(app):
    student, teacher, keeper = (login(app, name) for name in ("student", "teacher", "keeper"))
    record = approved(student, teacher)
    # Direct setup simulates an external maintenance change; public UI forbids it while reserved.
    execute(app, "INSERT INTO equipment_maintenance(equipment_id,started_by,start_at,reason) VALUES (1,3,?,'独立审查模拟外部维护')", (CLOCK.isoformat(timespec="seconds"),))
    assert event(keeper, "loan.checkout", {"reservation_id": record["id"]}).status_code == 409
    assert rows(app, "SELECT status FROM reservations WHERE id=?", (record["id"],))[0]["status"] == "approved"


@pytest.mark.parametrize("start,end", [
    ("2026-10-21T10:00", "2026-10-21T11:00"),
    ("2026-11-01T10:00", "2026-11-01T10:00"),
    ("2026-11-01T10:00", "2026-11-01T09:59"),
    ("2026-11-01T10:00:01", "2026-11-01T11:00"),
    ("2026-11-01T10:00+08:00", "2026-11-01T11:00+08:00"),
    ("2026-02-30T10:00", "2026-03-01T11:00"),
])
def test_datetime_rejection_is_atomic_and_audited(app, start, end):
    student = login(app, "student")
    before = len(rows(app, "SELECT id FROM reservations"))
    response = event(student, "reservation.submit", {"equipment_id": 1, "start_at": start, "end_at": end, "purpose": "日期边界"})
    assert response.status_code == 400
    assert len(rows(app, "SELECT id FROM reservations")) == before
    assert rows(app, "SELECT outcome FROM event_audit ORDER BY id DESC LIMIT 1")[0]["outcome"] == "invalid"


def test_half_open_adjacent_reservations_do_not_conflict(app):
    student = login(app, "student")
    first = reservation(student)
    second = reservation(student, start_at=first["end_at"], end_at=(CLOCK + timedelta(days=10, hours=2)).isoformat(timespec="minutes"))
    assert first["end_at"] == second["start_at"]


@pytest.mark.parametrize("late_seconds,expected", [(-1, 200), (0, 409), (1, 409)])
def test_checkout_end_time_boundary_matches_contract(app, late_seconds, expected):
    student, teacher, keeper = (login(app, name) for name in ("student", "teacher", "keeper"))
    record = approved(student, teacher)
    app.config["NOW"] = datetime.fromisoformat(record["end_at"]) + timedelta(seconds=late_seconds)
    keeper = login(app, "keeper")  # Advancing ten days also expires the previous session.
    assert event(keeper, "loan.checkout", {"reservation_id": record["id"]}).status_code == expected


def test_csrf_origin_logout_and_old_session_reuse(app):
    student = login(app, "student")
    client, identity = student
    old_cookie = client.get_cookie("labreserve_session").value
    envelope = {"source_id": "reservation.cancel", "payload": {"id": 1}}
    assert client.post("/api/events", json=envelope).status_code == 403
    assert client.post("/api/events", json=envelope, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/events", json=envelope, headers={"X-CSRF-Token": identity["csrf_token"], "Origin": "https://foreign.example"}).status_code == 403
    assert rows(app, "SELECT status FROM reservations WHERE id=1")[0]["status"] == "pending"
    assert client.post("/api/logout", headers={"X-CSRF-Token": identity["csrf_token"]}).status_code == 200
    client.set_cookie("labreserve_session", old_cookie)
    assert client.get("/api/me").status_code == 401
    assert event(student, "reservation.cancel", {"id": 1}).status_code == 401


def test_login_rotates_session_and_expiration_boundary(app):
    student = login(app, "student")
    client = student[0]
    first_cookie = client.get_cookie("labreserve_session").value
    response = client.post("/api/login", json={"username": "student", "password": PASSWORD})
    assert response.status_code == 200
    new_cookie = client.get_cookie("labreserve_session").value
    assert first_cookie != new_cookie
    stale = app.test_client()
    stale.set_cookie("labreserve_session", first_cookie)
    assert stale.get("/api/me").status_code == 401
    app.config["NOW"] = CLOCK + timedelta(hours=12)
    assert client.get("/api/me").status_code == 401


def test_malformed_origin_is_rejected_as_csrf_instead_of_internal_error(app):
    student = login(app, "student")
    response = student[0].post("/api/events", json={"source_id": "reservation.cancel", "payload": {"id": 1}},
                               headers={"X-CSRF-Token": student[1]["csrf_token"], "Origin": "http://["})
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "CSRF_FAILED"
    assert rows(app, "SELECT status FROM reservations WHERE id=1")[0]["status"] == "pending"
    assert rows(app, "SELECT outcome FROM event_audit ORDER BY id DESC LIMIT 1")[0]["outcome"] == "denied"


def test_invalid_permission_replacements_leave_original_matrix_intact(app):
    admin = login(app, "admin")
    rid = role_id(app, "teacher")
    before = permissions(admin, rid)
    for keys in [before + ["equipment:approve"], before + [before[0]], [None], "reservation:view"]:
        assert event(admin, "rbac.save_permissions", {"role_id": rid, "permissions": keys}).status_code == 400
        assert permissions(admin, rid) == before


def test_each_admin_management_permission_is_protected(app):
    admin = login(app, "admin")
    rid = role_id(app, "admin")
    before = permissions(admin, rid)
    for protected in ["rbac:view", "rbac:manage", "page.rbac:view", "menu.rbac:view"]:
        response = event(admin, "rbac.save_permissions", {"role_id": rid, "permissions": [p for p in before if p != protected]})
        assert response.status_code == 409
        assert response.get_json()["error"]["code"] == "ADMIN_PROTECTED"
        assert permissions(admin, rid) == before


def test_invalid_role_assignments_and_last_admin_protection(app):
    admin, multi = login(app, "admin"), login(app, "multi")
    admin_role, student_role = role_id(app, "admin"), role_id(app, "student")
    uid = admin[1]["user"]["id"]
    for ids in [[], [student_role, student_role], [99999], [True], "student"]:
        assert event(admin, "rbac.assign_roles", {"user_id": uid, "role_ids": ids}).status_code == 400
    assert event(admin, "rbac.assign_roles", {"user_id": uid, "role_ids": [student_role]}).status_code == 409
    assert event(admin, "rbac.assign_roles", {"user_id": multi[1]["user"]["id"], "role_ids": [student_role, admin_role]}).status_code == 200
    assert event(admin, "rbac.assign_roles", {"user_id": uid, "role_ids": [student_role]}).status_code == 200
    assert admin[0].get("/api/rbac").status_code == 403
    assert multi[0].get("/api/rbac").status_code == 200
    assert event(admin, "rbac.assign_roles", {"user_id": uid, "role_ids": [admin_role]}).status_code == 403
