# 客户网页使用说明

## 登录与操作

1. 打开部署者提供的 HTTPS 工作台网址，填写客户的 Azure 目录（租户）ID。
2. 点击“登录 Azure”。网页显示 Microsoft 登录地址和设备代码，客户本人在 Microsoft 页面登录并完成 MFA。工作台不收集密码、验证码。设备代码登录使用 Azure SDK 内置的 Microsoft Azure CLI 公共客户端，**容器内无需安装 CLI**。登录页可能显示“Microsoft Azure CLI”，这是身份客户端名称。
3. 返回工作台，自动读取当前账号可访问的启用订阅，默认全选。可在下拉框搜索、勾选并应用，不会触发整页刷新。
4. 勾选需要部署的模型，选择部署类型和配额范围，填写资源组、Foundry、Project 命名规则。版本默认从 Azure 的 `isDefaultVersion` 标记解析，按订阅和区域分别确认；无法确认时该项不会创建，可在高级设置指定版本。
5. 点击“检查部署配置”，查看名称、区域、版本、最大可分配容量、已有部署以及阻塞原因。默认 `quota_scope=unknown` 只检查；必须按该客户实际配额确认是区域独立、订阅共享还是数据区共享后，重新检查才能创建。
6. 点击“确认并创建缺失项”，核对确认窗口后执行。已有同模型/同部署类型的部署复用，不修改版本、容量或 Key。新 Foundry 启用系统托管身份与 Project 管理，Project 是其子资源；网络沿用 Azure 默认设置，不会自动创建私有端点、防火墙或资源锁。
7. 结果先在网页显示。点击“读取 Key”仅读取现有账户 Key，不重新生成；随后可以逐项显示和复制。默认隐藏。禁用 Key 认证的账户不擅自启用。
8. 点击“导出 Excel”。主表列顺序固定为：**订阅、订阅 ID、资源组、资源名称-foundry、区域、资源、url、密钥**。其中“资源名称-foundry”为真实 Foundry 账户名，“资源”为真实 Project 名。URL 使用 Azure 返回的资源 Endpoint，不拼接虚构 URL。“模型部署”表保存实际版本、模型、容量、RPM 和处理情况。只有明确确认才把已读取的 Key 写入 Excel。

## 模型与区域

- 生图：`gpt-image-2.5-flare`、`gpt-image-2.5-sunburst`、`gpt-image-2`。
- 文本：`gpt-5.6-terra`、`gpt-5.6-luna`、`gpt-5.6-sol`、`gpt-6-sol`、`gpt-6-luna`、`gpt-6-astra`、`gpt-6.1-sol`。
- 以上是允许选择的名称，不代替 Azure 模型目录。当前客户未开放的模型/版本/类型会记录无法确认或无可用区域，不能通过改名绕过。
- `gpt-image-2` 只使用五个候选区域：`eastus2`、`westus3`、`polandcentral`、`swedencentral`、`uaenorth`。
- 其他模型默认按各自的 Azure 目录/容量查询可用区域。创建前客户必须核对清单中的实际区域和数据处理范围；可关闭自动区域，明确限制批准区域。
- 最大容量受实际剩余配额、SKU 容量最小/最大/步长及区域可用容量共同约束。共享额度只分配一次；不默认认为五个区域就是五份独立额度。容量单位不是通用 TPM 或 RPM 换算表，Azure 未返回 RPM 时不会填写猜测值。

## 命名示例

资源组 `CV-{subcode}`，Foundry `cv-{subcode}-{index:03d}`，Project `{foundry}-resource`。

订阅名为 `Azure Subscription A03` 时，gpt-image-2 候选区域对应 001–005。其他模型新增区域从 006 后继续，复用同区域账户，不因为选择多个模型而重复创建同名账户。同名跨订阅冲突会要求改规则；客户应添加自己的独有公司前缀，避免 Azure 全局自定义域冲突。`{subcode}` 会保留 `A01-10` 的完整编号。

已有账户会使用实际名称。现有 OpenAI 账户、未开启 Project 管理或缺少托管身份的 AIServices 账户不能直接创建 Project；工具显示阻塞并跳过对应模型，不自动升级或覆盖它。

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

为该容器设置 `PUBLIC_ORIGIN=https://该容器的实际域名`，精确包含域名、不得带尾斜杠或子路径。生产 Cookie 为 Secure、HttpOnly、SameSite=Strict；API 拒绝跨源写入。换自定义域名时同步修改此变量。未正确配置时页面拒绝非 localhost Host，这是保护行为。

镜像拉取使用专用托管身份及 ACR 的 AcrPull；容器运行身份不自动获得客户订阅权限，实际 Azure 操作使用客户手动登录的身份。无需配置客户密码、应用 Secret 或 Storage Key。不要把登录响应/密钥写到访问日志或监控采集内容中。

组织条件访问如果禁止设备代码流，登录将失败，需要客户管理员确认组织政策；工具不降低安全策略。此版不实现授权码回调登录；若组织只允许该方式，应为部署者自己的多租户应用配置正式 OAuth 登录后再使用，不复制其他工具的客户端 Secret。

## 部署者验收

```bash
python -X utf8 self_test.py
python -X utf8 web_test.py
```

测试使用合成租户/订阅和模拟 ARM，不访问真实 Azure，也不证明客户真实写权限。部署后分别验证健康页、真实 Microsoft 登录、模型目录读取、一个获准试点创建、Project 状态及客户 Excel 下载。没有客户对试点创建的授权时只做只读验收。

官方依据：[设备代码认证](https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.devicecodecredential)、[Foundry/Project 创建](https://learn.microsoft.com/en-us/azure/foundry/how-to/create-projects)、[模型目录和默认版本](https://learn.microsoft.com/en-us/rest/api/microsoftfoundry/accountmanagement/models/list?view=rest-microsoftfoundry-accountmanagement-2025-06-01)。
