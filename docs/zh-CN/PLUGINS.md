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

## 独立安装的 App

通用 App release 提供 `release/app-descriptor.json`，包含 `schema_version: 1`、`app`、`version` 和能力定义。每项能力声明 `id`、`effect`、`intent`、`input_schema`、`output_schema`、`execution_mode`、`auth: {required, scopes}` 与 `resource_bindings`；`description` 可选。Descriptor 只包含可分发策略元数据，不包含凭据或本机路径。使用 `yushuos --config-root <root> sync-app-plugin --app <app-id> --app-root <app-install-root>` 登记。新的通用 App ID 必须有 Descriptor；没有 Descriptor 的旧 IMA/飞书 release 仍可按兼容方式使用。
