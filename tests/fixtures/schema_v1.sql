-- 原12表数据库的独立回归夹具，不依赖新的建库实现。
PRAGMA foreign_keys=ON;
CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT NOT NULL UNIQUE,display_name TEXT NOT NULL,password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE roles(id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL);
CREATE TABLE user_roles(user_id INTEGER NOT NULL REFERENCES users(id),role_id INTEGER NOT NULL REFERENCES roles(id),PRIMARY KEY(user_id,role_id));
CREATE TABLE operations(id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL);
CREATE TABLE control_objects(id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,kind TEXT NOT NULL);
CREATE TABLE permissions(operation_id INTEGER NOT NULL REFERENCES operations(id),object_id INTEGER NOT NULL REFERENCES control_objects(id),PRIMARY KEY(operation_id,object_id));
CREATE TABLE role_permissions(role_id INTEGER NOT NULL REFERENCES roles(id),operation_id INTEGER NOT NULL,object_id INTEGER NOT NULL,PRIMARY KEY(role_id,operation_id,object_id),FOREIGN KEY(operation_id,object_id) REFERENCES permissions(operation_id,object_id));
CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),csrf_token TEXT NOT NULL,expires_at TEXT NOT NULL);
CREATE TABLE equipment(id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,category TEXT NOT NULL,location TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('available','maintenance')),description TEXT NOT NULL DEFAULT '');
CREATE TABLE reservations(id INTEGER PRIMARY KEY,equipment_id INTEGER NOT NULL REFERENCES equipment(id),user_id INTEGER NOT NULL REFERENCES users(id),start_at TEXT NOT NULL,end_at TEXT NOT NULL,purpose TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled','borrowed','returned')),reviewer_id INTEGER REFERENCES users(id),review_note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,CHECK(end_at>start_at));
CREATE TABLE loans(id INTEGER PRIMARY KEY,reservation_id INTEGER NOT NULL UNIQUE REFERENCES reservations(id),checkout_at TEXT NOT NULL,returned_at TEXT,status TEXT NOT NULL CHECK(status IN ('borrowed','returned')),condition_note TEXT NOT NULL DEFAULT '');
CREATE TABLE event_audit(id INTEGER PRIMARY KEY,actor_id INTEGER REFERENCES users(id),actor_name TEXT NOT NULL,source_id TEXT NOT NULL,event_type TEXT NOT NULL,object_code TEXT NOT NULL,operation_code TEXT NOT NULL,target_id TEXT,outcome TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
-- TEST DATA
INSERT INTO users VALUES(1,'legacy-student','保留原学生','original-password-hash',1),(2,'legacy-teacher','保留原教师','original-teacher-hash',1);
INSERT INTO roles VALUES(1,'student','旧学生角色');
INSERT INTO user_roles VALUES(1,1);
INSERT INTO operations VALUES(1,'view','查看');
INSERT INTO control_objects VALUES(1,'equipment','设备','business');
INSERT INTO permissions VALUES(1,1);
INSERT INTO role_permissions VALUES(1,1,1);
INSERT INTO sessions VALUES('preserve-session-hash',1,'preserve-csrf','2099-01-01T00:00:00');
INSERT INTO equipment VALUES(11,'LEG-011','保留设备','原分类','原实验室','available','原设备说明'),(12,'LEG-012','原维护设备','原分类','原实验室','maintenance','待修理');
INSERT INTO reservations VALUES
 (21,11,1,'2030-02-01T09:00','2030-02-01T10:00','原待审申请','pending',NULL,'','2029-12-01T09:00:00'),
 (22,11,1,'2030-02-02T09:00','2030-02-02T10:00','原已批准申请','approved',2,'保留审批意见','2029-12-01T09:00:00'),
 (23,11,1,'2029-01-01T09:00','2029-01-01T10:00','原已归还申请','returned',2,'同意','2028-12-01T09:00:00'),
 (24,11,1,'2030-01-01T07:00','2030-01-01T12:00','原借用中申请','borrowed',2,'同意','2029-12-01T09:00:00');
INSERT INTO loans VALUES(31,23,'2029-01-01T09:00:00','2029-01-01T10:00:00','returned','历史归还检查'),(32,24,'2030-01-01T07:00:00',NULL,'borrowed','历史借出检查');
INSERT INTO event_audit VALUES(41,1,'原学生','reservation.submit','submit','reservation','create','21','accepted','原始审计证据','2029-12-01T09:00:00');
