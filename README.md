# Azure Foundry 模型部署工具

## 客户网页与容器

客户不熟悉脚本时，推荐使用独立的浏览器工作台。手动登录客户 Azure 账号，勾选订阅和模型，填写命名规则，检查后按按钮创建缺失项；无需安装 Azure CLI，也无需玖云 M365 账号。

支持三个生图模型和七个文本模型的选择。模型是否可部署，以该订阅 Azure 实际目录、默认版本、配额和区域容量为准，不保证列出的模型在每个客户租户均已开放。

网页默认使用 Azure 返回的默认版本；高级设置仍可以指定精确版本。新部署采用检查时确认的版本，不自动升级现有部署。`gpt-image-2` 候选区域限定为 East US 2、West US 3、Poland Central、Sweden Central、UAE North；其余模型独立查询各自区域。

容器启动、Azure Container App 部署、登录策略、Tier 1 目标和客户 Excel 格式见 [客户网页使用说明](docs/WEB_GUIDE.md)。生图新部署目标为 2 RPM，所有文本新部署目标为 1,000,000 TPM；以实际可用额度和 Azure 容量换算为准，不自动修改已有部署。下文保留原有脚本方式，脚本仍要求明确填写版本。

公共仓库：[beifu12/azure-foundry-image-batch](https://github.com/beifu12/azure-foundry-image-batch)。客户可以点击 **Code → Download ZIP**，或在 [发布页面](https://github.com/beifu12/azure-foundry-image-batch/releases/latest) 下载完整脚本包。

发布包内的目录及文件名全部使用 ASCII 英文，解压后的固定目录为 `azure-foundry-image-batch`；中文说明仍保留在文件内容中，避免部分 Linux 解压工具将中文目录名解错。

Ubuntu 下载入口（在当前目录没有同名解压目录时使用）：

```bash
curl -fL https://github.com/beifu12/azure-foundry-image-batch/releases/download/v1.2.0/azure-foundry-image-batch.zip -o image-batch-v1.2.0.zip
unzip image-batch-v1.2.0.zip
cd azure-foundry-image-batch
```

旧版解出的乱码目录可以暂时保留，不影响进入新版英文目录。

在客户自己的电脑或 Cloud Shell 中运行。支持 Azure 公有云；不需要登录玖云 Dashboard，也不把客户凭据上传到玖云。

客户直接使用请按本文运行；交给自己的 Agent 时，先让它阅读 [Agent 操作指南](docs/AGENT_GUIDE.md) 和 [AGENTS.md](AGENTS.md)。环境、登录及常见失败见 [排障说明](docs/TROUBLESHOOTING.md)。

可以使用管理员账号直接部署，也可以由管理员先初始化应用并配置各订阅 Contributor，然后使用应用身份部署。默认只扫描，创建必须额外指定 `--execute`。请先在一个测试订阅验收，再扩大范围。

## 能做什么

- 扫描指定租户下当前身份可访问、状态为 Enabled 的订阅；默认全选。不可访问的订阅不在扫描范围，不能承诺枚举租户全部订阅。
- 查询 Foundry/Azure OpenAI 账户、现有部署、模型版本、可用区域和容量。某个账户部署列表读取失败时，不把它当作空账户；该订阅记录失败。
- 同订阅、同区域已有同模型、同部署类型时跳过，即使版本或命名不同也不会再创建。不升级、不扩容、不更换现有部署。失败或尚在创建的部署列为阻塞，须先检查处理。
- 命名由客户配置；区域已有一个可复用账户时使用它，已有多个时要求客户明确命名，不随机选取。
- 在生图 2 RPM／文本 1,000,000 TPM 目标内，从真实剩余配额、SKU 约束和平台可用容量计算合法分配。余额不足时可能低于目标；区域独立额度各区分别分配，共享额度在同一个池内分配，不重复乘以区域数量。
- 执行前重新扫描，与已确认清单比较。状态或配额改变时要求重扫；长时间创建账户后再次检查额度。
- 每个订阅/区域单独记录结果，失败后继续后续项。结果逐项保存；中断后重新扫描确认，不盲目重试写入。
- 返回 Azure 实际 Endpoint、部署名称、容量、实际 RPM 和原始限流字段。Key 需要显式选择，单独写入私密文件，不写普通结果或日志，也不重置已有 Key。

## 先确认配额规则

不要默认认为“五区域 × 每区 2 RPM = 10 RPM”。微软已开始引入订阅级共享配额，各模型处于逐步切换中；同模型版本的 Global Standard 可能跨区域共享，Data Zone Standard 可能按数据区共享。配置必须按客户租户当前实际配额确认。

当前官方 Tier 1 参考表中，`gpt-image-2` 的 DataZoneStandard 为 2 RPM、GlobalStandard 为 6 RPM；`gpt-image-2.5-flare` 和 `gpt-image-2.5-sunburst` GlobalStandard 均为 5 RPM。表格是参考，不代替订阅实时配额，也不保证所有区域均能部署。

`quota_scope` 可选值：

| 值 | 含义 |
| --- | --- |
| `unknown` | 默认：仅扫描，全部新部署阻塞，不猜测配额范围 |
| `regional` | 客户已确认此模型/类型仍是每区域独立配额，各区用满可分配额度 |
| `subscription` | GlobalStandard 跨区域共享，同一订阅的总分配不超过保守剩余额度 |
| `data-zone` | DataZoneStandard 按数据区共享，同时需填写 `data_zones` 区域映射 |

例如数据区映射 `"data_zones": {"eastus2": "US", "swedencentral": "EU"}`。只需配置实际选择的区域；区域所属数据区须由客户确认。不要为了提高显示的总 RPM 把共享额度改成 `regional`。

脚本不固定写死五个区域；`regions: "auto"` 使用 Model Capacities 接口实际返回的区域，再核对模型目录。扫描之后应检查区域清单及数据处理范围，必要时把 `regions` 改为客户批准的区域列表，再重新扫描。

## 安装

准备 Python 3.10 或更新版本。管理员方式还需安装并登录微软 Azure CLI。以下为 Windows PowerShell 示例；Cloud Shell 可把虚拟环境 Python 路径改为 `.venv/bin/python`。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
```

可以先运行无云端写入的自检测试：`.\.venv\Scripts\python -X utf8 self_test.py`。测试使用模拟响应，不需要登录或提供账号。

**Python 依赖不会安装 Azure CLI。** 管理员方式需另外按 [微软官方说明](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) 安装 CLI，安装后重新打开终端，确认 `az version` 可运行。应用部署方式无需 Azure CLI；只有管理员初始化应用/角色时需要它。

```powershell
# 首先只检查本地环境，不登录、不访问 Azure。
.\.venv\Scripts\python -X utf8 image_batch.py doctor --offline

# 使用应用身份时：缺少 CLI 不会阻止这个本地检查。
.\.venv\Scripts\python -X utf8 image_batch.py doctor --offline --auth app
```

Linux/macOS/Cloud Shell 的创建环境命令同样是 `python -m venv .venv`，之后把本文 `.\.venv\Scripts\python` 替换为 `.venv/bin/python`。脚本只调用 Python 与（管理员方式下的）Azure CLI，不需要安装 Azure CLI 的 Foundry 扩展。

编辑 `config.json`：

1. 把 `tenant_id` 替换为客户的目录（租户）ID。
2. 默认 `subscription_ids: "all"`。试运行建议改为 `["客户测试订阅ID"]`。

   单个订阅也必须使用列表，例如 `"subscription_ids": ["11111111-1111-4111-8111-111111111111"]`，不能直接填写订阅 ID 字符串。示例 UUID 需要替换为客户的真实订阅 ID。
3. 选择模型、版本和部署类型；不是只有一个笼统的 image-2.5。
4. 确认资源组、账户及部署命名规则。
5. 先使用 `quota_scope: "unknown"` 扫描，核对实际配额范围后修改并重扫。

模型示例：

| model | model_version 示例 |
| --- | --- |
| `gpt-image-2` | `2026-04-21` |
| `gpt-image-2.5-flare` | `2026-09-08` |
| `gpt-image-2.5-sunburst` | 请填写该订阅模型目录中显示的精确版本，不自动猜测 |

版本和区域以扫描时 Azure API 为准。脚本不自动切换模型、不自动升级版本。

命名模板支持 `{sub8}`（订阅 ID 前八位）、`{subscription}`（完整订阅 ID）、`{region}`、`{subcode}`（订阅名中的 A03 等编号，无编号时用 sub8）、`{index:03d}`（区域编号）。建议加入客户独有前缀。网页为同一订阅的所有已选模型统一编号；脚本单次扫描按区域顺序编号。

## 方式一：管理员直接部署

“admin”只是登录方式，不代表账号天然有权限。账号至少需要目标订阅 Contributor（或等效自定义权限），并满足组织策略与模型使用限制。

```powershell
az cloud set --name AzureCloud
az login --tenant "客户租户ID" --allow-no-subscriptions

# 在相同终端只读检查登录及所选订阅范围。
.\.venv\Scripts\python -X utf8 image_batch.py doctor --config config.json

# 只读扫描，首次扫描可保持 quota_scope=unknown。
.\.venv\Scripts\python -X utf8 image_batch.py scan --config config.json --plan output/plan-01.json
```

查看清单 `rows`、`errors`。`planned` 表示准备创建；`existing` 表示已有部署；`blocked` 表示无法确认或额度不足。确认区域、命名、配额范围和全部创建项后，再执行：

```powershell
.\.venv\Scripts\python -X utf8 image_batch.py deploy --config config.json --plan output/plan-01.json --execute --output output/result-01.json --include-keys --secret-output output/keys-01.private.json
```

如果修改了配置、配额或资源，请生成新清单，例如 `--plan output/plan-02.json`。不要编辑清单绕过检查。输出文件已存在时不会覆盖，下一次必须用新文件名。

## 方式二：应用身份部署

初始化管理员既要有 Entra 应用管理权限，又要能在目标订阅分配角色，例如 Owner 或 Contributor + User Access Administrator。仅有 Contributor 通常不能给应用授予 Contributor。Entra 全局管理员也不自动拥有 Azure 订阅权限。

先以管理员登录同一个客户租户，然后检查应用和授权方案：

```powershell
.\.venv\Scripts\python -X utf8 image_batch.py setup-app --config config.json --app-name "客户确认的图像部署应用名称" --output output/app-check-01.json --secret-output output/app-01.private.json
```

确认后执行初始化：

```powershell
.\.venv\Scripts\python -X utf8 image_batch.py setup-app --config config.json --app-name "客户确认的图像部署应用名称" --execute --secret-days 90 --output output/app-result-01.json --secret-output output/app-01.private.json
```

- 未找到该名称应用：创建单租户应用、企业应用、一条 90 天密钥，逐订阅补齐 Contributor。
- 已有唯一同名单租户应用：复用。已有无条件 Owner/Contributor（包括父级授权）会跳过；不删除其他角色。
- 多个同名应用、同名多租户应用或租户不匹配：停止，要求使用明确的唯一名称。
- 已有应用默认不新增密钥；客户须提供有效的现有应用凭据。确需增加一条新密钥时加 `--new-secret`，旧密钥保留。
- 新密钥值只在创建时可取；已有密钥值不能通过 Graph 再次读取。
- 本脚本不为应用授予 Microsoft Graph 应用权限；它通过 Azure RBAC 管理订阅。创建应用的管理员凭据与后续部署应用凭据分开。

使用新凭据进行扫描与部署：

```powershell
.\.venv\Scripts\python -X utf8 image_batch.py scan --config config.json --auth app --credentials output/app-01.private.json --plan output/app-plan-01.json
.\.venv\Scripts\python -X utf8 image_batch.py deploy --config config.json --auth app --credentials output/app-01.private.json --plan output/app-plan-01.json --execute --output output/app-deploy-01.json --include-keys --secret-output output/app-keys-01.private.json
```

也支持 `AZURE_TENANT_ID`、`AZURE_CLIENT_ID`、`AZURE_CLIENT_SECRET` 环境变量。不要把 Secret 写入命令行参数、源码、普通配置或公共仓库。角色生效可能有延迟；403 时检查授权后重新扫描，不会自动反复创建应用/密钥。

## 结果与异常

普通结果：订阅、区域、账户 ID、部署名称、模型版本、capacity、Endpoint 与 `endpoints` 字典、实际 `rpm`、`rate_limits`。`rpm: null` 表示 Azure 没有返回可识别的 RPM，不会用估计值冒充。扫描中的 `estimated_rpm` 是 SKU 参考推算，正式结果以部署实际返回为准；RPM 不是性能或每分钟成功图片数承诺。

私密结果：每个账户的 `key`（Key1）及 Endpoint，或读取失败原因。它是账户级 Key，一个账户多个部署共用；不是每个模型独立 Key。禁用本地 Key 认证的账户会报错，脚本不会开启认证或修改网络规则。新建 AIServices 账户使用 Azure 默认网络设置；部署前客户须确认该设置符合组织要求。

退出码 `0` 为处理结束且无已知失败，`2` 为部分阻塞/失败，`1` 为输入/登录/流程错误，`130` 为人工中断。全部部署读取只依靠当前显式身份，不回退到其他 CLI 账号或托管身份。

资源组、账户、部署均为创建操作；发生超时后 Azure 可能继续执行。先扫描查看实际状态，再决定重试；脚本不会自动删除资源或重放 POST 创建密钥。不要在同一客户订阅并行运行多个部署进程，也不要在执行期间由其他人调整同模型配额。If-None-Match 创建保护依赖资源提供程序支持，不能替代跨进程互斥。

订阅未注册 Microsoft.CognitiveServices、名称全局冲突、资源锁、Azure Policy、模型白名单或无配额都可能阻止创建。请在 Portal 核实后重扫。Contributor 不绕过这些限制。应用/Key 私密文件请放在仅客户本人可读的目录；Windows 文件权限继承父目录，文件不是加密保险库。分发包不包含真实账号、客户配置、报告、凭据或生成图片。

## 验证范围

已通过模拟 Azure 响应的自动化测试，涵盖配额分配、重复部署、状态变化、失败继续、凭据文件保护等。尚未在客户租户完成真实应用创建、RBAC 分配、模型部署和 Key 读取验收；首次仅执行一个测试订阅，再核对 Portal 及 API 调用。部署脚本不发起付费的图片生成测试。

公共仓库的自动检查在 Windows/Linux、Python 3.10/3.12 上运行模拟测试和应用身份离线环境检查，不使用 Azure 凭据。GitHub 自检通过也不等于客户环境已部署成功。

维护者可运行 `python package_release.py --output dist/azure-foundry-image-batch.zip` 生成源码白名单发布包。它不收集真实 config、凭据或结果，并且不会覆盖已存在的压缩包。

## 官方参考

- [Azure OpenAI 配额、Tier 与共享范围](https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits)
- [模型区域可用性](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability)
- [Model Capacities API](https://learn.microsoft.com/en-us/rest/api/microsoftfoundry/accountmanagement/model-capacities/list?view=rest-microsoftfoundry-accountmanagement-2025-06-01)
- [区域模型及 SKU API](https://learn.microsoft.com/en-us/rest/api/microsoftfoundry/accountmanagement/models/list?view=rest-microsoftfoundry-accountmanagement-2025-06-01)
