# CLI 与日常使用

## 路由过程

AI 宿主负责理解自然语言和对话。它读取 Core 能力目录，只路由已声明能力，并提交符合 JSON 契约的请求。Core 选择插件版本、校验输入、执行权限门禁并返回 JSON 结果。领域规则与业务数据由插件负责。

用显式前缀（例如 `#example`）查询路由：

```bash
yushuos parse --text "#example hello"
```

未注册的自然语言请求会交回宿主；路由含糊或不可用时要求澄清，Core 不会猜测提供者。

## 检查与调用

```bash
yushuos doctor
yushuos catalog
```

`doctor` 检查配置和插件清单；`catalog` 列出已安装版本、能力声明、路由可用性和执行状态。清单中写有某项能力，不代表外部账号或能力已经可用。

安装示例插件后，可以通过 stdin 发送一个 JSON 对象。默认调用是预览模式，并采用只读宿主模式：

```bash
printf '%s' '{"request_id":"demo-read-001","capability":"example.echo","intent":"read","fields":{"message":"hello"}}' | yushuos invoke
```

输出是一个包含 `status`、`request_id` 和结果数据或结构化错误的 JSON 对象。使用 `yushuos status --request-id <id>` 查看回执；查询同一操作时沿用原请求 ID。

## 流程与写入

`plan` 始终只生成预览。只有用户请求执行、宿主模式为 `execute`，且 Core 与插件的所有门禁均通过时，`workflow` 才会执行。先预览并检查预期变更。

外部写入必须同时满足：插件声明写入能力和意图、插件信息已验证并授权、存在匹配权限授予、已配置共享操作台账、用户明确要求写入、宿主授权执行。缺少任何条件都会 fail-closed。Core 授权不能取代宿主授权。

写入结果为 `unknown` 时，用原请求 ID 查询 `status` 并核对远端状态。不要换新 ID 重放或盲目重试。恢复流程依据已记录回执和资源引用；工作流检查点不保存私有请求正文。

## 配置与发布命令

Core 数据目录默认为 `~/.yushuos`；可用 `YUSHUOS_HOME` 或全局参数 `--config-root` 指向其他目录。密钥、账号绑定、远端资源 ID 和插件业务数据应保存在仓库之外。默认无权限授予且写入处于预览模式。

项目配置可以选择插件版本、提供者、资源范围或命名空间内的插件设置，但不能扩大全局权限或改变 Core 执行模式。可从 `templates/project.yaml.template` 开始。

- `deploy --preview --version <id>`：安装不可变候选版本。
- `verify --version <id>`：检查包哈希。
- `activate --version <id>`：切换活动版本。
- `rollback`：恢复到上一个已验证版本。
- `status --request-id <id>` / `status --plan-id <id>`：查询操作回执或流程状态。
- `resume --file <json>`：按回执恢复；未知外部写入不会被盲目重放。

运行 `yushuos <命令> --help` 查看当前参数。
