# LabReserve 验收映射与证据清单

适用数据库版本2：16表、96字段、15项submit业务绑定。最终后端结果为85 passed in69.39s，0失败/错误；T=evidence/pytest-results.xml（文本evidence/pytest.txt）。P=evidence/pytest-persistence.xml仅为T中的持久化子集，不与T相加。

本表区分“自动化通过”“代码审查”“未专项验证”。U=evidence/browser/result.json，版本2真实Edge浏览器34步全部通过，console_errors和unexpected_http_errors均为空；步骤编号按steps数组从1起。下文test_名称可在T中按完整名字或参数化前缀检索。

## 1. 交付能力与证据

| 编号 | 验收目标 | 设计/交付物 | 应执行的验证 | 当前结论 |
| --- | --- | --- | --- | --- |
| R1 | 完整代码实现 | app、run.py、requirements.txt、tests、启动说明 | 隔离初始化；核心业务链；主数据/维护/迁移 | 85项自动化通过；U 34步通过，含主数据、维护和完整借还链；迁移由T专项验证 |
| R2 | 页面操作、角色及权限控制 | 共享页面、6账号、权限矩阵、服务端拒绝 | 角色/页面/按钮边界，直调与新增事件越权 | T核心授权/6新增事件拒绝与U第18—29步通过；动态撤菜单/创建按钮专项边界见A09/A11 |
| R3 | RBAC与监听器机制分析 | design.md、API、模型簇与ER/事件图 | 页面/菜单/动作差异，固定事件映射 | T独立许可/registry通过，U第18、28步真实矩阵和15绑定通过；全部submit/DOM映射代码审查 |
| R4 | 全部权限数据库持久化 | 7张RBAC核心、16表业务与技术关系 | 主外键、矩阵持久化、旧库升级 | T持久化与16表迁移自动化通过；P为全量中的子集；真实OS进程重启未专项验证 |

## 2. 授权与事件机制验收

| ID | 前置与操作 | 预期判定 | 实际证据 | 实际结果 |
| --- | --- | --- | --- | --- |
| A01 | 未登录读取 /api/me 或受控列表 | 401；无业务数据泄露 | T `test_anonymous_wrong_password_and_logout`；`app/routes.py`、`app/auth.py` | /api/me 匿名拒绝自动化通过；各列表统一鉴权经代码审查 |
| A02 | 6种子账号登录并读取身份 | 正确角色列表，无密码散列公开 | T test_all_seed_accounts_can_log_in[...]；U第1、10、13、17、23、25步；app/auth.py:public_user | 六账号登录API/浏览器通过；公开字段白名单代码审查 |
| A03 | multi 登录 | 同时含 student、teacher；许可等于二者并集 | T `test_multi_role_union_and_student_data_scope`、`test_existing_session_tracks_role_assignment_and_removal`；`app/rbac.py:permissions_for` | 双角色、关键并集权限自动化通过；完整并集算法代码审查 |
| A04 | 学生与教师共享预约页面 | 学生提交，教师审批他人，按钮权限不同 | T test_complete_submit_approve_checkout_return_flow；U第12、14步，02-student-reservation.png、03-teacher-approval.png；reservationActions | 共享页提交/审批浏览器通过；按钮分支结合代码审查 |
| A05 | 学生直接 POST reservation.approve | 403；原预约状态不变；拒绝审计可查 | T `test_fixed_registry_ignores_forged_authorization_fields`、`test_existing_session_loses_revoked_permission_immediately`；`app/events.py` | 学生直接审批拒绝自动化通过；撤权审批的状态不变及 denied 审计自动化通过 |
| A06 | 向事件接口发送未知 source_id | 400；不执行处理器，不改变业务 | T `test_fixed_binding_ignores_forged_authorization_fields`、`test_fixed_registry_ignores_forged_authorization_fields`；`app/events.py` | 未知事件 400 自动化通过；拒绝发生在处理器执行前经代码审查 |
| A07 | payload伪造operation/object/handler | 不能改变固定映射与身份 | T test_fixed_binding_ignores_forged_authorization_fields；U第20步 | 自动化及旧会话直调/伪造字段浏览器流程通过 |
| A08 | 读取/api/events | 15项固定submit绑定及审计 | T test_auditor_can_read_registry_but_cannot_mutate；U第28步、08-event-audit.png；app/events.py | 15绑定API/浏览器通过；全部submit和点击仅开表单经代码审查 |
| A09 | 移除menu.reservations:view | 菜单受控，业务许可独立 | T test_page_menu_and_business_permissions_are_independent；app.js:renderNavigation；U第11步仅种子菜单隐藏 | 接口独立性自动化通过；动态撤菜单UI仍仅代码审查，未专项浏览器验证 |
| A10 | 移除 page.reservations:view，保留 reservation:view | 页面访问/对应列表接口受到页面许可限制 | T `test_page_menu_and_business_permissions_are_independent`、`test_page_permission_is_independent_of_business_permission`；`app/static/app.js:go` | 页面许可撤销后的列表拒绝自动化通过；前端页面入口限制代码审查 |
| A11 | 保留 page/menu 查看许可，撤销 reservation:create | 仍可查看；提交按钮受控；直接提交为 403 | T `test_permission_revocation_affects_existing_cookie_session`；`app/static/app.js:renderReservations` | 创建许可动态撤销及直调 403 自动化通过；创建按钮撤权 UI 代码审查，未专项浏览器验证 |
| A12 | 保存权限、刷新和重建应用 | 数据库撤权恢复，无种子覆盖 | T/P test_saved_permissions_survive_application_recreation_without_reseeding；U第19、21步 | 矩阵撤销/恢复浏览器通过，同库应用对象重建自动化通过；真实OS进程重启未做，P不另计 |
| A13 | 重复用户角色/不存在角色/不存在许可组合 | 外键或输入校验拒绝；原关联整体不变 | T `test_invalid_role_assignments_and_last_admin_protection`、`test_invalid_permission_replacements_leave_original_matrix_intact`、`test_seven_rbac_tables_and_composite_foreign_keys` | 自动化通过：非法角色/许可拒绝、关联不部分更新、外键约束生效 |
| A14 | 撤销管理员核心管理入口权限或移除最后管理员 | 拒绝造成管理失联的修改；有解释信息 | T `test_each_admin_management_permission_is_protected`、`test_invalid_role_assignments_and_last_admin_protection` | 自动化通过：4 项管理入口分别受保护；最后管理员保护和第二管理员交接生效 |
| A15 | 管理员执行普通业务动作 | 同样通过显式许可判定；无角色名旁路 | `app/rbac.py:require_permissions`、`app/events.py:PermissionListener.handle`、`app/db.py:_seed`；T `test_concurrent_nonoverlapping_checkouts_still_protect_one_physical_device` | 无管理员鉴权旁路经代码审查；管理员正常业务自动化通过；管理员业务许可专项撤销未另测 |
| A16 | 旧会话在撤权后提交 | 最新数据库许可拒绝 | T test_existing_session_loses_revoked_permission_immediately、test_existing_session_tracks_role_assignment_and_removal；U第19—21步 | 即时撤权/角色变更自动化通过；教师旧会话403浏览器流程通过 |

## 3. 业务状态、数据归属与并发验收

| ID | 前置与操作 | 预期判定 | 实际证据 | 实际结果 |
| --- | --- | --- | --- | --- |
| B01 | 合法未来预约 | pending，申请人为当前用户 | T test_complete_submit_approve_checkout_return_flow、test_fixed_binding_ignores_forged_authorization_fields；U第12步 | API/浏览器通过；伪造申请人/状态自动化拒绝 |
| B02 | 教师批准他人申请 | approved及独立审批记录 | T test_independent_final_review_and_four_stored_states；U第14步、03-teacher-approval.png | 独立review_id、审批人/时间及四态工作流自动化/浏览器通过 |
| B03 | 借出并归还 | 借还事实与显示一致，工作流仍approved | T test_return_preserves_checkout_inspection_and_frees_original_slot；U第15—16步、12-loan-inspection.png、04-loan-return.png | 独立双经办/检查与验收API/浏览器通过；存储approved、展示returned由专项用例核实 |
| B04 | 教师/multi自审 | 明确拒绝，记录不变 | T test_self_review_forbidden_even_with_review_permission（两项）；U第24步、07-self-review-denied.png | 自动化及浏览器通过，实际403/SELF_REVIEW_FORBIDDEN |
| B05 | 对 pending 驳回且不提供理由 | 400；无部分变更；提供理由后可进入 rejected | T `test_rejection_requires_note_and_audit_never_contains_secrets` | 自动化通过：空理由拒绝，补充理由后驳回，驳回后再次批准冲突 |
| B06 | 本人/他人/manage取消 | 归属受控，借后不得取消 | T test_ownership_is_enforced_per_action_not_only_in_list、test_return_preserves_checkout_inspection_and_frees_original_slot；U第31步 | 本人/他人/manage和借后拒绝自动化通过；本人待审确认取消浏览器通过；已批准未借出取消代码审查 |
| B07 | 重复审批、借出、归还，或终态重新操作 | 409；不产生重复借还或状态倒退 | T `test_complete_submit_approve_checkout_return_flow`、`test_rejection_requires_note_and_audit_never_contains_secrets`、`test_concurrent_returns_are_not_double_applied`；`app/business.py` | 重复借出/归还及驳回后批准自动化通过；其余终态组合按状态守卫代码审查，未穷举全部组合 |
| B08 | 无效时间、过去时间、结束≤开始 | 400；不新增预约 | T `test_datetime_rejection_is_atomic_and_audited[...]`、`test_invalid_reservation_never_mutates[...]` | 自动化通过：非法日期、过去、倒序、相等、秒/时区边界均拒绝且不新增记录 |
| B09 | 同设备时间区间重叠的两个请求 | 至多一个进入有效占用；其他 409 | T `test_concurrent_overlapping_reservations_have_one_winner`、`test_concurrent_overlapping_submissions_serialize`、`test_overlap_half_open_interval_and_cancel_frees_slot` | 真实多连接竞争和顺序冲突自动化通过：仅一笔占用成功 |
| B10 | 同设备 10:00—11:00 与 11:00—12:00 | 半开区间允许衔接 | T `test_half_open_adjacent_reservations_do_not_conflict`、`test_overlap_half_open_interval_and_cancel_frees_slot` | 自动化通过：相邻半开区间可衔接 |
| B11 | 前一实物未归还，再借出另一时段预约 | 409；不能因为预约时段不重叠重复借出实物 | T `test_physical_device_blocks_second_checkout_even_for_different_dates`、`test_concurrent_nonoverlapping_checkouts_still_protect_one_physical_device` | 顺序/并发实物占用自动化通过，最多一笔未归还借用 |
| B12 | 维护设备申请/借出 | 维护与主数据可用规则生效 | T test_maintenance_blocks_submission_and_preserves_existing_reservations、test_checkout_defensively_checks_maintenance_after_approval；U第5—9步、11-maintenance-lifecycle.png | 维护不可选/完成恢复及父档案启停浏览器通过；维护后借出再次校验由API用例证明 |
| B13 | 超过预约结束时间办理借出 | 409；未新增借还 | T `test_checkout_end_time_boundary_matches_contract`（-1、0、1 秒三项）、`test_checkout_rejects_half_open_end_and_expired_reservation[...]`；`app/business.py:checkout_loan` | 自动化通过：结束前 1 秒允许，结束时及以后拒绝；拒绝先于借还写入经代码审查 |
| B14 | 普通学生读取列表、导出或单条变更 | 数据限本人；导出还需 export 许可 | T `test_multi_role_union_and_student_data_scope`、`test_ownership_is_enforced_per_action_not_only_in_list`、`test_csv_bom_formula_escape_and_export_authorization`；`app/routes.py:export_reservations` | 本人列表、跨用户取消拒绝、无 export 拒绝自动化通过；授予 export 后本人数据范围经代码审查 |
| B15 | 管理能力读取数据 | 按能力获取范围 | T test_multi_role_union_and_student_data_scope、test_auditor_can_read_registry_but_cannot_mutate；U第14—16、26—29步 | 关键管理身份API/浏览器通过；所有动态许可组合未逐一专项验证 |
| B16 | 并发授权/分配角色及业务写入 | 无半次替换；合法事务完整提交，失败回滚 | T `test_invalid_permission_replacements_leave_original_matrix_intact`、`test_invalid_role_assignments_and_last_admin_protection`、`test_mid_transaction_domain_failure_rolls_back_and_keeps_audit`、业务并发用例；`app/events.py` | 部分自动化通过：关联替换原子性、失败回滚、业务并发；授权变更与业务提交相互竞争未专项并发验证，BEGIN IMMEDIATE 内重查权限经代码审查 |

## 4. 基础防护与交付检查

| ID | 检查 | 预期 | 实际证据 | 实际结果 |
| --- | --- | --- | --- | --- |
| C01 | 16表schema、主键/外键/索引 | 7核心授权、独立审批借还维护，字段一致 | T test_seven_rbac_tables_and_composite_foreign_keys、test_v1_migration_preserves_all_existing_data_and_backup、test_catalog_assets_enable_disable_and_foreign_keys；database-schema.md | 16表/FK与关键约束自动化通过；96字段及三列PK/复合FK定义静态核对 |
| C02 | 无 CSRF 或错误 CSRF 的变更请求 | 拒绝且无业务变更 | T `test_csrf_and_cross_origin_are_blocked`、`test_csrf_origin_logout_and_old_session_reuse`、`test_malformed_origin_is_rejected_as_csrf_instead_of_internal_error` | 自动化通过：缺失、错误、跨源及损坏 Origin 均拒绝，无业务变更 |
| C03 | 注销旧会话/轮换/过期 | 401，不可继续变更 | T test_csrf_origin_logout_and_old_session_reuse、test_login_rotates_session_and_expiration_boundary；U第33步 | 会话边界自动化通过，页面退出失效浏览器通过 |
| C04 | 脚本样式输入显示 | 文本转义，不执行脚本 | app.js:h/textContent/列表渲染；U第34步仅一般流程无JS错误 | 转义代码审查完成；未做专项XSS攻击字符串浏览器测试，U第34步不替代该验证 |
| C05 | CSV公式前缀/BOM/范围 | 转义、BOM、授权范围 | T test_csv_bom_formula_escape_and_export_authorization；U第30步；routes.py:csv_safe | BOM、=公式、无权限拒绝API通过，真实CSV下载浏览器通过；+/-/@分支和同范围代码审查 |
| C06 | 各结果审计及目标 | 固定绑定匹配，不记录密码令牌 | T test_rejection_requires_note_and_audit_never_contains_secrets、test_new_events_all_require_equipment_update_and_log_denial[...]；U第27—28步、14-audit-denied.png、08-event-audit.png | API及允许/拒绝审计页浏览器通过；目标类型须结合source解释 |
| C07 | 初始化、迁移与显式重置 | 保留已有数据，reset单独授权参数 | T test_saved_permissions_survive_application_recreation_without_reseeding、test_v1_migration_preserves_all_existing_data_and_backup；run.py | 应用重建/非破坏迁移自动化通过；--reset仅代码审查，未专项执行重置 |
| C08 | 图表、报告与公开仓库 | 图/截图区分、实码一致、远程同步 | 设计/字段/事件文档；U新截图；evidence/report-quality.json；公开main分支与交付说明 | 16表/15事件、85项自动化和34步浏览器通过；28页报告逐页核对，RBAC模型簇有5个完整正文页；公开仓库main同步，具体提交号见交付说明 |

## 5. 证据记录约定

测试只能连接独立临时数据库，不能重置用于截图和演示的工作数据库。自动化日志至少记录执行命令、用例数量、成功/失败、执行时间；截图应标明账号、页面与操作场景，避免展示密码输入及令牌。数据库证据只摘取与授权和状态有关的必要列，不输出密码散列和会话散列。高分辨率设计图可复现，但不能作为“系统已实现”或“测试已通过”的唯一证据。

验收汇总建议字段为：ID、实际执行时间、执行环境、结果、证据路径、问题及修复记录。若环境限制导致某项未做，应写“未执行”和具体原因；不能用设计推导替代实测通过，也不能把自动化 API 测试等同于已完成全部人工页面验证。

## 6. 版本2业务与迁移增量

| ID | 验收目标 | 实际自动化证据（T） | 结果与边界 |
| --- | --- | --- | --- |
| D01 | 实验室/分类/同型号资产与FK | T test_catalog_assets_enable_disable_and_foreign_keys；U第2—4步、10a-laboratory-form.png、10-equipment-assets.png | 自动化/浏览器通过：主数据、负责人、独立资产编号/型号/外键；FK破坏拒绝为API验证 |
| D02 | 父档案停用/设备服役/报废 | T test_live_reservations_block_parent_disable_and_equipment_retirement、test_retired_asset_cannot_be_reactivated_and_legacy_failure_is_atomic；U第8—9步 | 父档案启停和设备停用恢复浏览器通过；有效预约保护/不可复活由API验证 |
| D03 | 独立终审与四态存储 | T test_independent_final_review_and_four_stored_states；U第14步 | API/浏览器通过；唯一终审及禁止borrowed写入预约表由数据库用例证明 |
| D04 | 双检查/双经办/验收与归还释放 | T test_return_preserves_checkout_inspection_and_frees_original_slot、test_invalid_return_rolls_back_without_losing_checkout；U第15—16步、12-loan-inspection.png | 正常验收双记录API/浏览器通过；非法unknown和释放区间由API用例证明 |
| D05 | 手工维护历史与唯一开放 | T test_maintenance_complete_history_and_unique_open_record；U第5—7步、11-maintenance-lifecycle.png | 真实表单开始/不可预约/结束恢复浏览器通过；部分唯一/重复拒绝由API验证 |
| D06 | 异常验收自动开维护及恢复 | test_damaged_return_automatically_blocks_asset_until_maintenance_finishes | 通过：damaged关联维护阻断预约，完成维护后可再申请；有其他未来申请时仍自动维护的分支代码审查 |
| D07 | 并发开始同设备维护 | test_concurrent_maintenance_starts_serialize | 通过：真实多连接仅一笔成功、一条开放记录 |
| D08 | 非破坏12表→16表迁移 | test_v1_migration_preserves_all_existing_data_and_backup、test_empty_v1_fixture_migration_does_not_touch_other_database | 通过：备份旧库、保留ID/授权/会话/审计、旧缺项NULL/unknown、重复启动不重复迁移、不触碰其他文件 |
| D09 | 新事件统一授权与submit | T test_new_events_all_require_equipment_update_and_log_denial[...]；U第26—28步、13-readonly-equipment.png、14-audit-denied.png | 新事件403/审计API通过；只读界面、直调维护403及15绑定浏览器通过；全部submit匹配DOM经代码审查 |
