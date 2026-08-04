# Body OS Agent 迁移交接说明

更新时间：2026-07-29

## 结论

Body OS 当前已经完成可用闭环，可以迁移给别的 agent 使用和继续维护。

这里的“完成”指：

- Garmin 数据已进入三层数据契约。
- `#身体`、`#训练`、`#恢复`、`#营养` 四个入口可以直接返回可执行建议。
- 学习负载、训练建议、恢复建议、最低营养建议已经能基于当前数据运行。
- 排程侧已有 L2 任务调整能力：恢复日自动延后非关键高精力任务到飞书 Base。

这里的“未完成”指：

- 不是整个个人混合管理系统的所有长期功能都完成。
- Garmin CN 真实网络增量同步路径还需要在在线登录态下首跑验证。
- 复杂食物数据库、自动改日历仍属于后续阶段。

## 迁移前提

迁移 agent 需要能访问本工作区：

```text
D:\个人混合管理系统
```

Python 直接使用当前环境即可，不需要重复安装 Garmin 包：

```text
C:\Users\26326\.workbuddy\binaries\python\versions\3.13.12\python.exe
```

Garmin 相关包已在托管环境中：

```text
garmin-mcp-server==0.3.4
garminconnect==0.3.7
```

迁移时不要把账号、密码、token、cookie 写入文档或代码。

## 数据契约

保持现有文件名，不重命名。

```text
Garmin API
  -> raw_garmin_365d.json
     原始镜像层，不手工修改，不作为最终业务事实源

  -> body_os_dataset_365d.json
     清洗层，排除无效日期，统一字段

  -> body_os_today_energy.json / _energy_status.json / body_os_garmin_summary.json
     运行态，给 Agent 和入口层消费
```

关键文件：

```text
08_工具脚本（Tools）\身体管理\raw_garmin_365d.json
08_工具脚本（Tools）\身体管理\body_os_dataset_365d.json
08_工具脚本（Tools）\身体管理\body_os_garmin_summary.json
08_工具脚本（Tools）\身体管理\body_os_today_energy.json
04_数据中心（Data）\运行状态（Runtime）\_energy_status.json
```

有效数据起点来自配置，不要硬编码：

```text
04_数据中心（Data）\系统配置（Config）\body_os_config.json
```

当前配置：

```json
{
  "schema_version": "1.0",
  "body_data": {
    "valid_start": "2025-12-11",
    "exclude_days_without_statistics": true
  },
  "garmin": {
    "source": "garmin_cn",
    "raw_is_immutable_mirror": true
  },
  "policy": {
    "scheduler_control_level": 2,
    "manual_energy_overrides_garmin": true
  }
}
```

统计口径：

- `2025-12-11` 之前的数据不纳入统计。
- 有效期内某天无统计信息时，排除那一天，不参与均值和判断。
- 当前口径：227 天有效，2025-12-11 前排除 134 天，有效期内空日排除 4 天。
- 当前最新有效 Garmin 日：2026-07-28。
- 2026-07-29 无有效统计，不能纳入判断。

## 已完成能力

### Garmin 数据层

关键模块：

```text
08_工具脚本（Tools）\身体管理\garmin_bodyos_365d.py
08_工具脚本（Tools）\身体管理\garmin_incremental_sync.py
08_工具脚本（Tools）\身体管理\energy_policy.py
08_工具脚本（Tools）\身体管理\training_policy.py
```

能力：

- 读取 Garmin CN raw 数据。
- 根据配置起点清洗近一年数据。
- 生成今日身体能量上下文。
- 输出学习负载建议。
- 输出训练建议（含 activityType 级规则 + 肌群 48h 重复检测）。
- 增量同步支持 14 天窗口合并和 raw meta schema 版本。

### Body OS 策略层

关键模块：

```text
08_工具脚本（Tools）\身体管理\training_log.py
08_工具脚本（Tools）\身体管理\recovery_policy.py
08_工具脚本（Tools）\身体管理\nutrition_policy.py
```

能力：

- `training_log.py`：解析手动训练输入，支持重量、次数、组数、训练时长、跑步距离；
  新增肌群映射表（MUSCLE_GROUP_MAP），自动将动作名映射到肌群并统计各肌群容量。
- `recovery_policy.py`：根据身体可用能量、睡眠、压力、训练风险给恢复建议。
- `nutrition_policy.py`：最低营养闭环，不使用复杂食物数据库，默认按 70kg 估算蛋白质和饮水。

### 输入入口

关键模块：

```text
02_执行引擎（Engine）\输入解析引擎\handlers\body_os.py
02_执行引擎（Engine）\输入解析引擎\input_parser.py
```

可用入口：

```powershell
python "D:\个人混合管理系统\02_执行引擎（Engine）\输入解析引擎\input_parser.py" "#身体 今天适合怎么安排学习和训练" --dry-run

python "D:\个人混合管理系统\02_执行引擎（Engine）\输入解析引擎\input_parser.py" "#训练 力量 卧推 60kgx8x3 深蹲 80kgx5x5 45分钟" --dry-run

python "D:\个人混合管理系统\02_执行引擎（Engine）\输入解析引擎\input_parser.py" "#恢复 今天怎么恢复" --dry-run

python "D:\个人混合管理系统\02_执行引擎（Engine）\输入解析引擎\input_parser.py" "#营养 今天怎么吃" --dry-run
```

当前预期：

- `#身体` 返回 Garmin 概览、最新有效日期、学习负载、身体可用能量、训练建议（含肌群风险）。
- `#训练` 返回训练记录草稿、总容量、肌群分布与容量统计。
- `#恢复` 返回恢复建议。
- `#营养` 返回蛋白质、饮水和“不使用复杂食物数据库”的说明。

### 排程安全层（L2 已升级）

关键模块：

```text
02_执行引擎（Engine）\每日排程引擎\daily_scheduler.py
```

核心函数：

```python
adjust_tasks_for_energy_policy(tasks, energy_context, dry_run=False)
```

行为由 `body_os_config.json` 中的 `scheduler_control_level` 控制：

- **control_level=1（L1）**：只返回调整建议，不写飞书。
- **control_level=2（L2，当前）**：在 `main()` 中自动调用，恢复日将非关键高精力任务的
  截止日期延后一天并写入飞书 Base 执行库。**不碰日历。**

控制边界：

- `study_load=recovery` 时，保留 P0 和低精力任务，把非关键高精力任务放入 `overflow`。
- `study_load=deep` 时，提高高精力任务权重。
- `dry_run=True` 时跳过 Base 写入（测试安全）。

## 验证命令

迁移 agent 接手后，先跑这些命令。

```powershell
python -m unittest tests.test_training_log tests.test_recovery_policy tests.test_nutrition_policy tests.test_body_os_usable_interface tests.test_scheduler_energy_task_adjustment
```

预期：

```text
Ran 13 tests
OK
```

```powershell
python -m unittest tests.test_energy_policy tests.test_training_policy tests.test_body_os_garmin_context tests.test_garmin_bodyos_365d tests.test_daily_scheduler_garmin_energy
```

预期：

```text
Ran 24 tests
OK
```

```powershell
python -m unittest discover tests
```

预期：

```text
Ran 86 tests
OK
```

```powershell
python -m unittest discover "D:\个人混合管理系统\02_执行引擎（Engine）\输入解析引擎\tests"
```

预期：

```text
Ran 195 tests
OK
```

## 数据重建命令

如果 raw 数据更新，执行：

```powershell
python "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_bodyos_365d.py" --raw-input "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\raw_garmin_365d.json" --out "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\body_os_dataset_365d.json" --summary-out "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\body_os_garmin_summary.json" --today-out "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\body_os_today_energy.json" --runtime-energy-out "D:\个人混合管理系统\04_数据中心（Data）\运行状态（Runtime）\_energy_status.json"
```

如果要增量同步，优先使用：

```powershell
python "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_incremental_sync.py"
```

注意：真实 Garmin CN 网络同步路径尚未完成在线登录态首跑验证。首跑后必须检查 raw meta、清洗层和 `#身体` 输出。

## 命名约定

内部字段：

```text
body_battery_score
```

兼容别名：

```text
body_battery
```

用户展示：

```text
身体可用能量
```

不要再使用：

```text
精神电量
```

原因：Garmin Body Battery 更准确的语义是身体恢复状态和任务承载能力，不应直接等同精神状态。

## 用户目标

训练目标优先级：

```text
塑形/降脂/增肌 > 跑步能力维护 > 绝对力量提升
```

训练安排：

- 根据日程和活动精力灵活安排。
- 每周至少保留一天恢复。
- 力量训练由 Garmin 记录重量、次数、组数。
- 当前没有 RPE 或接近力竭记录。
- 暂不做复杂食物数据库。

## 后续路线

优先级建议：

1. Garmin CN 增量同步真实在线首跑验证。
2. 训练策略从 activityType 级升级到动作/肌群级 ← **已完成**。
3. 手动训练日志和 Garmin strength sets 数据做合并去重。
4. 营养模块再考虑食物数据库。
5. 阶段三以后再讨论 Level 3 自动改日历，并要求用户确认。

## 交接判断

可以迁移给别的 agent 的标准已经满足：

- 有明确数据契约。
- 有配置文件。
- 有可执行入口。
- 有策略模块。
- 有测试覆盖。
- 有验证命令。
- 有未完成风险说明。

新的 agent 接手时，不应重新安装 Garmin 依赖，不应重命名数据文件，不应把 raw 当最终事实源，不应自动修改用户日历。
