# LabReserve API and implementation contract

Local coursework app, Flask + SQLite + plain HTML/CSS/JS. Python >=3.11. Run `python run.py` on 127.0.0.1:8783. Backend owner app/*.py + run.py + requirements.txt + tests/. Frontend owner app/static/* + app/templates/index.html. Root owns docs, evidence, scripts, report and README. Dates are ISO local Asia/Shanghai, naive minute precision, reject invalid/past/end<=start. Test clock injectable or generate future dates.

JSON success shape `{ok:true,data:...}`; error `{ok:false,error:{code,message}}`. Cookie session, CSRF token from login/me response, X-CSRF-Token on mutating requests, same-origin. Responses data objects below. No frontend framework or external CDN. Root GET renders index.html; assets `/static/`.

POST /api/login `{username,password}` -> `{user:{id,username,display_name,roles:[{id,code,name}]}, permissions:["equipment:view",...], csrf_token}`. GET /api/me same, 401 anonymous. POST /api/logout -> {}.
Seed demo accounts: student / teacher / keeper / admin / auditor / multi ; all password `Lab@2026!`. Student 学生 张同学; teacher 指导教师 李老师; keeper 设备管理员 王老师; admin 系统管理员; auditor 审计员; multi 兼任学生与教师 (student + teacher). Admin has explicit all permissions, never authorization bypass.

GET /api/dashboard -> `{equipment_count,pending_count,approved_count,borrowed_count,my_reservation_count,permission_count}` counts scoped to own student, full for review/checkout/audit.
GET /api/equipment -> array `{id,code,name,category,location,status,description}` status available/maintenance. Equipment physical quantity is one per record.
GET /api/reservations -> array `{id,equipment_id,equipment_name,equipment_code,user_id,applicant_name,start_at,end_at,purpose,status,reviewer_name,review_note,created_at}` status pending/approved/rejected/cancelled/borrowed/returned. Students own records only; review/checkout/audit roles all.
GET /api/loans -> array `{id,reservation_id,equipment_name,applicant_name,checkout_at,returned_at,status,condition_note}` scoped similarly.
GET /api/audit -> array last 200 `{id,actor_name,source_id,event_type,object_code,operation_code,target_id,outcome,detail,created_at}`. GET /api/events -> `{bindings:[{source_id,event_type,object_code,operation_code,handler}],recent:[audit rows]}` permission audit:view.
GET /api/rbac -> `{roles:[{id,code,name}],users:[{id,username,display_name,role_ids:[int]}],objects:[{id,code,name,kind}],operations:[{id,code,name}],permissions:[{object_code,operation_code}],role_permissions:{"1":["equipment:view",...]}}` permission rbac:view. Permission matrix renders supported pairs only.

POST /api/events `{source_id,payload:{...}}` -> updated record or `{message}`. Server fixed registry resolves source to object/operation/handler, never trusts caller operation/object. Unknown source 400. Auth 401, missing permission 403, invalid input 400, unavailable/bad state/duplicate/conflict 409. All binding actions below:
- equipment.save => equipment:update, payload `{id? ,code,name,category,location,status,description}` (admin/keeper)
- reservation.submit => reservation:create, `{equipment_id,start_at,end_at,purpose}`
- reservation.approve => reservation:approve, `{id,note?}` (teacher/admin; self review forbidden)
- reservation.reject => reservation:reject, `{id,note}` (teacher/admin; self review forbidden)
- reservation.cancel => reservation:cancel, `{id}` (own only unless explicit reservation:manage, pending/approved only)
- loan.checkout => loan:checkout, `{reservation_id,condition_note?}` (keeper/admin, approved only, current time must be strictly before end_at (now >= end_at is expired); not early-limited for demo)
- loan.return => loan:return, `{id,condition_note}` (keeper/admin, borrowed only)
- rbac.save_permissions => rbac:manage, `{role_id,permissions:["equipment:view",...]}` replaces supported permissions atomically. Guard removal of rbac:view/manage and page/menu.rbac:view from admin; explain admin protection.
- rbac.assign_roles => rbac:manage, `{user_id,role_ids:[int]}`; reject empty/unknown/duplicate ids, ensure at least one active admin remains.

GET /api/export/reservations -> UTF-8 BOM CSV (permission reservation:export), same data scope, CSV formula escaping.

Permission object codes: page.dashboard/page.equipment/page.reservations/page.loans/page.rbac/page.audit (kind page); menu.dashboard/menu.equipment/menu.reservations/menu.loans/menu.rbac/menu.audit (kind menu); equipment/reservation/loan/rbac/audit (kind business). All pages/menus use view. Business supported pairs equipment:view/update; reservation:view/create/approve/reject/cancel/manage/export; loan:view/checkout/return; rbac:view/manage; audit:view. Dashboard requires page.dashboard:view. List endpoint requires business view plus corresponding page view. Event checks business pair every dispatch; UI page/menu/button presentation independently from stored permissions. Admin all explicit; student dashboard/equipment/reservations/loans page+menu view plus equipment:view,reservation:view/create/cancel,loan:view; teacher same + approve/reject; keeper same base + equipment:update,loan:checkout/return; auditor all reading incl audit but no mutation/export optional; multi union. Audit/event registry view uses audit:view + page.audit:view.

SQLite core exactly users,roles,user_roles,operations,control_objects,permissions,role_permissions (both mappings with composite PK). sessions optional technical + equipment,reservations,loans,event_audit. SQL FK on every connection. Transactions BEGIN IMMEDIATE for conflicting mutations; reservations overlap pending/approved/borrowed, half-open intervals. Physical active loan blocks new checkout regardless dates. Reservation state transitions and owner/self-review restrictions belong business service, separate from RBAC. Password hashes, random sessions hashed in DB, password never in audit. Login throttling simple optional. No destructive reset without --reset flag. Every mutating event writes accepted or denied/invalid audit, validation failures must not partially mutate business. Denied checks logged without secrets. Static UI must escape text and avoid innerHTML from user data.
