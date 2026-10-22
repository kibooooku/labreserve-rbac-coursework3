# LabReserve 实验室设备预约与借还系统

LabReserve 使用 Flask、SQLite 和原生 JavaScript，将设备实物、实验室、设备分类、预约审批、借还验收、维护记录和细粒度 RBAC 连接为可运行的本地应用。

公开仓库：[kibooooku/labreserve-rbac-coursework3](https://github.com/kibooooku/labreserve-rbac-coursework3)。

## 启动

需要 Python 3.11 或以上。Windows 可直接双击项目根目录的 `启动系统.cmd`；也可在 CMD 中进入项目目录后执行：

```cmd
启动系统.cmd
```

启动器会检测 Python、建立或检查 `.venv`、安装缺少的项目依赖并启动服务。命令窗口会显示启动结果，保持窗口打开即可使用，按 Ctrl+C 停止。

手动启动时在 PowerShell 执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

打开 [本机应用](http://127.0.0.1:8783)。首次启动建立数据库和演示数据，后续启动保留现有记录；从旧版数据库启动时会自动备份并迁移到版本 2 的 16 表结构。迁移备份保存在数据库旁的 `backups/`，原来没有记录的审批时间、经办人等保持空值，不补造历史。

需要主动清空当前数据并重建演示记录时执行 `.\.venv\Scripts\python.exe run.py --reset`。常规启动无需此参数。

## 账号与角色

演示账号统一密码为 `Lab@2026!`。

| 账号 | 角色 | 主要能力 |
| --- | --- | --- |
| student | 学生 | 查看设备、申请预约、取消本人尚未借出的预约 |
| teacher | 指导教师 | 申请预约、批准或驳回他人申请，不能自审 |
| keeper | 设备管理员 | 维护资产、实验室和分类，登记借出、归还及维护 |
| admin | 系统管理员 | 配置角色许可、分配用户角色，以及显式授予的业务操作 |
| auditor | 审计员 | 查看业务、权限矩阵和事件审计，导出预约；不能修改授权或业务 |
| multi | 学生与教师 | 同时拥有两角色许可，可申请和审批他人记录，仍不能自审 |

## 主要流程

1. 学生从可用设备中选择一台实物，提交未来时间和用途。相同型号的不同资产使用不同编号，可分别预约。
2. 教师在共享预约页面批准或驳回申请。审批结果、审批人、意见和时间保存为独立审批记录。
3. 设备管理员办理借出，记录经办人和借出检查；归还时分别记录验收说明与 `passed`/`damaged` 结果。
4. 验收异常会在同一事务中建立关联维护，设备立即不可预约或借出。完成维护需填写结果，历史借出检查不会被归还说明覆盖。
5. 设备页还可维护实验室、负责人、设备分类和启停状态。有效预约或未归还借用会阻止手工维护、相关主数据停用和设备停用/报废。
6. 管理员在矩阵中改变许可或用户角色，旧登录会话的下一次请求立即采用新授权。审计员可查看 15 项固定事件绑定与允许、拒绝、校验失败记录。

系统允许在预约开始前提前借出，但当前时间必须严格早于预约结束；同一台实物未归还时，即使另一次预约时段不同，也不能再次借出。

## 数据与授权设计

数据库版本 2 共 16 张表：

| 分组 | 表 |
| --- | --- |
| RBAC 核心 7 表 | users、roles、user_roles、operations、control_objects、permissions、role_permissions |
| 会话与审计 2 表 | sessions、event_audit |
| 业务 7 表 | laboratories、equipment_categories、equipment、reservations、reservation_reviews、loans、equipment_maintenance |

- 许可由“操作 × 控制对象”标识，采用联合主键；用户可以拥有多个角色，有效许可为全部已分配角色的并集。
- 页面、菜单和业务动作分别授权，界面隐藏按钮之外，服务端每次执行事件都重新检查数据库许可。
- 登录会话负责身份、到期和 CSRF，不提供会话自选角色子集；本系统未实现角色继承、正式 SSD/DSD 或 RBAC3。
- 服务端固定注册表把 source_id 解析为事件类型、对象、操作和处理器，不信任客户端自报权限或处理器。
- 预约流程、借还状态和设备可用性分别存储或推导：借还不把预约工作流覆写为另一套状态，维护由开放维护记录表达。
- `BEGIN IMMEDIATE`、外键、联合主键和部分唯一索引保护业务更新；失败回滚后保留审计。

[详细设计](docs/design.md)、[全字段与关系](docs/database-schema.md)、[API 契约](docs/api-contract.md)、[验收映射](docs/acceptance.md)位于 `docs/`。报告位于 `reports/`，图示位于 `docs/figures/`。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/browser_check.py
```

数据库版本 2 的最终验证：后端 85 项自动化通过，0 失败/错误；真实 Edge 浏览器 34 步通过，无 JavaScript 异常和非预期 HTTP 错误。持久化用例已包含在 85 项内，单独持久化 XML 不重复计数。

自动化测试和浏览器脚本使用隔离数据库。浏览器验收使用本机 Microsoft Edge；结果、JUnit XML、截图与下载证据保存在 `evidence/`。验证结论应与当前代码及数据库版本对应，具体覆盖范围见验收映射，不把历史版本的测试数量等同于新增功能已验证。

应用默认只监听 127.0.0.1，适用于本机演示；未集成学校统一认证、门禁硬件、短信、分布式库存或多机构租户隔离。
