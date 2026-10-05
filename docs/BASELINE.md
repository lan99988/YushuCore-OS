# API v2 基线

兼容基线冻结于提交 `5bf6bb545fffa08da2b6ebdad7a0f6a46fb4d381`。该提交的 `yushuos/cli.py` 从 `git archive` 导出到独立临时目录，再用归档目录中的 `python -m yushuos` 执行命令采集快照；因此快照来源不依赖后续工作区修改。

`tests/fixtures/v2/plugin.yaml` 和 `run.py` 取自该提交的 `templates/plugin-template`。采集时先用归档版本的 `lock-plugin` 命令锁定临时插件，再通过真实 CLI 和 `json-stdio-v1` runner 调用插件。`cli.json` 保存 `doctor`、默认 `catalog`、最长前缀路由与宿主 handoff、默认 preview `invoke`、已授权写能力仍返回 preview 的 gate 输出，以及 workflow preview 的完整 JSON 输出。写能力 gate 还断言没有启动插件数据目录。`workflow-execute.json` 保存显式执行后的 workflow、状态查询及旧请求收据。执行样例从 `legacy-ledger.sql` 创建 v0.1 台账，确认原有 `operations`、`locks`、`events` 数据与 `user_version=1` 保留，同时新增 workflow 表。

测试逐字段比较 JSON，只将 `doctor.core_version` 和 workflow 状态中的动态时间替换为占位符；插件版本、状态、字段、路由结果、gate 结果、计划指纹及工作流状态仍严格比较。临时目录不出现在这些 CLI 输出中，因此不做路径模糊匹配。

运行基线回归：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_v2_regression.py -q
```
