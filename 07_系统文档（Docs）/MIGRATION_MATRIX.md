# 迁移矩阵

采用 Strangler Migration：新入口以适配器包围旧实现，逐条验证等价后再单独评估旧入口。WP9 不删除或改写任何旧路径。

| 旧入口 | 新入口 | 等价测试 | 当前状态 | 回滚路径 | 可否删除 |
|---|---|---|---|---|---|
| input_parser shim | Capture | `tests/experience/test_capture_flow.py` | shadow | 恢复调用旧 input_parser shim | 否 |
| daily_scheduler | Today | `tests/experience/test_today_flow.py` | shadow | 恢复调用旧 daily_scheduler | 否 |
| body_os handler | Body Plugin | `tests/plugins/test_body_plugin.py` | adapted | 恢复旧 body_os handler 路由 | 否 |

旧入口删除必须同时满足以下条件，并为每个入口单独执行：

1. 连续两个验收周期无回退。
2. 对应行为等价测试通过。
3. 用户确认删除该入口。
4. 已批准独立删除计划，明确回滚点和影响面。

在这些条件完成前，旧入口仍是正式恢复路径；迁移状态变化需要同步更新本表和相应测试证据。
