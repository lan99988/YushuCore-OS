# 运行与恢复手册

本地默认网络模式为 `OFF`，Agent 自治等级上限保持 2。所有恢复先定位故障和 correlation ID；不要通过扩大权限、开启网络或删除旧入口来绕过失败。

## 日常检查

```powershell
.\.venv\Scripts\python.exe scripts\plugin_inventory.py
.\.venv\Scripts\python.exe scripts\flow_smoke_test.py
.\.venv\Scripts\python.exe scripts\verify.py
```

冒烟运行全部六条 Flow，使用本地 fixture，不访问外部服务。JSON 输出可用于自动化：

```powershell
.\.venv\Scripts\python.exe scripts\flow_smoke_test.py --format json
```

故障模拟选项：`--scenario plugin_unavailable`、`--scenario permission_denied`、`--scenario partial_failure`。模拟插件仅在临时本地目录中运行，命令退出后 fixture 状态会清理。

## 插件不可用

1. 记录 Flow 与 `correlation_id`，执行 `plugin_inventory.py` 查看对应插件状态和声明能力。
2. 若为 dormant，确认是否由使用场景要求激活；若为 disabled、unavailable 或 dependency unavailable，检查对应 manifest 和依赖状态。
3. 恢复到最近已知可用的 manifest / 插件实现后，再运行 inventory、对应 Flow 测试和 `flow_smoke_test.py`。
4. 新入口仍不可用时，按迁移矩阵切回对应旧入口；保留新旧入口，不删除任何路径。

## 权限拒绝或需要审批

1. 按 `correlation_id` 检查 `policy_blocked`、`approval_required` 事件及审计记录中的 `reason_code`。
2. `policy_blocked` 表示动作未执行；先确认插件声明权限与 Agent 已授权限是否匹配。
3. 需要审批的动作保持待确认状态，等待用户通过现有审批入口决定；不得自动重试或扩大 Agent 权限。
4. 审计写入失败时策略执行必须 fail-closed：保持阻止状态，恢复本地审计存储后重试原请求。

## 部分结果、失败与补偿

1. 按 `correlation_id` 检查 `partial_result` 的步骤计数，并对照 `plugin_started`、`plugin_completed`、`plugin_failed` 和策略事件。
2. 只有插件提供补偿回调后才会出现回滚事件。`rollback_completed` 状态为 `completed` 表示补偿成功；`failed` 表示补偿回调未成功；`simulated` 仅表示离线冒烟 fixture 的补偿模拟，不代表真实数据发生过回滚。
3. 没有补偿回调的步骤不声称已回滚。若发生无法物理回滚的外部写入，登记目标系统、已完成操作、影响对象和人工补偿动作，逐项完成后再重跑。
4. 修复实现后先运行对应插件 / Flow 测试，再运行六 Flow smoke 和 `scripts/verify.py`。

## 代码回退

1. 定位引入故障的变更和可恢复版本，保留当前工作区其他改动。
2. 按仓库审查流程恢复目标 WP9 文件或代码版本；不执行清空工作区、删除未跟踪文件或移除旧入口的操作。
3. 回退后运行 `pytest -q`、`scripts/verify.py`、插件清单和六 Flow smoke。
4. 验证恢复结果和事件中没有凭证、知识正文、财务截图正文、健康原始数据或完整外部消息正文。

## 事件数据边界

事件只保留受控元数据：Flow、插件 / 能力标识、步骤状态、错误类型、计数和 correlation ID。事件总线订阅者与本地日志接收安全快照；普通遥测接收端故障不打断业务执行。策略审计存储故障会阻止受控动作执行。
