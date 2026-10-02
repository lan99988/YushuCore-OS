# 插件契约与开发

## 插件目录

领域能力从 `templates/plugin-template` 开始，应用适配器从 `templates/app-plugin-template` 开始。每个插件独立安装、独立版本化。Core 将已验证插件安装到 `~/.yushuos/plugins/<plugin-id>/<version>`，并把该版本视为不可变。

插件包包含 `plugin.yaml`、`SKILL.md`、`README.md`、`run.py` 和插件私有的 `data/` 目录。清单描述稳定 ID 与版本、契约版本、依赖、数据路径、运行环境、配置、输入输出 Schema、效果、意图、权限、资源范围、路由，以及实现/验证/授权状态。凭据和远端资源标识放在本地绑定中，不要打进分发包。

## Runner 协议

Core 向 runner 的 stdin 发送一个 JSON 请求。runner 只在 stdout 输出一个 JSON 结果，诊断信息写入 stderr。稳定 SDK `yushuos_sdk` 提供请求/结果类型和共享回执状态存储。子进程使用裁剪后的环境变量，但插件仍是可信本地代码，不构成操作系统沙箱。

外部写入前，用原始请求 ID 调用 `StateStore.claim`；已知结果后调用 `StateStore.record`。如果请求 ID 已被占用，先检查原回执。结果不确定时保留待核对状态，避免盲目重放。工作流检查点不要写入私有请求正文。

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
