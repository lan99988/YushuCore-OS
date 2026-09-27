# 插件能力清单

本清单对应 `capability_plugins/manifests/*.yaml`。状态在本工作区按注册中心的有效状态计算；`ready` 表示可被编排器解析，`dormant` 表示按需插件尚未激活。

刷新或查看完整能力列：

```powershell
.\.venv\Scripts\python.exe scripts\plugin_inventory.py
```

机器读取格式：

```powershell
.\.venv\Scripts\python.exe scripts\plugin_inventory.py --format json
```

| 插件 | 状态 | 领域 | 能力 |
|---|---|---|---|
| body | dormant | body | `body.adjustment_suggestion`, `body.current_energy`, `body.recovery_context`, `body.training_context` |
| calendar | ready | calendar | `calendar.check_conflict`, `calendar.create_proposal`, `calendar.find_free_slots`, `calendar.list_events`, `calendar.move_proposal` |
| creation | dormant | creation | `creation.capture_proposal`, `creation.feedback_proposal`, `creation.transition_proposal` |
| experience | dormant | experience | `experience.record_proposal`, `experience.reflection_promotion_proposal`, `experience.transition_proposal` |
| finance | dormant | finance | `finance.monthly_snapshot` |
| goal | dormant | goal | `goal.create_proposal`, `goal.current`, `goal.gap`, `goal.parse` |
| information | ready | information | `information.capture`, `information.get`, `information.list_inbox`, `information.propose_domain`, `information.recognize` |
| interest | dormant | interest | `interest.exploration_proposal`, `interest.project_conversion_proposal`, `interest.record_proposal` |
| knowledge | ready | knowledge | `knowledge.evidence_context`, `knowledge.get`, `knowledge.get_schema`, `knowledge.health`, `knowledge.read_context`, `knowledge.search` |
| learning | dormant | learning | `learning.context`, `learning.current_state`, `learning.progress` |
| life_admin | dormant | life_admin | `life_admin.capture`, `life_admin.domains` |
| project | dormant | project | `project.context`, `project.create_proposal`, `project.list`, `project.milestone_proposal` |
| social | dormant | social | `social.capture` |
| task | ready | task | `task.create_proposal`, `task.list`, `task.parse`, `task.prioritize`, `task.update_proposal` |

该清单枚举 manifest 声明，不会导入插件实现、读取业务数据或触发外部写入。按需插件首次使用前需经过既有生命周期接口激活；关闭或 dormant 状态不得被当作 ready 能力调用。
