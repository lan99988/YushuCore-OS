# 插件契约与开发

## 插件目录

领域能力从 `templates/plugin-template` 开始，应用适配器从 `templates/app-plugin-template` 开始。每个插件独立安装、独立版本化。Core 将已验证插件安装到 `~/.yushuos/plugins/<plugin-id>/<version>`，并把该版本视为不可变。

插件包包含 `plugin.yaml`、`SKILL.md`、`README.md`、`run.py` 和插件私有的 `data/` 目录。清单描述稳定 ID 与版本、契约版本、依赖、数据路径、运行环境、配置、输入输出 Schema、效果、意图、权限、资源范围、路由，以及实现/验证/授权状态。凭据和远端资源标识放在本地绑定中，不要打进分发包。

## Runner 协议

Core 向 runner 的 stdin 发送一个 JSON 请求。contract v2 使用 `json-stdio-v1`，contract v3 使用 `json-stdio-v2`。runner 只在 stdout 输出一个 JSON 结果，诊断信息写入 stderr。`yushuos-core` 发行包内含插件可导入的 `yushuos_sdk`，提供请求/结果类型和共享状态存储。子进程使用裁剪后的环境变量，但插件仍是可信本地代码，不构成操作系统沙箱。

外部写入前，用原始请求 ID 调用 `StateStore.claim`。contract v2 插件可继续用 `StateStore.record` 记录已知结果。contract v3 插件接收运行时校验且不可变的 `PluginContext`，与 `StateStore.record_with_events(result, context, emissions)` 配合，在既有 Core 台账的同一事务中记录确认收据和已声明 outbox 事件。可信 context 由运行时绑定到调用；自行构造字典不能伪造可信来源。若请求 ID 已被占用，先检查原回执。结果不确定时保留待核对状态，避免盲目重放。工作流检查点不要写入私有请求正文。

## 创建并安装插件

1. 将模板复制到私人工作目录，设置唯一插件 ID 和版本。
2. 实现清单、Skill 使用说明、README 和 JSON-stdio runner；先从只读能力开始。
3. 生成锁定清单：

   ```bash
   yushuos lock-plugin --path ./my-plugin
   ```

4. 安装不可变插件包：

   ```bash
   yushuos install-plugin --path ./my-plugin
   ```

5. 检查 `yushuos catalog`。安装不会授予权限，也不会静默切换新版本。存在多个版本时，在 Core 配置中明确选择一个版本；并检查宿主停用状态、依赖和授权状态。
6. 只有具体写入场景已记录清楚时，才配置最小权限和共享操作台账；任何获准写入前先预览。

`plugin.lock.json` 用于发现包内容意外变化，不验证发布者身份，也不能让不可信代码变安全。安装前先检查插件源码。

## 示例

`templates/plugin-template/plugin.yaml` 与 `run.py` 是只读示例。`templates/project-contracts.example.yaml` 展示项目级数据契约。发布前替换示例 ID 和 Schema。


## Contract v3 上下文与事件

manifest contract v3 要求 `json-stdio-v2` 和精确字段的 context 对象。插件从 `yushuos_sdk` 导入 `PluginContext`，用 `PluginContext.from_envelope(envelope)` 校验调用信封。不可变上下文绑定 request ID、插件 ID/版本、provider digest、project、现存台账/数据路径、允许的事件名、自动化 run/root/causation/depth 与 mode。不要自行创建或修改上下文来冒认插件身份。

只发射 manifest 声明的事件。`claim(request)` 返回 true 后，结果明确时调用一次 `record_with_events`。SDK 在既有 Core 台账的同一事务中提交最小收据和 outbox envelope；只有确认 `succeeded` 才发出成功业务事件，并会过滤资源引用。这不会让插件文件写入或多步 Core workflow 变成事务。

## `local_commit_v1` 本地提交恢复协议

只有 contract v3 manifest 可以声明顶层 `operation_support: local_commit_v1`。该声明给插件的 `internal_write` 能力启用显式 `invoke`、`replay`、`recover` runner action；同一插件可同时声明 `read_only` 能力，但不可声明 `external_write`。未声明该 profile 的 v2/v3 插件继续使用原有 `Request.fingerprint()` 和 runner 行为。

Core 写能力预览会先校验输入 Schema 和已声明的资源范围，然后直接返回 `data: {capability, planned_fields, target, write_performed: false}`。Core 不启动 runner、不绑定执行上下文、不 claim，也不创建插件数据目录或操作台账；此预览展示原始已校验输入，不替插件执行默认值、trim 或生成 ID。`Task` 插件的预览因此不得把其提交函数当作预览入口。

该 profile 的 runner envelope 在 v3 JSON 信封中增加 `action`：

| action | 用途 |
|---|---|
| `invoke` | 首次获准执行。先由 `StateStore.claim(request)` claim，再把业务变更和本地提交证明写在同一私有事务内。 |
| `recover` | 仅由显式 `resume --host-mode execute` 调用。只核验原提交证明；有证明时用 `reconcile_confirmed` 补 Core 收据和事件，没有证明时返回 unknown，绝不重新执行业务。 |
| `replay` | 在当前能力、权限、资源和原 provider 均通过检查后，读取插件私有保存的原结果快照，不执行写入。 |

profile context 使用 `schema_version: 2`，在原 v1 字段之外要求 `intent`、`operation_support` 和 `fingerprint_scheme`。原 `schema_version: 1` context 字段与 `PluginContext.to_dict()` 输出保持不变。Core 将初次调用的 provider ID/version/digest、project、intent 和原因果 trace 绑定到 Core 台账；recover/replay 复用这一身份。若 provider 版本或摘要改变，Core 停止操作，不把旧请求交给新代码恢复。

本地写操作的指纹由 Core 绑定 profile 选择并持久化，插件不可自选或按哈希猜测 scheme。`legacy-v1` 完全沿用 `Request.fingerprint()`；`jcs-operation-v1` 用 RFC 8785 JCS 的 SHA-256，只覆盖 `{capability, fields, target}`。`intent` 和顶层 `project_ref` 由 Core 另行绑定并在 claim/恢复时核对。SDK 提供 `yushuos_sdk.canonical.fingerprint_for_scheme(request, scheme)` 作为统一实现；正常插件调用 `StateStore.claim(request)` 即可，SDK 从 Core 绑定读取算法。

插件发现原 Task 数据库已有与请求指纹匹配的完整提交证明时，调用 `StateStore.reconcile_confirmed(request, result, context, emissions)`。该 API 在一个 Core 台账事务中添加不可变核验收据并写入事件 outbox；原 `unknown` receipt 与任何人工 resolution 都保留，冲突或 abandoned 请求会被拒绝。Core 收据只保存最小状态，不保存 Task 正文。正文过期时，插件仍将原业务状态报告为 `succeeded`，并在返回数据中标记 `operation_status: committed`、`result_state: expired`、`code: task.result_expired`、`task_id` 和 `original_request_id`；不得补造 `{task, changed}`。

`StateStore.operation_context(request_id)` 返回 Core 绑定的安全元数据，含 provider identity、原 project/intent/trace、事件声明、operation profile 和 fingerprint scheme；它不返回路径、resource binding 或业务正文。CLI `status` 对 schema v2 profile 操作增加 provider provenance 和 outbox 安全资源引用，旧台账和旧 context 的输出形状保持不变。

## Nullable Schema

输入/输出 Schema 可将 `type` 写成一个具体 JSON 类型与字符串 `null` 的二项数组，例如 YAML `type: [string, "null"]`，对应 JSON `{"type":["string","null"]}`；也可写 YAML `type: "null"` 表示值只能是 JSON null。类型数组不得包含多个非 null 类型。YAML 中实际空值不是有效类型名。

## 独立安装的 App

通用 App release 提供 `release/app-descriptor.json`，包含 `schema_version: 1`、`app`、`version` 和能力定义。每项能力声明 `id`、`effect`、`intent`、`input_schema`、`output_schema`、`execution_mode`、`auth: {required, scopes}` 与 `resource_bindings`；`description` 可选。Descriptor 只包含可分发策略元数据，不包含凭据或本机路径。使用 `yushuos --config-root <root> sync-app-plugin --app <app-id> --app-root <app-install-root>` 登记。新的通用 App ID 必须有 Descriptor；没有 Descriptor 的旧 IMA/飞书 release 仍可按兼容方式使用。
