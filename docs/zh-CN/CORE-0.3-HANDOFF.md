# YushuOS Core 0.3 对接说明（契约 v1.1）

本文面向插件和独立 App 的维护者，说明 Core 0.3 的兼容边界、API v2 插件协议、SDK 事件接口与自动化交接规则。Core 是本机的能力目录、校验与授权边界；领域业务和账号数据仍属于独立插件或 App。

## 兼容边界

既有 CLI 命令 `doctor`、`catalog`、`parse`、`plan`、`invoke`、`workflow`、`status`、`resume` 保留原默认 JSON 形状与调用行为。`catalog --details` 才追加输入/输出 Schema、意图、权限、资源范围和 `execution_mode` 等描述字段；默认 `catalog` 不切换到详情结构。CLI 全局参数 `--config-root` 与 `--project-file` 放在命令前。

既有 manifest `contract_version: 2` 插件继续使用 `json-stdio-v1` runner（Core API v2 的结构化 Request/Result 契约保持不变）：Core 通过 stdin 发送一个 JSON envelope，插件向 stdout 返回一个 JSON result。结果只允许 `status`、`request_id`、`message`、`resource`、`data`、`error` 这些字段；Core 校验状态、请求 ID、字段类型和已声明的输出 Schema，未知字段或不匹配结果会被拒绝。自动化新增的 `host_required` 限制针对自动触发执行，不改变旧的手动 `invoke` 路径。

插件 manifest contract v3 使用 `json-stdio-v2` runner，并增加必需的不可变 `context`；它沿用 Core API v2 的 Request/Result 字段契约。SDK 的 `PluginContext.from_envelope()` 校验精确字段集、插件与请求身份、provider digest、事件声明、深度及资源映射，并递归冻结其值。context 的可信来源由 Core runtime 在调用时绑定；插件自行构造字典不能替代该绑定。原有 v2 插件不需要添加此上下文即可继续使用。

## SDK、台账与事件

`Request`、`Result` 和 SDK 位于 `yushuos-core` 同一发行包中，插件从 `yushuos_sdk` 导入；当前不需要单独安装名为 `yushuos-sdk` 的发行包。自动化的私有动作模板只描述能力、意图、字段和可选 target/workflow 步骤；模板不得写入 `request_id`。Core 按 `run_id` 与 `step_id` 为每一步派生稳定请求 ID，重放同一 occurrence 时得到相同 ID。

动作 hash、规则 revision、授权绑定以及稳定 run ID 和步骤 request ID 使用 RFC 8785 JCS 字节的 SHA-256。公式如下：
- run_id = "run-" + SHA-256(JCS({"kind":"run-v1","rule_id":rule_id,"rule_revision":revision,"occurrence_key":occurrence_key}))
- request_id = "req-" + SHA-256(JCS({"kind":"step-v1","run_id":run_id,"step_id":step_id}))
两种摘要均使用小写十六进制。SDK outbox event ID 单独按确定性 SHA-256 生成：对 {"request_id":request_id,"index":emission_index,"type":event_type} 使用 ensure_ascii=False、键排序和紧凑分隔符序列化为 UTF-8 JSON 后计算摘要。outbox event ID 不是 JCS 摘要。根事件 depth 为 0；由事件触发的 run 再发射事件时，depth 在 causation depth 上加 1。

插件通过 `StateStore.claim(request)` 先占用原请求；结果明确后调用 `record_with_events(result, context, emissions)` 记录收据，只有确认 `succeeded` 时 SDK 才会提交声明事件。SDK 在**同一个现有 Core operations SQLite 台账事务**内写入最小收据和事件 outbox envelope；事件 ID 由原请求 ID、发射序号和事件类型确定，类型必须在 manifest 的 `emitted_events` 中，资源信息只保留允许的引用字段。未知、失败或部分结果不发出成功业务事件。该事务原子覆盖收据和 outbox，但不覆盖插件私有文件写入，也不覆盖另一份 automation SQLite 数据库。外部 App 的 provider fingerprint 纳入 App 文件摘要、external binding 和配置文件 SHA，不纳入绝对路径或配置正文；仅迁移安装路径不改变 fingerprint，同版本代码或配置变化会使旧授权失效。

事件的 source plugin/version、project、request、causation、root 和 occurrence 信息由可信 context 生成，CLI 事件只能由 `core.cli` 来源发布，调用者不能伪造插件来源。`automation tick` 从已登记插件的 outbox 导入事件前会检查源插件、事件声明、版本和 provider digest；重复导入由稳定事件 ID 去重。Core 不在 workflow 多步骤之间提供单事务回滚。

## 自动化标识与执行边界

每个触发 occurrence 都有唯一键：手动调用使用 invocation ID，事件触发使用 event ID，cron 使用 UTC 计划时刻，interval 使用 anchor 与间隔序号。run ID 从规则 ID、规则 revision 和 occurrence key 稳定派生。相同 occurrence 不会再次创建第二次执行；每条 rule 同时最多一个活动 run。

运行器用 30 秒租约并每 5 秒续约。worker 可并发处理不同规则，重复规则运行会被挡住。事件因果链最大深度为 8，单一 root 的 fan-out 上限为 256。未知结果不会自动重放：保持原 run/request 身份进行读回核验；`abandoned` 会留下显式决策并保留资源锁。自动化历史保存受限元数据、hash、pin、状态和资源引用，不保存字段正文或 workflow payload。

`automation` 通过独立数据库 `<config-root>/state/automation.sqlite` 管理 rule、授权、事件和 run；Core 原有 `operations.sqlite3` 仍是插件请求收据与 outbox 台账。自动化规则通过插件私有数据目录中的 `actions/<action_ref>.json` 引用动作模板，DB 只记录引用、hash 和 provider pin。settings 文件 `automation.yaml` 支持 `schema_version: 1`、时区和历史保留天数。详见[自动化指南](AUTOMATION.md)。

## 通用 App Descriptor v1

独立 App 包不随 Core 一起发布。需要适配的 App release 可提供 `release/app-descriptor.json`，顶层字段为 `schema_version: 1`、`app`、`version`、`capabilities`。每项能力声明唯一 ID、`effect`、`intent`、输入/输出 Schema、`execution_mode`、`auth.required` 与 scope、`resource_bindings`，可带 description。Descriptor 是可分发的策略元数据，不得包含凭据、token、账号信息或本机路径。

执行 `yushuos --config-root <root> sync-app-plugin --app <app-id> --app-root <app-install-root>` 可根据已验证活动 release 生成不可变 Core adapter，并写入受控绑定。任意新的 App ID 必须提供 Descriptor；旧 `ima`、`feishu` 包在没有 Descriptor 时仍按既有兼容协议登记。带 Descriptor 的通用 App adapter 使用 contract v3 与 `json-stdio-v2`；App CLI 继续从 stdin 读取原 request，并可从环境变量 `YUSHUOS_PLUGIN_CONTEXT` 读取 JSON context，供 SDK 校验和记录。账号、访问凭据、release 和共享台账由 App 本机 active pointer 管理，不进入 Descriptor 或 Core 包。

## 发布验收要点

- 默认 v2 CLI、catalog JSON、插件请求/结果结构应保持稳定；详情以 `catalog --details` 显式选择。
- 插件只在成功确认后发出声明过的事件，并用 SDK 将收据与 outbox 一起写入原 Core 台账。
- 自动化授权绑定规则 revision、动作 hash、provider digest 和资源 pin，30 天后过期；任何绑定变化都要重新审阅授权。
- `host_required` 自动化先进入 `host_pending`，宿主明确接管后才可执行；旧手动 `invoke` 不受此自动化等待状态影响。
- 以 `unknown` 结束的写入必须先按原 request ID 做外部读回，再通过 history resolve 追加核验决定；不能创建新 request ID 来重复提交。
- App packages、IMA/飞书服务、真实账号与数据不包含在 Core 仓库或本地演示中。
