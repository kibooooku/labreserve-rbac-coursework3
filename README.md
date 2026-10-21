# LabReserve 实验室设备预约与借用系统

系统分析与设计第三次作业。使用 Flask、SQLite 和原生 JavaScript 实现数据库驱动的细粒度 RBAC，并将按钮监听、事件派发、权限校验与业务响应串联。

## 快速运行

需要 Python 3.11 或以上。Windows PowerShell 在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

访问 http://127.0.0.1:8783 。首次运行自动创建 SQLite 数据库和演示数据，后续启动保留数据。默认仅监听本机。不要将教学演示账号直接用于公网部署。

Windows也可双击 `启动系统.cmd`。若需重建演示数据，请明确执行 `python run.py --reset`；该操作会清空当前演示库。

## 演示账号

统一密码 `Lab@2026!`。

| 账号 | 角色 | 主要操作 |
|---|---|---|
| student | 学生 | 查看设备、预约、取消自己的预约 |
| teacher | 指导教师 | 审批或拒绝预约，不能审批本人申请 |
| keeper | 设备管理员 | 维护设备、办理领用和归还 |
| admin | 系统管理员 | 权限矩阵、用户角色分配及明确授予的业务权限 |
| auditor | 审计员 | 只读审计与事件追踪 |
| multi | 学生与教师 | 演示多角色权限并集及禁止自审 |

## 建议演示顺序

1. student 登录，选择可用设备，填写未来时间与用途提交预约。
2. teacher 登录，在同一预约页面审批申请。
3. keeper 登录，在同一预约页面办理领用，在借还页面办理归还。
4. admin 登录，在权限矩阵撤销教师某个操作；教师已登录会话下一次请求即受新权限约束。
5. auditor 登录，查看事件源、事件类型、操作、控制对象、执行结果和审计记录。
6. multi 提交申请后尝试审批本人申请，观察业务规则拒绝；这条规则独立于RBAC许可。

## 设计重点

- 七表核心：users、roles、user_roles、operations、control_objects、permissions、role_permissions。
- permissions 联合主键为操作与控制对象；用户可分配多个角色，权限取并集。
- 页面、菜单与业务按钮分别表达权限；后端在执行前从数据库重新读取权限。
- 前端监听器统一派发事件，后端固定注册表将事件源映射为操作和对象，禁止客户端自报权限绕过检查。
- 预约冲突、设备状态、所有权和禁止自审放在业务层；通用RBAC层不理解预约含义。
- 数据库事务保护预约时段与借还状态，接受、拒绝和输入错误均有事件审计。

详细设计和接口约定见 `docs/`；自动化测试在 `tests/`；实际验证证据在 `evidence/`。验证依赖和命令：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/browser_check.py
```

浏览器验收脚本使用本机已安装的 Microsoft Edge，启动临时本地服务和临时数据库，不更改演示库。未安装Edge时可先运行API测试。该项目为本机教学演示，包含独立账号的真实会话和数据持久化；不包含学校统一身份认证、硬件门禁或短信通知。

## 验证结果

2026-10-22最终验证：68项唯一自动化用例通过，0失败（全量67项加独立持久化1项）；真实Edge浏览器24步骤通过。依据为evidence/pytest-results.xml、pytest-persistence.xml与browser/result.json。

教学演示允许提前领用，但当前时刻达到或超过预约结束即拒绝。实物未归还时不能再次领用。

实验报告位于reports/，设计图位于docs/figures/。
