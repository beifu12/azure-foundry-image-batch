# 环境、登录与运行问题

## 先运行诊断

```powershell
# 只查本地环境，不登录、不访问 Azure。
.\.venv\Scripts\python -X utf8 image_batch.py doctor --offline

# 有配置并完成客户登录后：只读验证登录和订阅可见范围。
.\.venv\Scripts\python -X utf8 image_batch.py doctor --config config.json

# 应用方式无需 CLI。
.\.venv\Scripts\python -X utf8 image_batch.py doctor --auth app --config config.json --credentials output/app-01.private.json
```

诊断不会安装软件、自动登录、弹出授权、生成 Secret 或修改 Azure。`--offline` 通过只代表本地依赖就绪；在线诊断通过只代表令牌及订阅读取有效，不证明创建/角色分配/Key 权限。

## 常见问题及处理

| 现象 | 原因/处理 |
| --- | --- |
| `python` 找不到或打开 Microsoft Store | 安装 Python 3.10+，Windows 可先用 `py -3 --version` 检查；重新打开终端 |
| `No module named azure` / `requests` | 使用同一个虚拟环境的 Python 执行 `-m pip install -r requirements.txt`，不要把包安装到另一个 Python |
| `az` 不存在 | 管理员方式按官方说明安装 Azure CLI 后重新打开终端；应用方式不需要它；pip 不会安装 Azure CLI |
| 网页已登录，但脚本未登录 | 在脚本所在的相同电脑/终端/WSL/容器环境完成 CLI 登录；不要复制 Azure 登录缓存或 Token |
| CLI 选择了其他云 | 只有明确使用 Azure 公有云才运行 `az cloud set --name AzureCloud`，然后登录客户资源租户；脚本不支持世纪互联云 |
| MFA 或条件访问提示 | 客户本人完成；无浏览器时可按组织策略使用 `az login --tenant ... --use-device-code`，不以用户名/密码自动登录 |
| 应用没有可见订阅 | 核对应用租户及目标订阅 RBAC；目录内创建了应用不等于已经授权订阅。新角色可能延迟生效 |
| `setup-app` Graph 403 | 管理员的 Entra 应用管理权限不足，或客户限制了 Azure CLI 的 Graph 委托访问；由租户管理员处理，不自动授予 Graph 应用权限 |
| 角色分配 403 | 仅 Contributor 通常不能给其他身份授权；管理员需要订阅 Owner 或适当的 RBAC 管理权限，不自动提升为 Owner |
| 账户/部署创建 403 | 订阅可见不代表拥有写权限；还可能有 Azure Policy、资源锁、网络或模型限制，诊断通过不能绕过这些限制 |
| Microsoft.CognitiveServices 未注册 | 管理员先在 Portal 检查提供程序状态；获准后显式注册，再重扫。脚本不盲目注册提供程序 |
| `blocked` 且 quota_scope=unknown | 客户未确认配额范围；保持只读，查实后修改配置并生成新清单 |
| 区域/版本没有容量 | 查看最新模型目录、SKU、地区及该订阅配额；不自动换另一个模型或批准范围外的区域 |
| 区域多个现有 Foundry | 让客户明确需要复用的账户命名；不随机挑选，不另外创建来回避问题 |
| 配额/状态变化，清单不一致 | 重新扫描到新文件，确认新清单；不要直接改 plan.json 的资源 ID 或容量 |
| 名称已存在、HTTP 409/412 | 核对是谁已经创建了资源以及实际状态，重扫；不覆盖或删除现有资源 |
| 超时、连接断开、中断 | Azure 可能继续执行已接收请求；用 Portal 与只读重扫确认，不自动重放创建/密钥请求 |
| Key 读取失败或 disableLocalAuth=true | 不启用本地认证、不重新生成 Key；客户按既有认证策略处理。已创建部署仍保留在普通结果中 |
| 文件已存在 | 选择新的 plan/result/private 文件名，避免覆盖已确认清单和一次性密钥值 |
| 应用凭据文件是 `{}` | 初始化可能在密钥创建前中断；根据普通记录核对已有应用/SP/密码，再决定补齐。不要删文件后重复整个创建流程 |
| `rpm: null` | Azure 未返回可识别 RPM；只保留原始 rate_limits，不能按 Tier 表假装实际 RPM |

## 网络与代理

客户环境需要能访问 Python 包源、Microsoft 登录、Azure ARM；初始化应用还需 Microsoft Graph。管理员登录也可能访问系统浏览器与组织身份服务。TLS 检查/代理由客户按组织规范配置，不关闭证书验证，不把 Secret/Token 放入代理排障日志。

排障只发送命令名称、脱敏 HTTP 状态/错误码及步骤说明。不要上传 `.private.json`、真实 config/plan/result、浏览器带 Token 的地址或完整 SDK 调试日志到公共 Issue。

## 权限与范围

新建资源默认使用 Azure 配置；此版不替客户建立私有端点、防火墙或网络路由。不支持覆盖已有部署、跨机器并发互斥、自动提额或模型切换。多订阅失败会逐项记录，修复后重新扫描，再执行客户确认的剩余项。

## 官方安装与登录文档

- [Azure CLI 安装](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- [交互登录与 MFA](https://learn.microsoft.com/en-us/cli/azure/authenticate-azure-cli-interactively)
- [Python 应用身份认证](https://learn.microsoft.com/en-us/azure/developer/python/sdk/authentication/local-development-service-principal)
