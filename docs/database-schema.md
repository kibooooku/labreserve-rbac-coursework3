# 数据库字段与关系

数据库版本为 2，共 16 张业务与授权表。字段、主键、外键和索引与 `app/db.py` 的实际 SCHEMA 一致；API 联查投影字段另见 `api-contract.md`。

七张授权表为 users、roles、user_roles、operations、control_objects、permissions、role_permissions；技术表为 sessions、event_audit；七张业务表为 laboratories、equipment_categories、equipment、reservations、reservation_reviews、loans、equipment_maintenance。

## 1. 用户（users）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| username | TEXT | NOT NULL | — |
| display_name | TEXT | NOT NULL | — |
| password_hash | TEXT | NOT NULL | — |
| active | INTEGER | NOT NULL | 1 |

唯一约束：`(username)`。

## 2. 角色（roles）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| code | TEXT | NOT NULL | — |
| name | TEXT | NOT NULL | — |

唯一约束：`(code)`。

## 3. 用户角色分配（user_roles）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| user_id | INTEGER | PK1；NOT NULL；FK | — |
| role_id | INTEGER | PK2；NOT NULL；FK | — |

外键关系：

- `(role_id) → roles(id)`；删除策略 CASCADE。
- `(user_id) → users(id)`；删除策略 CASCADE。

唯一约束：`(user_id,role_id)`。

## 4. 操作（operations）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| code | TEXT | NOT NULL | — |
| name | TEXT | NOT NULL | — |

唯一约束：`(code)`。

## 5. 控制对象（control_objects）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| code | TEXT | NOT NULL | — |
| name | TEXT | NOT NULL | — |
| kind | TEXT | NOT NULL | — |

唯一约束：`(code)`。

实际建表约束：

```sql
CREATE TABLE control_objects (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('page','menu','business'))
)
```

## 6. 许可（permissions）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| operation_id | INTEGER | PK1；NOT NULL；FK | — |
| object_id | INTEGER | PK2；NOT NULL；FK | — |

外键关系：

- `(object_id) → control_objects(id)`；删除策略 NO ACTION。
- `(operation_id) → operations(id)`；删除策略 NO ACTION。

唯一约束：`(operation_id,object_id)`。

## 7. 角色许可（role_permissions）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| role_id | INTEGER | PK1；NOT NULL；FK | — |
| operation_id | INTEGER | PK2；NOT NULL；FK | — |
| object_id | INTEGER | PK3；NOT NULL；FK | — |

外键关系：

- `(operation_id,object_id) → permissions(operation_id,object_id)`；删除策略 NO ACTION。
- `(role_id) → roles(id)`；删除策略 CASCADE。

唯一约束：`(role_id,operation_id,object_id)`。

## 8. 登录会话（sessions）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| token_hash | TEXT | PK1 | — |
| user_id | INTEGER | NOT NULL；FK | — |
| csrf_token | TEXT | NOT NULL | — |
| expires_at | TEXT | NOT NULL | — |

外键关系：

- `(user_id) → users(id)`；删除策略 CASCADE。

唯一约束：`(token_hash)`。

## 9. 实验室（laboratories）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| code | TEXT | NOT NULL | — |
| name | TEXT | NOT NULL | — |
| location | TEXT | NOT NULL | — |
| manager_id | INTEGER | FK | — |
| active | INTEGER | NOT NULL | 1 |
| description | TEXT | NOT NULL | '' |

外键关系：

- `(manager_id) → users(id)`；删除策略 NO ACTION。

唯一约束：`(code)`。

## 10. 设备分类（equipment_categories）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| code | TEXT | NOT NULL | — |
| name | TEXT | NOT NULL | — |
| active | INTEGER | NOT NULL | 1 |
| description | TEXT | NOT NULL | '' |

唯一约束：`(name)`。

唯一约束：`(code)`。

## 11. 设备实物（equipment）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| code | TEXT | NOT NULL | — |
| name | TEXT | NOT NULL | — |
| model | TEXT | NOT NULL | '' |
| category_id | INTEGER | NOT NULL；FK | — |
| laboratory_id | INTEGER | NOT NULL；FK | — |
| location | TEXT | NOT NULL | — |
| lifecycle_status | TEXT | NOT NULL | 'active' |
| description | TEXT | NOT NULL | '' |
| created_by | INTEGER | FK | — |
| created_at | TEXT | — | — |
| updated_at | TEXT | — | — |

外键关系：

- `(created_by) → users(id)`；删除策略 NO ACTION。
- `(laboratory_id) → laboratories(id)`；删除策略 NO ACTION。
- `(category_id) → equipment_categories(id)`；删除策略 NO ACTION。

唯一约束：`(code)`。

实际建表约束：

```sql
CREATE TABLE equipment (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 model TEXT NOT NULL DEFAULT '', category_id INTEGER NOT NULL REFERENCES equipment_categories(id),
 laboratory_id INTEGER NOT NULL REFERENCES laboratories(id), location TEXT NOT NULL,
 lifecycle_status TEXT NOT NULL DEFAULT 'active' CHECK(lifecycle_status IN ('active','disabled','retired')),
 description TEXT NOT NULL DEFAULT '', created_by INTEGER REFERENCES users(id), created_at TEXT, updated_at TEXT
)
```

## 12. 预约申请（reservations）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| equipment_id | INTEGER | NOT NULL；FK | — |
| user_id | INTEGER | NOT NULL；FK | — |
| start_at | TEXT | NOT NULL | — |
| end_at | TEXT | NOT NULL | — |
| purpose | TEXT | NOT NULL | — |
| status | TEXT | NOT NULL | — |
| created_at | TEXT | NOT NULL | — |
| updated_at | TEXT | — | — |
| cancelled_at | TEXT | — | — |
| cancelled_by | INTEGER | FK | — |

外键关系：

- `(cancelled_by) → users(id)`；删除策略 NO ACTION。
- `(user_id) → users(id)`；删除策略 NO ACTION。
- `(equipment_id) → equipment(id)`；删除策略 NO ACTION。

实际建表约束：

```sql
CREATE TABLE reservations (
 id INTEGER PRIMARY KEY, equipment_id INTEGER NOT NULL REFERENCES equipment(id),
 user_id INTEGER NOT NULL REFERENCES users(id), start_at TEXT NOT NULL, end_at TEXT NOT NULL,
 purpose TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','cancelled')),
 created_at TEXT NOT NULL, updated_at TEXT, cancelled_at TEXT, cancelled_by INTEGER REFERENCES users(id),
 CHECK(end_at > start_at), CHECK((status='cancelled') OR (cancelled_at IS NULL AND cancelled_by IS NULL))
)
```

## 13. 审批记录（reservation_reviews）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| reservation_id | INTEGER | NOT NULL；FK | — |
| reviewer_id | INTEGER | FK | — |
| decision | TEXT | NOT NULL | — |
| note | TEXT | NOT NULL | '' |
| reviewed_at | TEXT | — | — |

外键关系：

- `(reviewer_id) → users(id)`；删除策略 NO ACTION。
- `(reservation_id) → reservations(id)`；删除策略 NO ACTION。

唯一约束：`(reservation_id)`。

## 14. 借还记录（loans）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| reservation_id | INTEGER | NOT NULL；FK | — |
| checkout_by | INTEGER | FK | — |
| checkout_at | TEXT | NOT NULL | — |
| checkout_condition | TEXT | NOT NULL | '' |
| returned_by | INTEGER | FK | — |
| returned_at | TEXT | — | — |
| return_condition | TEXT | — | — |
| acceptance_result | TEXT | — | — |

外键关系：

- `(returned_by) → users(id)`；删除策略 NO ACTION。
- `(checkout_by) → users(id)`；删除策略 NO ACTION。
- `(reservation_id) → reservations(id)`；删除策略 NO ACTION。

唯一约束：`(reservation_id)`。

实际建表约束：

```sql
CREATE TABLE loans (
 id INTEGER PRIMARY KEY, reservation_id INTEGER NOT NULL UNIQUE REFERENCES reservations(id),
 checkout_by INTEGER REFERENCES users(id), checkout_at TEXT NOT NULL, checkout_condition TEXT NOT NULL DEFAULT '',
 returned_by INTEGER REFERENCES users(id), returned_at TEXT, return_condition TEXT,
 acceptance_result TEXT CHECK(acceptance_result IN ('passed','damaged','unknown')),
 CHECK(returned_at IS NULL OR returned_at >= checkout_at),
 CHECK((returned_at IS NULL AND returned_by IS NULL AND return_condition IS NULL AND acceptance_result IS NULL)
    OR (returned_at IS NOT NULL AND return_condition IS NOT NULL AND acceptance_result IS NOT NULL))
)
```

## 15. 设备维护（equipment_maintenance）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| equipment_id | INTEGER | NOT NULL；FK | — |
| loan_id | INTEGER | FK | — |
| started_by | INTEGER | FK | — |
| start_at | TEXT | NOT NULL | — |
| reason | TEXT | NOT NULL | — |
| ended_by | INTEGER | FK | — |
| end_at | TEXT | — | — |
| result | TEXT | — | — |

外键关系：

- `(ended_by) → users(id)`；删除策略 NO ACTION。
- `(started_by) → users(id)`；删除策略 NO ACTION。
- `(loan_id) → loans(id)`；删除策略 NO ACTION。
- `(equipment_id) → equipment(id)`；删除策略 NO ACTION。

唯一约束（部分索引）：`(equipment_id)`。

唯一约束：`(loan_id)`。

实际建表约束：

```sql
CREATE TABLE equipment_maintenance (
 id INTEGER PRIMARY KEY, equipment_id INTEGER NOT NULL REFERENCES equipment(id),
 loan_id INTEGER UNIQUE REFERENCES loans(id), started_by INTEGER REFERENCES users(id), start_at TEXT NOT NULL,
 reason TEXT NOT NULL, ended_by INTEGER REFERENCES users(id), end_at TEXT, result TEXT,
 CHECK(end_at IS NULL OR end_at >= start_at),
 CHECK((end_at IS NULL AND ended_by IS NULL AND result IS NULL) OR (end_at IS NOT NULL AND result IS NOT NULL))
)
```

## 16. 事件审计（event_audit）

| 字段 | SQL 类型 | 键与非空约束 | 默认值 |
| --- | --- | --- | --- |
| id | INTEGER | PK1 | — |
| actor_id | INTEGER | FK | — |
| actor_name | TEXT | NOT NULL | — |
| source_id | TEXT | NOT NULL | — |
| event_type | TEXT | NOT NULL | — |
| object_code | TEXT | NOT NULL | — |
| operation_code | TEXT | NOT NULL | — |
| target_id | TEXT | — | — |
| outcome | TEXT | NOT NULL | — |
| detail | TEXT | NOT NULL | — |
| created_at | TEXT | NOT NULL | — |

外键关系：

- `(actor_id) → users(id)`；删除策略 NO ACTION。

## 状态字段与联查投影

- `reservations.status` 只存 pending、approved、rejected、cancelled；API 的 borrowed/returned 由关联借还记录推导，`workflow_status` 保留原工作流状态。
- `loans` 不存状态副本：returned_at 为空表示借出未还，非空表示已归还。借出和归还检查分别保存，验收结果不覆盖借出说明。
- `equipment` 只存生命周期 active、disabled、retired；可预约状态再结合实验室/分类 active 和未结束维护记录推导。`equipment_maintenance` 每台设备至多一条 end_at 为空的开放维护，由部分唯一索引保护。
- `reservation_reviews.reservation_id` 唯一，每份申请当前只允许一次最终批准/驳回。更正决定需新建申请，不宣称提供多轮审批或会签。
- `sessions` 仅承担身份会话，不存自选激活角色集合；角色许可每次从授权关系实时求并集。
