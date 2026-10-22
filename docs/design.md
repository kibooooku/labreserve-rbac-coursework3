# LabReserve 系统设计

LabReserve 管理实验室设备的预约、审批、实物借还、验收和维护，并用数据库中的角色许可控制共享页面和业务动作。本文对应数据库版本 2：16 张表、15 项固定事件绑定。字段和约束的完整清单见 [database-schema.md](database-schema.md)，请求与响应见 [api-contract.md](api-contract.md)。

## 1. 业务范围与分层

一条主要链路是申请人选择设备并预约，教师批准或驳回，设备管理员登记借出与归还，异常验收转入维护，维护完成后恢复可用条件。实验室和分类是独立主数据，设备每一行代表一台实物；同型号可以有多台实物，code 为各台独立资产编号。

| 层次 | 实际职责 | 边界 |
| --- | --- | --- |
| 共享界面 | 根据页面、菜单及业务许可呈现功能，监听点击与提交，显示审批、借还和维护记录 | 不决定最终授权，不接收客户端自报的角色特权 |
| HTTP/会话 | 统一 JSON、Cookie 身份、CSRF、同源检查和安全响应头 | 会话只确定身份，没有自选激活角色状态 |
| 固定事件入口 | source_id 解析为 event_type、object_code、operation_code、handler；统一鉴权与审计 | 客户端不能通过 payload 替换绑定或指定任意函数 |
| RBAC 服务 | 从 user_roles、role_permissions 实时求全部已分配角色的许可并集 | 不理解时段、维护、归属或审批记录的业务含义 |
| 业务服务 | 校验主数据、记录归属、状态、时段、实物占用、审批和维护规则 | 通过统一授权后才执行；业务限制不会自动成为新角色 |
| SQLite | 外键、复合主键、唯一键、检查约束、事务和部分唯一索引 | 本地单数据库写入序列化，不是分布式库存锁 |

实验室 manager_id 仅表示业务负责人，不会自动赋予管理员角色，也不会形成按实验室隔离的数据授权。设备分类与实验室可独立停用；有有效预约或未归还借用时拒绝停用相关主数据，保留历史关联。

## 2. 16 表关系

| 分组 | 表 | 关系与键 |
| --- | --- | --- |
| 授权 | users | 用户身份，username 唯一，密码仅保存散列 |
| 授权 | roles | 角色，code 唯一 |
| 授权 | user_roles | PK(user_id,role_id)，两个外键；用户与角色多对多 |
| 授权 | operations | 操作词汇，code 唯一 |
| 授权 | control_objects | 受控对象，code 唯一，kind 为 page/menu/business |
| 授权 | permissions | PK(operation_id,object_id)，限定支持的操作与对象组合 |
| 授权 | role_permissions | PK(role_id,operation_id,object_id)，后两列复合外键引用 permissions |
| 技术 | sessions | token_hash 主键，user_id 外键，CSRF 与到期时间；不保存原始会话令牌 |
| 技术 | event_audit | actor_id 外键，保存事件绑定、目标、结果和时间 |
| 业务 | laboratories | 实验室 code 唯一，manager_id 可空并引用 users，active 表示启停 |
| 业务 | equipment_categories | 分类 code/name 分别唯一，active 表示启停 |
| 业务 | equipment | 资产 code 唯一；model、分类/实验室外键、架位、生命周期、创建人及创建/更新时间 |
| 业务 | reservations | 设备、申请人、时段、用途、流程状态、创建/更新时间、取消人和取消时间 |
| 业务 | reservation_reviews | reservation_id 唯一外键；审批人、决定、意见与时间；每份申请一次最终决定 |
| 业务 | loans | reservation_id 唯一外键；借出/归还经办人、独立检查说明、时间和验收结果 |
| 业务 | equipment_maintenance | 设备外键、可空且唯一的 loan_id、开始/结束经办人与时间、原因和结果；每台设备最多一条开放维护 |

许可不使用独立 permission_id。操作与对象组合本身唯一标识一项许可，角色许可表直接引用这一组合，避免许可重复和不存在的许可关联。user_roles 的联合主键表示一个用户不会重复获得同一角色；role_permissions 的三列主键表示同一角色不会重复获得同一许可。

预约与审批记录拆分，使审批意见不会混入申请字段；取消已批准但尚未借出的预约时保留原审批记录。借还记录分别保存 checkout_condition 和 return_condition，后者不会覆盖前者。验收异常关联维护记录，能够从一次归还追溯该实物的维护原因；普通手动维护的 loan_id 为空。

## 3. 授权与会话

若 R(u) 是用户已分配角色集合，P(r) 是角色许可集合，则 E(u)=⋃r∈R(u)P(r)。对对象 o 和操作 a，只有(a,o)属于 E(u) 才通过 RBAC 检查。每次受控变更在 BEGIN IMMEDIATE 之后重查许可，使授权更改与业务提交按写事务顺序执行。管理员拥有显式授予的许可，不按角色名绕过鉴权。

| 业务许可 | 学生 | 教师 | 设备管理员 | 审计员 | 系统管理员 | 学生兼教师 |
| --- | --- | --- | --- | --- | --- | --- |
| equipment:view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| equipment:update | — | — | ✓ | — | ✓ | — |
| reservation:view/create/cancel | ✓ | ✓ | ✓ | 仅 view | ✓ | ✓ |
| reservation:approve/reject | — | ✓ | — | — | ✓ | ✓ |
| reservation:manage | — | — | — | — | ✓ | — |
| reservation:export | — | — | — | ✓ | ✓ | — |
| loan:view | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| loan:checkout/return | — | — | ✓ | — | ✓ | — |
| rbac:view | — | — | — | ✓ | ✓ | — |
| rbac:manage | — | — | — | — | ✓ | — |
| audit:view | — | — | — | ✓ | ✓ | — |

以上是种子授权；管理员保存矩阵后以数据库实际记录为准。实验室、分类和维护事件在当前粒度下共同使用 equipment:update，并没有各自独立的许可对象。不同 source_id 可以共享一个许可对，但每个 source_id 的绑定唯一且固定。

权限矩阵只允许编辑 permissions 中存在的格子。保存前验证所有许可，随后在同一事务替换目标角色集合。用户角色分配同样整体校验并替换。admin 的 rbac:view、rbac:manage、page.rbac:view、menu.rbac:view 受到防失联保护，并至少保留一个有效管理员账号；这些规则保护管理入口，不是全能旁路。

登录会话保存随机令牌的 SHA-256 摘要、用户、CSRF 和到期时间，默认有效期 12 小时。重新登录轮换会话，注销删除服务端会话。当前没有 session_roles、角色激活/停用接口或会话内角色子集，每次使用全部已分配角色。多角色并集、即时撤权、角色继承和 DSD 是不同机制。

## 4. 页面、菜单与动作

| 层次 | 对象与许可示例 | 用途 | 服务端检查 |
| --- | --- | --- | --- |
| 页面 | page.reservations:view | 是否进入共享预约区域 | 预约列表同时要求页面许可和 reservation:view |
| 菜单 | menu.reservations:view | 是否展示导航入口 | 不以隐藏菜单替代接口授权 |
| 动作 | reservation:approve | 是否呈现审批动作 | 事件每次校验业务许可，随后验证具体记录 |

三类许可独立保存。只有页面查看许可不能推导出审批权；隐藏菜单不会自动删除业务许可。按钮还受记录状态与归属影响。普通申请人只读取本人预约和借还；拥有审批、借还管理、reservation:manage 或审计能力的用户可按职责读取全量记录。查询与导出复用相同范围函数。

角色授权是动作的必要条件，业务条件继续收窄访问：即使拥有批准许可，也不能审批自己的预约；即使拥有取消许可，也不能取消他人记录，除非另有 reservation:manage；即使拥有借出许可，也不能对同一预约重复借出。

## 5. 15 项固定事件

前端按钮 click 只打开确认或检查表单，最终由表单 submit 监听器把动作组织为 {source_id,payload}，服务端按下表解析后执行。15 项固定绑定的 event_type 均为 submit。payload 中的 object、operation、handler、user_id 或状态字段不能替代固定绑定及当前身份。注册表本身不是可由客户端写入的业务配置。

| source_id | event_type | 对象:操作 | handler | 主要写入表 |
| --- | --- | --- | --- | --- |
| equipment.save | submit | equipment:update | save_equipment | equipment；兼容维护输入时也可写 equipment_maintenance |
| laboratory.save | submit | equipment:update | save_laboratory | laboratories |
| laboratory.set_active | submit | equipment:update | set_laboratory_active | laboratories |
| category.save | submit | equipment:update | save_category | equipment_categories |
| category.set_active | submit | equipment:update | set_category_active | equipment_categories |
| maintenance.start | submit | equipment:update | start_maintenance | equipment_maintenance |
| maintenance.end | submit | equipment:update | end_maintenance | equipment_maintenance |
| reservation.submit | submit | reservation:create | submit_reservation | reservations |
| reservation.approve | submit | reservation:approve | approve_reservation | reservation_reviews、reservations |
| reservation.reject | submit | reservation:reject | reject_reservation | reservation_reviews、reservations |
| reservation.cancel | submit | reservation:cancel | cancel_reservation | reservations |
| loan.checkout | submit | loan:checkout | checkout_loan | loans |
| loan.return | submit | loan:return | return_loan | loans；damaged 时关联 equipment_maintenance |
| rbac.save_permissions | submit | rbac:manage | save_role_permissions | role_permissions |
| rbac.assign_roles | submit | rbac:manage | assign_roles | user_roles |

每次成功受控变更还写 event_audit。流程为身份与 CSRF → 固定绑定 → BEGIN IMMEDIATE → 当前许可 → 处理器业务校验/写入 → 成功审计 → COMMIT。领域错误回滚后单独保留 denied 或 invalid 审计；成功审计写入失败时也不提交业务修改。未登录 401、缺许可/自审/归属 403、输入错误 400、记录不存在 404、业务冲突 409；未知内部错误返回不含堆栈的 JSON 500。

审计目标随事件语义确定：设备/实验室/分类保存对应各自记录；维护事件对应维护记录；预约事件对应预约；借还事件对应借还；授权变更对应角色或用户。object_code 是抽象授权对象，不代表 target_id 总是某一张表的同一类型主键。失败时仅能使用已取得且类型合法的目标编号，不伪造操作者或历史。

## 6. 存储状态、展示状态与维护

### 6.1 预约审批与借还分离

reservations.status 只存 pending、approved、rejected、cancelled。pending 可批准或驳回，pending/approved 在未生成借还记录时可取消。批准/驳回必须由他人处理，reservation_reviews.reservation_id 唯一；当前不支持同一申请多轮决定或会签。

loans 不存重复的状态列。不存在借还记录时，预约列表显示原流程状态；存在且 returned_at 为空时显示 borrowed；returned_at 非空时显示 returned。API 同时返回 workflow_status，保留预约表的原状态。借出和归还不会把 reservations.status 改成 borrowed/returned，也不会删除原批准记录。

| 事件 | 存储变化 | 展示结果与约束 |
| --- | --- | --- |
| 提交 | 插入 pending 预约 | 合法未来半开区间，无占用冲突，设备有效可用 |
| 批准/驳回 | 插入审批记录，更新预约为 approved/rejected | 不能自审；驳回理由必填；批准重新检查设备、过期与冲突 |
| 取消 | 更新为 cancelled，写 cancelled_at/cancelled_by | 本人或 manage；尚无任何借还记录 |
| 借出 | 插入 loans，记录 checkout_by/at/condition | 原预约仍 approved；列表投影 borrowed；必须 now < end_at；允许提前借出 |
| 正常归还 | 写 returned_by/at、return_condition、passed | 列表投影 returned，借出检查仍保留 |
| 异常归还 | 写 damaged 并自动建立关联开放维护 | 列表投影 returned；设备的维护状态由维护记录产生 |

### 6.2 设备可用性与生命周期

设备表只存 lifecycle_status：active、disabled、retired。retired 不可恢复为 active/disabled，替换实物应建立新的独立资产编号。停用或报废有有效预约/未归还设备时拒绝。

查询状态按优先级推导：生命周期非 active 时返回其值；分类或实验室停用时返回 disabled；有 end_at 为空的维护记录时返回 maintenance；否则为 available。available 表示未受这些可用性条件限制，不意味着当前一定没有未归还借用；预约时段与实物借出占用仍分别检查。

手动 maintenance.start 只对 available 且没有有效预约或未归还借用的设备开放，原因必填；部分唯一索引阻止同一实物同时存在两条开放维护。maintenance.end 要求维护未结束且结果非空，只填结束人/时间/结果，不顺带启用已停用的实验室、分类或已报废设备。

归还验收 damaged 时自动创建关联维护，安全处置优先，不因其他未来预约而跳过维护。这些未来申请仍保留历史，但维护结束前不能批准或借出。它与手动维护的冲突检查是不同业务路径，不能把两者概括成同一前置条件。

## 7. 事务、冲突与迁移

每个连接启用外键和 10 秒 busy_timeout。竞争写入在 BEGIN IMMEDIATE 之后校验，防止两个请求同时通过检查再写入。预约区间为 [start_at,end_at)，冲突条件是 existing.start < requested.end 且 existing.end > requested.start。pending/approved 占用中，已关联归还完成的记录被排除；拒绝和取消不占用。相邻区间可以衔接，实物未归还仍会阻止另一预约借出。

数据库以唯一约束保护一申请一审批、一申请一借还、一异常借还最多一关联维护，以部分唯一索引保护一设备一开放维护。应用继续校验决定、归属和时间，不能把数据库字段约束当成完整业务许可。

版本 2 启动检测旧设备表缺少 lifecycle_status 时执行非破坏迁移：先用 SQLite backup API 保存旧库快照，再在事务内重建旧设备、预约、借还相关结构，保留原主键、授权、会话和审计；外键核验成功后提交。旧分类与位置转成主数据关联。原来没有的审批时间、经办人保持 NULL；旧已归还说明迁入归还检查，不捏造借出检查；旧维护标记的时间明确为迁移登记时间。失败则回滚，保留备份，不要求用户先清空数据。

日期采用 Asia/Shanghai 本地 ISO 时间，预约输入精确到分钟，拒绝时区后缀、非零秒、非法日期、过去时间及结束不晚于开始。CSV 使用 UTF-8 BOM 和公式起始字符转义。页面用户内容经 h() 转义或 textContent 输出；专项验证范围与一般代码审查分开记录。

## 8. 模型定位与验证边界

当前实现是平面用户多角色许可并集，叠加业务记录和管理完整性约束。没有角色层次表、继承闭包、自选会话激活集合、正式互斥角色集合或阈值，因此不宣称实现角色继承、SSD/DSD 或 RBAC3。禁止自审比较操作者与某一预约申请人，允许同一人同时拥有学生与教师身份；它不是禁止角色并存。

RBAC0/1/2/3 的结构分类见 [Sandhu等原论文](https://csrc.nist.gov/CSRC/media/Projects/Role-Based-Access-Control/documents/sandhu96.pdf)；会话激活与 SSD/DSD 组件见 [NIST统一模型论文](https://csrc.nist.gov/pubs/journal/2001/08/proposed-nist-standard-for-rolebased-access-contro/final)；记录关系约束可以叠加在角色条件之后，见 [NIST FAQ](https://csrc.nist.gov/Projects/Role-Based-Access-Control/faqs)。这些概念用于解释实现，不构成标准符合性认证。

验证使用隔离数据库及真实浏览器流程；字段/关系图是设计图，界面截图来自运行记录，两者不互相替代。自动化、浏览器、代码审查和未专项验证的范围见 acceptance.md。当前系统是本机单数据库应用，未声称完成多实例协调、生产安全审计、压力认证或外部身份系统集成。
