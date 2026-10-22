# LabReserve API 契约

实现为 Flask + SQLite + 原生 HTML/CSS/JavaScript，本地默认入口 `http://127.0.0.1:8783`，Python 3.11+。数据库版本 2，共 16 张表；完整字段、主外键与索引见 [database-schema.md](database-schema.md)。

## 通用约定

成功为 `{ok:true,data:...}`，失败为 `{ok:false,error:{code,message}}`。会话 Cookie 由服务端设置，浏览器变更请求发送登录或 `/api/me` 返回的 CSRF 令牌，头名为 `X-CSRF-Token`；存在 Origin 时必须与本站协议和主机相同，损坏 Origin 返回 CSRF 拒绝。日期按 Asia/Shanghai 本地时间解释，预约输入为分钟精度 ISO 字符串；不接受带时区后缀或非零秒。

| 状态码 | 语义 |
| --- | --- |
| 400 | 输入不合法、未知事件源或未知许可组合 |
| 401 | 未登录、过期或注销会话 |
| 403 | 缺少许可、CSRF/来源失败、禁止自审、归属不允许 |
| 404 | 指定设备、申请、借还或主数据记录不存在 |
| 409 | 时段/状态/唯一业务约束冲突、管理员保护 |
| 413 | 请求超过 128 KiB |
| 500 | 统一内部错误 JSON，不返回内部堆栈 |

所有 ID 输入使用正整数，布尔值不能冒充 ID。角色权限每次从数据库实时求并集，没有会话自选激活角色或管理员角色名旁路。

## 身份与查询

| 方法与路径 | 要求 | data |
| --- | --- | --- |
| POST /api/login | `{username,password}`；同源 | `{user,permissions,csrf_token}`，并设置 Cookie |
| GET /api/me | 有效会话 | 与登录相同；user 含 id/username/display_name/roles，roles 为 id/code/name 数组 |
| POST /api/logout | 有效会话与 CSRF | `{}`，删除会话与 Cookie |
| GET /api/dashboard | page.dashboard:view | equipment_count、pending_count、approved_count、borrowed_count、my_reservation_count、permission_count |
| GET /api/equipment | page.equipment:view + equipment:view | 设备联查数组，字段见下文 |
| GET /api/equipment/metadata | page.equipment:view + equipment:view | `{laboratories,categories,managers}` |
| GET /api/maintenance | page.equipment:view + equipment:view | 维护记录联查数组 |
| GET /api/reservations | page.reservations:view + reservation:view | 按数据范围过滤的预约联查数组 |
| GET /api/loans | page.loans:view + loan:view | 按数据范围过滤的借还联查数组 |
| GET /api/audit | page.audit:view + audit:view | 最新 200 条事件审计，倒序 |
| GET /api/events | page.audit:view + audit:view | `{bindings,recent}`，15 项固定绑定与最新审计 |
| GET /api/rbac | page.rbac:view + rbac:view | `{roles,users,objects,operations,permissions,role_permissions}` |
| GET /api/export/reservations | page.reservations:view + reservation:export | UTF-8 BOM CSV；与预约查询复用数据范围，公式前缀转义 |

身份查询只公开用户必要字段，不返回密码散列、原始会话令牌或数据库会话摘要。演示账号 student、teacher、keeper、admin、auditor、multi 的初始化密码为 `Lab@2026!`；multi 同时分配 student 与 teacher，auditor 拥有全部受支持 view 和预约 export，不具有变更许可。

### 设备与主数据响应

设备字段包括 `id,code,name,model,category_id,laboratory_id,location,lifecycle_status,description,created_by,created_at,updated_at`，以及联查的 `category,category_name,category_active,laboratory_name,laboratory_active,status,maintenance_id`。code 是每台实物唯一资产编号；model 可以重复，不表示一行存多台。设备 location 可表示实验室内的存放架位，实验室自身 location 表示房间/地理位置。

设备不存冗余的 available/maintenance 状态列。`status` 按顺序推导：生命周期非 active 时为 disabled/retired；分类或实验室未启用时为 disabled；有未结束维护时为 maintenance；否则 available。`maintenance_id` 是当前开放维护记录 ID。available 不替代时段冲突和未归还实物检查。

metadata.laboratories 含 `id,code,name,location,manager_id,active,description,manager_name`；categories 含 `id,code,name,active,description`；两者 active 返回 JSON 布尔。managers 是所有有效用户的 `id,username,display_name`，用于负责人选择，不表示这些用户自动拥有管理角色。

维护记录含 `id,equipment_id,loan_id,started_by,start_at,reason,ended_by,end_at,result,equipment_name,equipment_code,started_by_name,ended_by_name,status`。status 由 end_at 推导为 open/closed；loan_id 为空表示普通维护，非空时可关联异常验收借还。

### 预约、审批与借还响应

预约字段包括 `id,equipment_id,equipment_name,equipment_code,user_id,applicant_name,start_at,end_at,purpose,workflow_status,status,review_id,reviewer_id,review_decision,reviewed_at,reviewer_name,review_note,created_at,updated_at,cancelled_at,cancelled_by`。

`workflow_status` 是预约实际存储的 pending/approved/rejected/cancelled；展示 `status` 在无借还时使用工作流状态，有未归还借还时为 borrowed，归还完成后为 returned。因此借出与归还不把预约表改成 borrowed/returned。每个 reservation_id 最多一条 reservation_reviews 最终决定；驳回后应新建申请。

借还字段为表中全部字段 `id,reservation_id,checkout_by,checkout_at,checkout_condition,returned_by,returned_at,return_condition,acceptance_result`，加上 `equipment_id,equipment_code,equipment_name,user_id,applicant_name,checkout_by_name,returned_by_name,status,condition_note,maintenance_id`。status 根据 returned_at 推导 borrowed/returned；condition_note 为兼容展示别名，优先归还说明，否则借出说明。新界面必须分别使用 checkout_condition 和 return_condition。

acceptance_result 新归还只允许 passed 或 damaged；unknown 仅用于迁移的历史验收未知记录。旧历史未记录的人员、审批时间和创建时间等允许为空，客户端应显示“—/未知”，不能把空值伪造为当前操作人或当前时间。

普通申请人查询只见本人预约和借还。拥有 reservation:approve/reject/manage、loan:checkout/return 或 audit:view 任一管理能力时采用全量范围。实验室负责人字段不会自动改变范围。

## 统一变更接口

`POST /api/events` 请求为：

```json
{"source_id":"reservation.submit","payload":{"equipment_id":1,"start_at":"2030-01-02T09:00","end_at":"2030-01-02T10:00","purpose":"实验用途"}}
```

需要有效会话及 CSRF。服务端从不可由请求改写的 registry 解析 source_id，不信任请求中的 object_code、operation_code、handler、操作者或目标状态。界面按钮 click 用于打开确认/检查表单；最终业务动作均由表单 submit 触发，15 项绑定的 event_type 均为 submit。

| source_id | 固定许可 | payload | 成功 data |
| --- | --- | --- | --- |
| equipment.save | equipment:update | `{id?,code,name,model?,category_id,laboratory_id,location,lifecycle_status?,description?}` | 更新后的设备联查对象 |
| laboratory.save | equipment:update | `{id?,code,name,location,manager_id?,description?}` | 实验室对象，含负责人显示名 |
| laboratory.set_active | equipment:update | `{id,active:boolean}` | 实验室对象，active 为布尔 |
| category.save | equipment:update | `{id?,code,name,description?}` | 分类对象 |
| category.set_active | equipment:update | `{id,active:boolean}` | 分类对象，active 为布尔 |
| maintenance.start | equipment:update | `{equipment_id,reason}` | 新开放维护对象 |
| maintenance.end | equipment:update | `{id,result}` | 已关闭维护对象 |
| reservation.submit | reservation:create | `{equipment_id,start_at,end_at,purpose}` | 新 pending 预约对象 |
| reservation.approve | reservation:approve | `{id,note?}` | 预约对象，含独立 approved 审批记录 |
| reservation.reject | reservation:reject | `{id,note}` | 预约对象，含独立 rejected 审批记录 |
| reservation.cancel | reservation:cancel | `{id}` | cancelled 预约对象，含取消人/时间 |
| loan.checkout | loan:checkout | `{reservation_id,checkout_condition?}` | 新借还对象，借出经办人为当前用户 |
| loan.return | loan:return | `{id,return_condition,acceptance_result?}` | 已归还借还对象；结果默认 passed |
| rbac.save_permissions | rbac:manage | `{role_id,permissions:["equipment:view",...]}` | `{message}` |
| rbac.assign_roles | rbac:manage | `{user_id,role_ids:[int,...]}` | `{message}` |

### 业务规则与兼容行为

- 实验室 code、分类 code/name、设备资产 code 不可重复；负责人必须是有效用户或空。启停使用单独 set_active 事件，active 必须为 JSON 布尔。
- 分类/实验室有关联未来有效预约或未归还借用时不能停用。已停用的分类/实验室不能用于保存新设备；设备不可预约、批准或借出。
- lifecycle_status 为 active/disabled/retired，默认 active。已报废设备不能重新启用；有效预约或未归还借用阻止停用/报废。
- 设备保存兼容旧 category 名称、status 和缺少 laboratory_id 的输入：分类按已有名称查找；更新默认原实验室，新增缺省取首个启用实验室；legacy status=maintenance 会调用真实维护登记，而非只改展示标记。新界面应发送规范 ID 和 lifecycle_status。
- 手动维护要求设备派生状态 available、无有效预约和未归还借用，reason 必填；结束维护 result 必填且不能重复结束。结束只关闭记录，不自动重新启用分类/实验室或报废设备。
- 新预约使用当前用户作为申请人，拒绝过去/逆序/相等时间；半开区间允许首尾相接。pending/approved 且尚未归还完成的关联占用参与时段冲突检查。
- 批准/驳回均不可自审、只接受 pending、只允许一份终审；驳回必须提供 note；批准重查设备有效、未过期和时段冲突。
- 取消要求本人或另有 reservation:manage，且流程为 pending/approved、尚无任何借还记录。保留原审批历史。
- 借出要求已批准、该申请从未生成借还、now 严格早于 end_at、设备有效可用、该实物无任何未归还借用；允许早于预约开始办理。checkout_condition 在 API 中可空，新界面要求填写。
- 归还要求尚未归还，return_condition 必填，acceptance_result 为 passed/damaged。damaged 同事务自动建立关联 loan_id 维护，不因其他未来预约而跳过；未来预约保留，但维护解除前不能批准/借出。passed 不创建维护。
- 借出/归还兼容旧 condition_note 输入，但始终分别写入 checkout_condition/return_condition，不覆盖历史检查。
- 权限集合必须全部来自已定义 permissions，重复/未知值拒绝并整体回滚。管理员核心管理入口不可撤空；用户角色不可空、不可重复/未知，且必须保留至少一个有效管理员。

## 授权对象与审计

页面/菜单对象分别为 page.* / menu.* 的 dashboard、equipment、reservations、loans、rbac、audit，操作均为 view。业务许可对为 equipment:view/update；reservation:view/create/approve/reject/cancel/manage/export；loan:view/checkout/return；rbac:view/manage；audit:view。新增主数据和维护事件共用 equipment:update，未新增隐含权限对象。

成功事件与 accepted 审计同事务提交。领域错误回滚后单独写 denied（401/403）或 invalid（其他业务/输入错误）审计；约束错误转换为 409；内部错误回滚并写可公开失败原因。审计不记录密码、会话令牌或 CSRF。

审计响应字段为 `id,actor_name,source_id,event_type,object_code,operation_code,target_id,outcome,detail,created_at`。target_id 在成功时优先采用返回记录 ID，故随 source_id 分别指向设备、实验室、分类、维护、预约、借还、角色或用户；不能只凭 object_code=equipment 就把维护目标误当资产 ID。

## 数据升级

启动自动检测旧设备结构并迁移，`PRAGMA user_version=2`。也可运行：

```powershell
.\.venv\Scripts\python.exe scripts/migrate_database.py
```

该脚本保留数据、先备份旧库，并输出表计数、字段、外键、索引和 foreign_key_check。旧12表数据不是通过 --reset 升级；迁移保留原 ID、RBAC、会话和审计，未知旧经办人/审批时间保持空，旧验收保持 unknown。
