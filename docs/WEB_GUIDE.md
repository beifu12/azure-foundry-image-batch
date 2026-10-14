# 客户网页使用说明

## 登录与操作

1. 打开部署者提供的 HTTPS 工作台网址。客户的 Azure 目录（租户）ID 可留空；跨租户来宾需要操作特定客户租户时，填写该客户租户 ID。
2. 点击“登录 Azure”，直接跳转到 Microsoft 选择 CSP／客户账号，按组织政策完成授权和 MFA，再自动返回工作台。首次使用可能需要客户管理员同意 Azure Service Management 委托访问；这只允许工具代表当前账号访问 Azure，不会提升该账号的订阅权限。密码、验证码仅在 Microsoft 页面输入，**无需安装 Azure CLI**。
3. 返回工作台，自动读取当前账号可访问的启用订阅，默认全选。可在下拉框搜索、勾选并应用，不会触发整页刷新。
4. 勾选需要部署的模型，选择部署类型，填写资源组、Foundry、Project 命名规则。配额默认“自动核对”，无需手动确认共享范围。版本默认从 Azure 的 `isDefaultVersion` 标记解析，按订阅和区域分别确认；无法确认时该项不会创建，可在高级设置指定版本。
5. 点击“检查部署配置”，查看名称、区域、版本、Tier 1 目标内的可分配容量、已有部署以及阻塞原因。自动模式（`quota_scope=auto`）逐区域生成候选清单，但不推断共享范围、不承诺区域容量总和一定可创建。执行按顺序逐项进行：创建资源前复核配额，账户就绪后、提交模型部署前再次复核；前项消耗共享额度后，后项余额不足便记录并跳过，不降低确认目标或盲目重试。Azure 仍会校验实际配额和平台容量。需要纯只读清单时可选择“仅检查”，即 `unknown`。
6. 检查清单按订阅折叠，摘要显示待创建、复用与需处理数量；单订阅默认展开，多订阅按需展开，轮询不会收起你已经打开的订阅。点击“确认并创建缺失项”，核对确认窗口后执行。同订阅、同区域已有成功的同模型部署优先复用，不要求版本或部署类型与新建设置相同；显示实际版本、类型、容量，不修改版本、容量或 Key。新 Foundry 启用系统托管身份与 Project 管理，Project 是其子资源；网络沿用 Azure 默认设置，不会自动创建私有端点、防火墙或资源锁。
7. 没有缺失模型时，按钮显示“获取已有部署结果”，直接读取已确认库存，不弹出创建确认，也不创建或修改 Project。检查清单和资源结果都按订阅折叠。结果先在网页显示。点击“读取 Key”仅读取现有账户 Key，不重新生成；随后可以逐项显示和复制。默认隐藏。禁用 Key 认证的账户不擅自启用。
8. 点击“导出 Excel”。主表列顺序固定为：**订阅、订阅 ID、资源组、资源名称-foundry、区域、资源、url、密钥**。其中“资源名称-foundry”为真实 Foundry 账户名，“资源”为真实 Project 名。URL 使用 Azure 返回的资源 Endpoint，不拼接虚构 URL。“模型部署”表保存实际版本、模型、容量、RPM 和处理情况。只有明确确认才把已读取的 Key 写入 Excel。

## 模型与区域

- 生图：`gpt-image-2.5-flare`、`gpt-image-2.5-sunburst`、`gpt-image-2`。
- 文本：`gpt-5.6-terra`、`gpt-5.6-luna`、`gpt-5.6-sol`、`gpt-6-sol`、`gpt-6-luna`、`gpt-6-astra`、`gpt-6.1-sol`。
- 以上是允许选择的名称，不代替 Azure 模型目录。当前客户未开放的模型/版本/类型会记录无法确认或无可用区域，不能通过改名绕过。
- `gpt-image-2` 只使用五个候选区域：`eastus2`、`westus3`、`polandcentral`、`swedencentral`、`uaenorth`。
- 其他九个模型默认只检查 `eastus2`，使用独立的“其他模型部署区域”输入框。gpt-image-2 的勾选区域不会混入此列表。只有主动勾选“自动查询”时，其他模型才按各自 Azure 目录检查更多可用区域。
- 所有新建生图部署默认目标为 **2 RPM**，包括 gpt-image-2 和两种 image-2.5；所有七种文本模型默认目标为 **1,000,000 TPM**。这是本工具按客户要求设置的 Tier 1 目标，不是对所有租户实际配额的保证。已有部署只复用，不自动降额或扩容。
- 工具按 Azure SKU 的 request/token 限流值及 renewalPeriod 换算容量，不把 TPM 直接当作 SKU capacity。若目标与最小值或步长不对齐，向下选择不超过目标的合法容量；若余额不足则使用可分配的合法余额。换算关系缺失时阻止创建，不猜测。实际 RPM/TPM 以创建结果返回为准。
- 容量还受实际剩余配额、SKU 最小/最大/步长及区域可用容量共同约束。共享额度只分配一次；不默认认为五个区域就是五份独立额度。gpt-image-2 五区域均有独立余额且成功创建时，目标合计为 10 RPM；区域已有配置、无余额或不可用时会单独说明。
- GlobalStandard / DataZoneStandard 的容量按整数单位分配：Azure 省略 minimum 或 step 时，工具使用 1；Azure 明确返回的约束始终优先，default 只是默认配置值，不作为最小值或步长。最大值、配额上限、已用配额及可用容量缺失时仍阻止创建，并指明缺失字段。剩余容量为 0 的区域会单独提示，不阻碍检查其他区域。

## 命名示例

资源组 `CV-{subcode}`，Foundry `cv-{subcode}-{index:03d}`，Project `{foundry}-resource`。

订阅名为 `Azure Subscription A03` 时，gpt-image-2 候选区域对应 001–005。其他模型新增区域从 006 后继续，复用同区域账户，不因为选择多个模型而重复创建同名账户。同名跨订阅冲突会要求改规则；客户应添加自己的独有公司前缀，避免 Azure 全局自定义域冲突。`{subcode}` 会保留 `A01-10` 的完整编号。

已有账户会使用实际名称。已有模型部署的复用不依赖新建配额或 Project，旧 OpenAI 资源也可只读复用；有匹配或唯一的已成功 Project 时返回实际名称，否则 Project 留空，不补建。若要在旧账户创建缺失模型与 Project，仍要求账户支持 Project 管理及托管身份；不支持时显示阻塞，不自动升级或覆盖它。部署读取失败或已有部署/账户未成功时不会假定不存在或创建第二个。仅有配额占用、却没有返回可读的同模型部署时，不会假定已经可复用。

## 多订阅与取消

- 每个浏览器会话一项后台任务；一个容器进程最多执行一项创建任务。多订阅、多区域在任务内排队顺序执行，避免同时提交大量 ARM 创建请求和共享配额竞争。
- 登录最多同时处理八项。读取失败不会误认为空资源；新任务不能抢占同会话正在执行的创建。
- 每个 ARM 网络请求最长 60 秒。只读 429/503 最多尝试五次，遵守 Retry-After 退避，网页提供等待说明；单次读取的退避预算三分钟，超过预算停止重试。资源就绪轮询最多十五分钟，当前网络请求可能再增加最多一分钟。
- 点击取消会立即显示“正在取消”，在当前网络请求返回或退避等待取消后停止后续步骤。Azure 已收到的操作不能据此撤销。已完成部署先保留在结果里，即使后续 Project 或订阅取消，仍可导出已知结果。
- 创建、角色配置或密钥生成不盲目自动重试。超时、409、进程重启或网络中断后，先重新检查真实状态。部分项失败会记录，不删除已创建资源或已有授权。
- 任务和登录凭据只在进程内存，不保存 Token/Key 到持久文件、日志或 Git。退出清除本会话数据；容器重启/升级会清除会话和运行中的任务记录，需要重新登录并检查。请在没有创建任务时升级。

## Ubuntu 自有容器（可选）

安装 Docker Engine 及 Compose 后，在项目目录运行：

```bash
docker compose up -d --build
```

同机访问 `http://127.0.0.1:8767/`。远程 Ubuntu 只通过 SSH 隧道访问，不把本地调试 HTTP 端口直接对公网开放：

```bash
ssh -L 8767:127.0.0.1:8767 用户名@Ubuntu地址
```

然后本机浏览器访问 `http://127.0.0.1:8767/`。本地 Compose 默认仅绑定 loopback，不需要 PUBLIC_ORIGIN。

## Azure Container App

部署者使用本目录 Dockerfile 构建镜像。创建**独立** Container App，不复用原运营工具的登录、连接、Token 或 Key。

需要 HTTPS 外部入口，目标端口 8767，至少 1 vCPU / 2 GiB，**minReplicas=1、maxReplicas=1**，revisionMode=Single。此版使用进程内会话和创建互斥，不支持多个副本/多个进程；也不能由其他实例并发写入同一客户租户。

为该容器设置 `PUBLIC_ORIGIN=https://该容器的实际域名`，精确包含域名、不得带尾斜杠或子路径。生产 Cookie 为 Secure、HttpOnly、SameSite=Lax，允许 Microsoft 顶层 GET 授权回调；API 拒绝跨源写入。换自定义域名时同步修改此变量和应用回调地址。未正确配置时页面拒绝非 localhost Host，这是保护行为。

镜像拉取使用专用托管身份及 ACR 的 AcrPull；容器运行身份不自动获得客户订阅权限，实际 Azure 操作使用客户手动登录的身份。无需配置客户密码或 Storage Key。不要把登录响应/密钥写到访问日志或监控采集内容中。

部署者在 Microsoft Entra 注册独立的多租户 Web 应用：支持“任何组织目录中的帐户”，Web 重定向 URI 为 `https://该容器的实际域名/auth/callback`，使用授权码流，不启用隐式授权。API 权限仅需 Azure Service Management 的委托权限 `user_impersonation`。创建该应用的客户端凭据，容器设置 `OAUTH_CLIENT_ID`；`OAUTH_CLIENT_SECRET` 从 Container App Secret 引用，不能写入镜像、示例配置、公开仓库或日志。凭据到期前由部署者轮换。不复用原运营工具的应用密钥。

该登录应用只用于身份授权，不需要作为服务主体绑定客户所有订阅。客户登录账号仍需目标订阅 Contributor 或等效资源操作权限；目录全局管理员角色不等于订阅权限。客户租户禁止用户同意时，由管理员批准委托访问后再登录，工具不会绕过组织策略。

可选的本地 Compose 未配置 OAuth 应用时，仍使用 Microsoft 设备代码登录，必须填写租户 ID；登录页可能显示 Microsoft Azure CLI，这是 SDK 默认公共客户端名称，容器内无需安装 CLI。组织禁用设备代码流时请部署正式浏览器授权方式。

## 部署者验收

```bash
python -X utf8 self_test.py
python -X utf8 web_test.py
```

测试使用合成租户/订阅和模拟 ARM，不访问真实 Azure，也不证明客户真实写权限。部署后分别验证健康页、真实 Microsoft 登录、模型目录读取、一个获准试点创建、Project 状态及客户 Excel 下载。没有客户对试点创建的授权时只做只读验收。

官方依据：[应用注册](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)、[MSAL 授权码登录](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens)、[设备代码认证](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.devicecodecredential)、[Foundry/Project 创建](https://learn.microsoft.com/en-us/azure/foundry/how-to/create-projects)、[模型目录和默认版本](https://learn.microsoft.com/en-us/rest/api/microsoftfoundry/accountmanagement/models/list?view=rest-microsoftfoundry-accountmanagement-2025-06-01)。
