# LabReserve 验收映射与证据清单

本文件依据最终已有证据更新验收状态；未重新执行测试。“自动化通过”仅指列出的实际断言或浏览器步骤通过，“代码审查”表示从源码核对，“未专项验证”表示没有为该分支单独执行验证，三者不混用。两份 JUnit XML 共 68 个不同用例、0 个失败/错误，浏览器记录为 24 步通过，均不等于所有扩展场景已经验证。

证据缩写：T = `evidence/pytest-results.xml`（67 项，执行文本 `evidence/pytest.txt`）；P = `evidence/pytest-persistence.xml`（1 项，执行文本 `evidence/pytest-persistence.txt`）；U = `evidence/browser/result.json`（24 步，按 steps 数组从 1 编号）。下文 `test_...` 是上述 XML 中可检索的实际用例名；参数化项按前缀匹配。浏览器截图位于 `evidence/browser/`。代码审查来源在相应行列明。

## 1. 四项要求与交付物

| 编号 | 作业要求 | 设计/交付物 | 应执行的验证 | 当前结论 |
| --- | --- | --- | --- | --- |
| R1 | 完整代码实现 | app、run.py、requirements.txt、tests、启动说明 | 清洁测试库初始化；启动；核心业务全链测试 | 自动化通过：T `test_complete_submit_approve_checkout_return_flow`；U 第 1—8 步真实页面链路通过 |
| R2 | 页面操作、角色及权限控制 | 共享页面、6 个演示账号、权限矩阵、服务端拒绝 | 角色切换截图；按钮可见性；直接构造越权请求 | 自动化/API 与浏览器关键场景通过：T、U 第 1—19 步；动态菜单/创建按钮专项边界见 A09、A11 |
| R3 | 分析页面/菜单/按钮异同及监听器机制 | design.md、ER/时序/状态图、固定事件 registry | 比较三类权限；检查 source_id 到对象/操作映射 | 设计与代码审查完成；T `test_page_menu_and_business_permissions_are_independent`、`test_auditor_can_read_registry_but_cannot_mutate` 通过；U 第 10、18 步通过 |
| R4 | 全部权限保存数据库表 | 7 张 RBAC 表、初始化许可、角色关联 | 表结构/主键/外键检查；修改许可后重启读取 | 数据库约束及应用对象重建持久化自动化通过：T `test_seven_rbac_tables_and_composite_foreign_keys`、P；真实进程重启未专项验证 |

## 2. 授权与事件机制验收

| ID | 前置与操作 | 预期判定 | 实际证据 | 实际结果 |
| --- | --- | --- | --- | --- |
| A01 | 未登录读取 /api/me 或受控列表 | 401；无业务数据泄露 | T `test_anonymous_wrong_password_and_logout`；`app/routes.py`、`app/auth.py` | /api/me 匿名拒绝自动化通过；各列表统一鉴权经代码审查 |
| A02 | 6 个种子账号分别登录，读取 /api/me | 返回正确角色列表；不返回密码/散列 | T `test_all_seed_accounts_can_log_in[...]`、`test_seed_login_password_hash_and_session_cookie`；U 第 1、4、6、9、15、17 步；`app/auth.py:public_user` | 六账号登录自动化/浏览器通过；公开字段白名单经代码审查 |
| A03 | multi 登录 | 同时含 student、teacher；许可等于二者并集 | T `test_multi_role_union_and_student_data_scope`、`test_existing_session_tracks_role_assignment_and_removal`；`app/rbac.py:permissions_for` | 双角色、关键并集权限自动化通过；完整并集算法代码审查 |
| A04 | 学生与教师打开同一预约页面 | 共用界面；学生无审批动作，教师有相应动作 | U 第 3、5 步；`02-student-reservation.png`、`03-teacher-approval.png`；`app/static/app.js:reservationActions` | 共享页学生提交/教师审批浏览器通过；按钮权限分支经代码审查 |
| A05 | 学生直接 POST reservation.approve | 403；原预约状态不变；拒绝审计可查 | T `test_fixed_registry_ignores_forged_authorization_fields`、`test_existing_session_loses_revoked_permission_immediately`；`app/events.py` | 学生直接审批拒绝自动化通过；撤权审批的状态不变及 denied 审计自动化通过 |
| A06 | 向事件接口发送未知 source_id | 400；不执行处理器，不改变业务 | T `test_fixed_binding_ignores_forged_authorization_fields`、`test_fixed_registry_ignores_forged_authorization_fields`；`app/events.py` | 未知事件 400 自动化通过；拒绝发生在处理器执行前经代码审查 |
| A07 | 在 payload 中伪造 operation/object/handler | 不能改变固定派发表解析结果；仍按 source_id 鉴权 | T `test_fixed_binding_ignores_forged_authorization_fields`；U 第 12 步 | envelope/payload 伪造字段自动化通过；旧会话伪造对象操作浏览器流程通过 |
| A08 | 读取 /api/events | 九项固定绑定；每项可追踪对象、操作、处理器 | T `test_auditor_can_read_registry_but_cannot_mutate`；U 第 18 步、`08-event-audit.png` | 九事件绑定、允许/拒绝记录自动化及浏览器通过 |
| A09 | 移除某角色 menu.reservations:view | 导航入口消失；不自动修改独立业务许可 | T `test_page_menu_and_business_permissions_are_independent`；`app/static/app.js:renderNavigation`；U 第 2 步仅验证种子角色菜单 | 接口独立性自动化通过；动态撤菜单后的 UI 仅代码审查，未专项浏览器验证；无“撤权前后菜单截图”声明 |
| A10 | 移除 page.reservations:view，保留 reservation:view | 页面访问/对应列表接口受到页面许可限制 | T `test_page_menu_and_business_permissions_are_independent`、`test_page_permission_is_independent_of_business_permission`；`app/static/app.js:go` | 页面许可撤销后的列表拒绝自动化通过；前端页面入口限制代码审查 |
| A11 | 保留 page/menu 查看许可，撤销 reservation:create | 仍可查看；提交按钮受控；直接提交为 403 | T `test_permission_revocation_affects_existing_cookie_session`；`app/static/app.js:renderReservations` | 创建许可动态撤销及直调 403 自动化通过；创建按钮撤权 UI 代码审查，未专项浏览器验证 |
| A12 | 管理员保存角色权限后刷新并重启 | 勾选结果从数据库恢复；无硬编码回填覆盖 | P `test_saved_permissions_survive_application_recreation_without_reseeding`；U 第 11、13 步 | 矩阵保存/恢复浏览器通过；同库应用对象重建后撤权仍生效自动化通过；真实操作系统进程重启未做 |
| A13 | 重复用户角色/不存在角色/不存在许可组合 | 外键或输入校验拒绝；原关联整体不变 | T `test_invalid_role_assignments_and_last_admin_protection`、`test_invalid_permission_replacements_leave_original_matrix_intact`、`test_seven_rbac_tables_and_composite_foreign_keys` | 自动化通过：非法角色/许可拒绝、关联不部分更新、外键约束生效 |
| A14 | 撤销管理员核心管理入口权限或移除最后管理员 | 拒绝造成管理失联的修改；有解释信息 | T `test_each_admin_management_permission_is_protected`、`test_invalid_role_assignments_and_last_admin_protection` | 自动化通过：4 项管理入口分别受保护；最后管理员保护和第二管理员交接生效 |
| A15 | 管理员执行普通业务动作 | 同样通过显式许可判定；无角色名旁路 | `app/rbac.py:require_permissions`、`app/events.py:PermissionListener.handle`、`app/db.py:_seed`；T `test_concurrent_nonoverlapping_checkouts_still_protect_one_physical_device` | 无管理员鉴权旁路经代码审查；管理员正常业务自动化通过；管理员业务许可专项撤销未另测 |
| A16 | 使用旧页面在权限撤销后继续提交 | 服务端按最新数据库许可拒绝 | T `test_existing_session_loses_revoked_permission_immediately`、`test_existing_session_tracks_role_assignment_and_removal`；U 第 11—13 步 | 同会话即时撤权/换角色自动化通过；教师旧会话直调 403 浏览器流程通过 |

## 3. 业务状态、数据归属与并发验收

| ID | 前置与操作 | 预期判定 | 实际证据 | 实际结果 |
| --- | --- | --- | --- | --- |
| B01 | 学生提交合法未来预约 | pending；申请人为当前用户 | T `test_complete_submit_approve_checkout_return_flow`、`test_fixed_binding_ignores_forged_authorization_fields`；U 第 3 步、`02-student-reservation.png` | 自动化/浏览器通过；伪造申请人和状态不会改变实际创建结果 |
| B02 | 指导教师批准该学生预约 | pending→approved；记录审批者 | T `test_complete_submit_approve_checkout_return_flow`；U 第 5 步、`03-teacher-approval.png`；`app/business.py:review_reservation` | 审批状态转换自动化/浏览器通过；审批人赋值经代码审查 |
| B03 | 设备管理员借出并归还 | approved→borrowed→returned；借还状态同步 | T `test_complete_submit_approve_checkout_return_flow`、`test_concurrent_returns_are_not_double_applied`；U 第 7—8 步、`04-loan-return.png` | 借还完整链及两表同步自动化/浏览器通过 |
| B04 | 教师或 multi 审批本人预约 | 409 或明确业务拒绝；状态不变 | T `test_self_review_forbidden_even_with_review_permission`（teacher、multi 两项）；U 第 16 步、`07-self-review-denied.png` | 自动化/浏览器通过：实际明确拒绝码为 403 / SELF_REVIEW_FORBIDDEN |
| B05 | 对 pending 驳回且不提供理由 | 400；无部分变更；提供理由后可进入 rejected | T `test_rejection_requires_note_and_audit_never_contains_secrets` | 自动化通过：空理由拒绝，补充理由后驳回，驳回后再次批准冲突 |
| B06 | 本人取消 pending/approved；他人学生取消 | 本人可取消；他人被拒；manage 许可按规则处理 | T `test_ownership_is_enforced_per_action_not_only_in_list`；U 第 21 步；`app/business.py:cancel_reservation` | 本人待审取消、他人拒绝、manage 取消自动化通过；本人待审取消浏览器通过；已批准取消分支代码审查 |
| B07 | 重复审批、借出、归还，或终态重新操作 | 409；不产生重复借还或状态倒退 | T `test_complete_submit_approve_checkout_return_flow`、`test_rejection_requires_note_and_audit_never_contains_secrets`、`test_concurrent_returns_are_not_double_applied`；`app/business.py` | 重复借出/归还及驳回后批准自动化通过；其余终态组合按状态守卫代码审查，未穷举全部组合 |
| B08 | 无效时间、过去时间、结束≤开始 | 400；不新增预约 | T `test_datetime_rejection_is_atomic_and_audited[...]`、`test_invalid_reservation_never_mutates[...]` | 自动化通过：非法日期、过去、倒序、相等、秒/时区边界均拒绝且不新增记录 |
| B09 | 同设备时间区间重叠的两个请求 | 至多一个进入有效占用；其他 409 | T `test_concurrent_overlapping_reservations_have_one_winner`、`test_concurrent_overlapping_submissions_serialize`、`test_overlap_half_open_interval_and_cancel_frees_slot` | 真实多连接竞争和顺序冲突自动化通过：仅一笔占用成功 |
| B10 | 同设备 10:00—11:00 与 11:00—12:00 | 半开区间允许衔接 | T `test_half_open_adjacent_reservations_do_not_conflict`、`test_overlap_half_open_interval_and_cancel_frees_slot` | 自动化通过：相邻半开区间可衔接 |
| B11 | 前一实物未归还，再借出另一时段预约 | 409；不能因为预约时段不重叠重复借出实物 | T `test_physical_device_blocks_second_checkout_even_for_different_dates`、`test_concurrent_nonoverlapping_checkouts_still_protect_one_physical_device` | 顺序/并发实物占用自动化通过，最多一笔未归还借用 |
| B12 | 维护设备创建预约/办理借出 | 按设备可用规则拒绝 | T `test_maintenance_blocks_submission_and_preserves_existing_reservations`、`test_checkout_defensively_checks_maintenance_after_approval`、`test_equipment_validation_and_maintenance_guard` | 自动化通过：维护设备不能申请/借出；有效预约阻止切维护 |
| B13 | 超过预约结束时间办理借出 | 409；未新增借还 | T `test_checkout_end_time_boundary_matches_contract`（-1、0、1 秒三项）、`test_checkout_rejects_half_open_end_and_expired_reservation[...]`；`app/business.py:checkout_loan` | 自动化通过：结束前 1 秒允许，结束时及以后拒绝；拒绝先于借还写入经代码审查 |
| B14 | 普通学生读取列表、导出或单条变更 | 数据限本人；导出还需 export 许可 | T `test_multi_role_union_and_student_data_scope`、`test_ownership_is_enforced_per_action_not_only_in_list`、`test_csv_bom_formula_escape_and_export_authorization`；`app/routes.py:export_reservations` | 本人列表、跨用户取消拒绝、无 export 拒绝自动化通过；授予 export 后本人数据范围经代码审查 |
| B15 | 审批、借还管理、审计身份读取数据 | 仅按授予的管理能力获取所需数据 | T `test_multi_role_union_and_student_data_scope`、`test_auditor_can_read_registry_but_cannot_mutate`；U 第 5、7、18—19 步；`app/rbac.py:full_scope` | 关键管理身份查询/操作自动化及浏览器通过；各种动态许可组合的数据范围未逐一专项验证 |
| B16 | 并发授权/分配角色及业务写入 | 无半次替换；合法事务完整提交，失败回滚 | T `test_invalid_permission_replacements_leave_original_matrix_intact`、`test_invalid_role_assignments_and_last_admin_protection`、`test_mid_transaction_domain_failure_rolls_back_and_keeps_audit`、业务并发用例；`app/events.py` | 部分自动化通过：关联替换原子性、失败回滚、业务并发；授权变更与业务提交相互竞争未专项并发验证，BEGIN IMMEDIATE 内重查权限经代码审查 |

## 4. 基础防护与交付检查

| ID | 检查 | 预期 | 实际证据 | 实际结果 |
| --- | --- | --- | --- | --- |
| C01 | 数据库 schema 与 PRAGMA foreign_key_list | 七表核心；permissions 两列联合 PK；role_permissions 三列联合 PK/复合 FK | T `test_seven_rbac_tables_and_composite_foreign_keys`；`app/db.py:SCHEMA` | 七表存在、许可联合主键与非法外键拒绝自动化通过；角色许可三列主键/复合外键定义代码审查 |
| C02 | 无 CSRF 或错误 CSRF 的变更请求 | 拒绝且无业务变更 | T `test_csrf_and_cross_origin_are_blocked`、`test_csrf_origin_logout_and_old_session_reuse`、`test_malformed_origin_is_rejected_as_csrf_instead_of_internal_error` | 自动化通过：缺失、错误、跨源及损坏 Origin 均拒绝，无业务变更 |
| C03 | 注销后复用旧会话 | 401；不能继续变更 | T `test_csrf_origin_logout_and_old_session_reuse`、`test_login_rotates_session_and_expiration_boundary`；U 第 23 步 | 注销旧 Cookie、登录轮换、12 小时到期自动化通过；页面退出后拒绝访问浏览器通过 |
| C04 | 特殊字符/脚本样式的目的与说明 | 以文本显示；不执行脚本 | `app/static/app.js:h`、各列表/对话框渲染、textContent 用法；U 第 24 步仅检查普通流程无 JS 异常 | 转义实现代码审查完成；未做专项 XSS 攻击字符串浏览器测试，不把普通流程无异常视为 XSS 测试通过 |
| C05 | CSV 字段以 =、+、-、@ 等开头 | 正确转义、带 UTF-8 BOM，保持相同数据范围 | T `test_csv_bom_formula_escape_and_export_authorization`；U 第 20 步；`app/routes.py:csv_safe`、`export_reservations` | BOM、= 公式转义、无权限拒绝自动化通过；真实 CSV 下载浏览器通过；+/-/@ 分支及同数据范围代码审查 |
| C06 | 成功、拒绝、无效事件记录 | actor/source/object/operation/outcome 对应；无密码或令牌 | T `test_existing_session_loses_revoked_permission_immediately`、`test_mid_transaction_domain_failure_rolls_back_and_keeps_audit`、`test_rejection_requires_note_and_audit_never_contains_secrets`、`test_permission_revocation_affects_existing_cookie_session`；U 第 18 步 | 允许/拒绝/失败审计、角色目标编号及不含演示密码/CSRF 自动化通过；真实审计页浏览器通过 |
| C07 | 初始化与重置 | 默认不破坏已有数据；仅显式 --reset 执行重置 | P `test_saved_permissions_survive_application_recreation_without_reseeding`；`run.py:main`、`app/db.py:initialize_database` | 同库应用对象重建不覆盖授权自动化通过；显式 --reset 门控仅代码审查，未专项执行重置测试 |
| C08 | 图表、报告与仓库 | 设计图与截图明确区分；无虚构结果；可复现启动；远程同步到指定仓库 | `docs/design.md`、`docs/independent-review.md`、设计图与 U 截图；最终报告/Git 证据由项目负责人补充 | 设计图/截图区分及证据审查完成；19页报告逐页排版检查通过，见 evidence/report-quality.json；源码与报告提交main，远程一致性由交付说明和Git核验记录确认 |

## 5. 证据记录约定

测试只能连接独立临时数据库，不能重置用于截图和演示的工作数据库。自动化日志至少记录执行命令、用例数量、成功/失败、执行时间；截图应标明账号、页面与操作场景，避免展示密码输入及令牌。数据库证据只摘取与授权和状态有关的必要列，不输出密码散列和会话散列。高分辨率设计图可复现，但不能作为“系统已实现”或“测试已通过”的唯一证据。

验收汇总建议字段为：ID、实际执行时间、执行环境、结果、证据路径、问题及修复记录。若环境限制导致某项未做，应写“未执行”和具体原因；不能用设计推导替代实测通过，也不能把自动化 API 测试等同于已完成全部人工页面验证。
