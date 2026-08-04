# BodyOS Garmin Energy 完整实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans 或等价的逐任务执行流程。每个 agent 只能在自己负责的文件范围内修改，修改前先读本文件、相关测试和目标代码。

**Goal:** 把 Garmin 中国区近一年身体数据稳定接入 Body OS，并让「身体可用能量」参与当天精神状态、学习负载和每日排程判断。

**Architecture:** Garmin 只作为传感器层，原始数据保存在 raw JSON，项目层通过 Body OS 映射数据集消费。每日排程只读取运行态 `_energy_status.json`，不直接耦合 Garmin API。

### 三层数据契约（2026-07-29 固化，文件名保留现名）

```text
Garmin API
  ↓
raw_garmin_365d.json           # 原始镜像层：只追加/窗口刷新，不手工改字段，不是业务事实源
  ↓
body_os_dataset_365d.json      # 清洗数据层：统计、趋势、训练/恢复分析唯一读取入口
  ↓
body_os_today_energy.json      # 当日身体上下文层：给 Agent 判断今日状态
_energy_status.json            # 排程 runtime 层：给 daily_scheduler 消费
```

- raw `meta` 含 `schema_version`（当前 `1.0`）、`sync_time`、`source`，支持未来字段迁移。
- 增量同步入口：`garmin_incremental_sync.py`（默认 14 天窗口，按日期+activityId 去重合并，合并后自动重建下游三层）。
- 有效起点不再硬编码：唯一来源 `04_数据中心（Data）\系统配置（Config）\body_os_config.json` 的 `body_data.valid_start`，配置缺失时回退 `2025-12-11`。
- 命名契约：内部字段 `body_battery_score`（保留 `body_battery` 兼容别名），用户展示统一「身体可用能量」，禁止「精神电量」措辞。精神状态是 body_battery_score + sleep + stress + readiness 的综合派生，语义为"身体恢复状态 + 任务承载能力"。
- 排程控制分级（`policy.scheduler_control_level`）：L1 只建议 / L2 调整内部任务优先级 / L3 改真实日历需用户确认。当前 L1。
- 手动 `#精力` 优先于 Garmin 自动状态（`policy.manual_energy_overrides_garmin=true`）。

### 阶段划分（2026-07-29 调整后）

- 阶段一（已完成）：A1/A2/B1/B2 —— Garmin 数据稳定，配置化起点，schema 版本号，身体可用能量语义。
- 阶段二（已完成）：C1 `energy_policy.py`（身体能量→学习负载）+ C2 `training_policy.py`（身体状态→训练建议，先做 activityType 级规则：连续3天力量→降量、48h 内重复力量→提醒、7日负荷突增40%→警告；肌群级规则留接口）。目标：系统能回答"今天身体状态怎么样"。
- 阶段三：D 排程集成（按控制分级消费 C 输出）。目标：回答"今天应该怎么安排"。

**Tech Stack:** Python 3.13、Garmin CN Web `gc-api`、Playwright/Chrome 已登录 profile、unittest、JSON 文件数据集、现有输入解析引擎和每日排程引擎。

---

## 1. 当前系统状态

当前已经完成到 Garmin CN 数据可用、365 天 raw 数据生成、Body OS 映射、身体可用能量派生精神状态、排程 runtime 写入这一步。

关键文件：

- `D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\raw_garmin_365d.json`
- `D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\body_os_dataset_365d.json`
- `D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\body_os_garmin_summary.json`
- `D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\body_os_today_energy.json`
- `D:\个人混合管理系统\04_数据中心（Data）\运行状态（Runtime）\_energy_status.json`
- `D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_sync_365d.py`
- `D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_bodyos_365d.py`
- `D:\个人混合管理系统\02_执行引擎（Engine）\输入解析引擎\handlers\body_os.py`
- `D:\个人混合管理系统\02_执行引擎（Engine）\每日排程引擎\daily_scheduler.py`

当前数据口径：

- raw 抓取范围：`2025-07-30..2026-07-29`
- 有效统计起点：`2025-12-11`
- 有效观察天数：`227`
- `2025-12-11` 前排除：`134` 天
- 有效期内无统计日排除：`4` 天
- 最新有效 Garmin 日：`2026-07-28`
- 当前身体可用能量：`18`
- 当前派生状态：`耗竭 / 恢复维护 / energy_coefficient=0.65`

必须保留的统计规则：

- `2025-12-11` 前的数据只能作为原始证据保存，不能进入项目统计。
- 有效期内某天没有统计信息，必须排除，不能按 0 进入均值。
- BMR、默认总热量、空数组、错误响应不能算有效统计。
- 身体可用能量用于当天精神状态判断时，优先看最新有效日，不用年平均做当天判断。
- 如果今天无有效统计，要明确标注“使用最新有效 Garmin 日”，不能伪装成今天数据。

安全规则：

- 不得把 Garmin 邮箱、密码、token、cookie 写入文档、日志或测试。
- 不重复安装 `garmin-mcp-server` 和 `garminconnect`。
- Garmin 中国区可用路线是 `https://connect.garmin.cn/gc-api/...`，不是直接依赖 `.com` API。
- raw 数据可以保留，但派生层只能读取清洗后的项目数据。

---

## 2. 总体分工

建议并行安排 6 个 agent。每个 agent 完成后必须提交变更摘要、运行命令、测试结果和风险说明。

| Agent | 负责范围 | 可修改文件 |
|---|---|---|
| A 数据同步 Agent | 稳定 Garmin CN 抓取和增量同步 | `08_工具脚本（Tools）\身体管理\garmin_sync_365d.py`、新增同步测试 |
| B 数据映射 Agent | 校准 Body OS 数据集、空日排除、身体可用能量语义 | `garmin_bodyos_365d.py`、`tests\test_garmin_bodyos_365d.py` |
| C 精力策略 Agent | 精神状态、学习负载、任务策略规则 | `garmin_bodyos_365d.py`，必要时拆出 `energy_policy.py` |
| D 排程集成 Agent | 让每日排程消费 Garmin 精力上下文 | `daily_scheduler.py`、`tests\test_daily_scheduler_garmin_energy.py` |
| E 入口展示 Agent | `#身体`、`#恢复`、`#精力` 的用户可读反馈 | `handlers\body_os.py`、`handlers\energy.py`、输入解析测试 |
| F QA/文档 Agent | 回归测试、运行手册、交接文档 | `07_系统文档（Docs）`、测试清单 |

协作顺序：

1. A 和 B 先确认数据来源与口径。
2. C 在 B 的字段稳定后维护策略规则。
3. D 消费 C 输出的 runtime 字段。
4. E 在 D 的字段稳定后做用户入口展示。
5. F 最后跑完整测试并更新交接。

---

## 3. 数据同步实施

### Task A1: 固化 Garmin CN 同步命令

**目标：** 让后续 agent 能用一个命令刷新近一年 raw 数据。

**方法：**

运行：

```powershell
python "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_sync_365d.py" --out "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\raw_garmin_365d.json"
```

如果脚本要求日期参数，则使用：

```powershell
python "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_sync_365d.py" --start 2025-07-30 --end 2026-07-29 --out "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\raw_garmin_365d.json"
```

验收：

- raw JSON 的 `meta.start`、`meta.end` 正确。
- `body_battery`、`daily_summary`、`sleep`、`stress`、`heart_rate` 至少存在数组。
- 网络失败时 JSON 中保留错误项，但映射层必须过滤 `error`。
- 不输出任何敏感凭证。

### Task A2: 增量同步设计

**目标：** 后续每日只抓最近 14 天，再合并到 365 天 raw，减少请求量。

建议新增脚本：

- `D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_incremental_sync.py`

逻辑：

1. 读取现有 `raw_garmin_365d.json`。
2. 计算刷新窗口：`today - 14 days` 到 `today`。
3. 调用现有 client 抓取窗口数据。
4. 按日期和 activity id 去重合并。
5. 写回 raw 文件。
6. 重新调用映射脚本生成项目数据和 runtime。

已实现：`garmin_incremental_sync.py`（2026-07-29）。要点：

- 窗口内旧数据整体替换为新抓取，窗口外历史保留；无日期的陈旧 error 条目丢弃。
- activities 按 `activityId` 去重，新数据覆盖旧数据。
- 合并后 meta 写入 `schema_version=1.0`、`sync_time`、`source=garmin`、`last_incremental_window`。
- 默认合并后自动重建清洗层+运行态（`--skip-remap` 可跳过）。

验收测试：

```powershell
python -m unittest tests.test_garmin_sync_365d tests.test_garmin_incremental_sync
```

---

## 4. 数据映射与校准实施

### Task B1: 保持有效起点和空日排除

**目标：** 任何统计都不能被无效日期污染。

当前核心函数：

- `build_body_os_dataset()`
- `_has_day_statistics()`
- `summarize_dataset()`

必须保持（2026-07-29 起改为配置驱动）：

```python
# 唯一来源：04_数据中心（Data）\系统配置（Config）\body_os_config.json
# body_data.valid_start = "2025-12-11"
# 代码通过 resolve_valid_start() 读取，配置缺失时回退 _FALLBACK_VALID_START
```

有效统计信号包括：

- 步数大于 0
- 睡眠秒数非空且非 0
- 静息心率非空
- 压力不为 `None` 且不为 `-1`
- 身体可用能量字段非空
- HRV 非空
- 当天有训练活动
- 强度分钟、楼层、血氧等非空有效指标

无效信号：

- 只有 BMR 或默认总热量
- 空数组
- `{"error": ...}`
- 睡眠秒数为 `0`
- 压力 `-1`

验收：

```powershell
python -m unittest tests.test_garmin_bodyos_365d
```

### Task B2: 审核身体可用能量语义

**目标：** 确认 `body_battery_score` 映射代表当天「身体可用能量」（身体恢复状态+任务承载能力），不直接等同精神状态，且不误用 `charged/drained`。内部字段 `body_battery_score` 为正式命名，`body_battery` 保留为兼容别名。

当前优先级：

1. `daily_summary.bodyBatteryMostRecentValue`
2. `daily_summary.bodyBatteryHighestValue`
3. `daily_summary.bodyBatteryAtWakeTime`
4. `body_battery.bodyBattery`
5. `body_battery.value`
6. `body_battery.charged`

后续 agent 要检查最近 30 天 raw 样本：

```powershell
python - <<'PY'
import json
from pathlib import Path
p = Path(r"D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\raw_garmin_365d.json")
raw = json.loads(p.read_text(encoding="utf-8"))
for item in raw.get("daily_summary", [])[-30:]:
    print(item.get("calendarDate"), item.get("bodyBatteryMostRecentValue"), item.get("bodyBatteryHighestValue"), item.get("bodyBatteryAtWakeTime"))
PY
```

如果 `bodyBatteryMostRecentValue` 长期异常缺失或长期为极低值，要增加 `bodyBatteryAtWakeTime`、`highest`、`mostRecent` 三字段同时输出，避免单值误判。

---

## 5. Body Intelligence 策略实施

### Task C1: `energy_policy.py` 身体可用能量到学习负载规则

**目标：** 让系统每天能回答“今天适合高强度学习、标准推进、轻任务，还是恢复维护”。

当前规则：

| 条件 | mental_state | study_load | status | coefficient |
|---|---|---|---|---|
| `body_battery < 20` | `depleted` | `recovery` | `差` | `0.65` |
| `body_battery < 40` 或 `sleep_hours < 6` 或 `readiness < 45` 或 `stress >= 65` | `low` | `light` | `差` | `0.8` |
| `body_battery >= 70` 且 `readiness >= 65` 且 `sleep >= 7` 且压力不高 | `high` | `deep` | `好` | `1.15` |
| 其他 | `normal` | `standard` | `一般` | `1.0` |

关键原则：

- 身体可用能量是刹车项：低于 20 时，不允许 readiness 把当天抬成高负载。
- readiness 是综合参考，不是唯一判断。
- sleep、stress 是保护项。
- `energy_coefficient` 只影响可用时长，不直接删除任务。

已实现：`D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\energy_policy.py`

验收：

```powershell
python -m unittest tests.test_energy_policy
```

### Task C2: `training_policy.py` activityType 级训练建议

**目标：** 让系统能回答“今天训练要不要降载”，先基于 Garmin 稳定可得的 `activity_type`、训练日期和 `training_load`，不依赖尚未确认的肌群数据。

已实现：`D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\training_policy.py`

当前规则：

- 身体可用能量耗竭 / `study_load=recovery`：训练建议 `recovery`，避免高强度力量和速度课。
- 连续 3 天力量训练：训练建议 `deload`，提示降低训练量。
- 48 小时内已有力量训练：训练建议 `caution`，提示避免继续堆高负荷。
- 近 7 日训练负荷较前 7 日上升超过 40%：训练建议 `caution`。
- 当前仅基于 `activityType` 判断训练频率，尚未细分肌群。

输出位置：

- `body_os_dataset_365d.json.today_training_context`
- `body_os_garmin_summary.json.today_training_context`
- `#身体` dry-run 展示中的“训练建议”

验收：

```powershell
python -m unittest tests.test_training_policy tests.test_garmin_bodyos_365d tests.test_body_os_garmin_context
```

---

## 6. 每日排程集成实施

### Task D1: 排程读取扩展精力上下文

**目标：** 每日排程在不耦合 Garmin 的前提下使用身体可用能量结果。

当前读取入口：

- `load_energy_context(today=None)`
- `load_energy_status(today=None)`
- `resolve_energy_multiplier(energy_context, config)`

排程优先级：

1. 用户手动配置 `_schedule_config.json` 的 `精力系数`。
2. Garmin runtime 中的 `energy_coefficient`。
3. 旧的 `status=差/好` 默认系数。
4. 默认 `1.0`。

验收：

```powershell
python -m unittest tests.test_daily_scheduler_garmin_energy
```

### Task D2: 学习任务负载调整

**目标：** 不只缩短总可用时长，还要根据 `study_load` 调整任务类型。

建议实现：

- `study_load=deep`：高效段优先安排高精力、高权重、硬骨头任务。
- `study_load=standard`：保持当前排序。
- `study_load=light`：减少高精力任务，优先复习、整理、低估时任务。
- `study_load=recovery`：只安排必要 P0、维护型任务和低精力任务，高精力任务进入 overflow 或建议改期。

建议新增纯函数：

```python
def adjust_tasks_for_energy_policy(tasks, energy_context):
    ...
```

放置位置：

- 短期：`daily_scheduler.py`
- 中期：拆到 `02_执行引擎（Engine）\每日排程引擎\energy_policy.py`

测试要求：

- `recovery` 不安排普通高精力任务。
- P0 任务即使 recovery 也保留，但标注风险。
- 手动配置仍优先。

---

## 7. 用户入口实施

### Task E1: `#身体` 展示

**目标：** 用户输入 `#身体 今天适合怎么安排学习` 时，能看到 Garmin 身体可用能量判断。

当前入口：

```powershell
python "D:\个人混合管理系统\02_执行引擎（Engine）\输入解析引擎\input_parser.py" "#身体 今天适合怎么安排学习" --dry-run
```

预期包含：

- Garmin 统计日期范围
- 有效观察天数
- 排除无统计日数量
- 最新有效 Garmin 日
- 如果今天无数据，明确提示今天未纳入判断
- 身体可用能量
- 精神状态
- 学习负载
- 建议依据

验收：

```powershell
python -m unittest tests.test_body_os_garmin_context
```

### Task E2: `#精力` 与 Garmin 的关系

**目标：** 保留手动 `#精力`，并定义和 Garmin 自动状态的覆盖关系。

建议规则：

- 用户当天手动输入 `#精力` 后，runtime `source=manual`。
- Garmin 同步默认不覆盖同一天的手动 `source=manual`，除非命令加 `--force-runtime`.
- 如果没有手动精力记录，Garmin 自动写入 runtime。

建议测试：

- 手动 `#精力 很好` 写入后，Garmin 同步不覆盖。
- `--force-runtime` 可以覆盖。
- 排程读取 manual 时不使用 Garmin coefficient。

---

## 8. 自动化实施

### Task F1: 每日同步流水线

**目标：** 每天早上排程前刷新 Garmin 数据和精力状态。

推荐顺序：

1. 运行 Garmin 增量同步。
2. 生成 Body OS 映射数据。
3. 写入 `body_os_today_energy.json`。
4. 写入 `_energy_status.json`。
5. 运行每日排程。

手动命令模板：

```powershell
python "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_sync_365d.py" --out "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\raw_garmin_365d.json"
python "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\garmin_bodyos_365d.py" --raw-input "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\raw_garmin_365d.json" --out "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\body_os_dataset_365d.json" --summary-out "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\body_os_garmin_summary.json" --today-out "D:\个人混合管理系统\08_工具脚本（Tools）\身体管理\body_os_today_energy.json" --runtime-energy-out "D:\个人混合管理系统\04_数据中心（Data）\运行状态（Runtime）\_energy_status.json"
python "D:\个人混合管理系统\02_执行引擎（Engine）\每日排程引擎\daily_scheduler.py" --dry-run
```

后续可以接入系统自动化，但自动化前必须先验证：

```powershell
python -m unittest tests.test_body_os_garmin_context tests.test_garmin_bodyos_365d tests.test_garmin_sync_365d tests.test_garmin_cn_discover tests.test_garmin_bodyos_sync tests.test_body_os_contract tests.test_daily_scheduler_garmin_energy
```

---

## 9. 质量门禁

任何 agent 完成任务后必须跑对应测试，最后由 QA agent 跑完整回归：

```powershell
python -m unittest tests.test_body_os_garmin_context tests.test_garmin_bodyos_365d tests.test_garmin_sync_365d tests.test_garmin_incremental_sync tests.test_garmin_cn_discover tests.test_garmin_bodyos_sync tests.test_body_os_contract tests.test_daily_scheduler_garmin_energy
```

还要跑实际入口：

```powershell
python "D:\个人混合管理系统\02_执行引擎（Engine）\输入解析引擎\input_parser.py" "#身体 今天适合怎么安排学习" --dry-run
```

检查输出必须包含：

- `Garmin近一年`
- `无统计日已排除`
- `最新有效Garmin日`
- `精神状态`
- `学习负载`
- `身体可用能量`

---

## 10. 完成标准

这个系统阶段完成时，必须满足：

1. 能稳定刷新 Garmin CN 数据。
2. raw 数据和项目映射数据分层保存。
3. `2025-12-11` 前数据不进入统计。
4. 有效期内无统计日排除，不影响均值。
5. 身体可用能量参与当天精神状态判断。
6. 最新有效 Garmin 日和请求日期不一致时，界面明确说明。
7. 每日排程能读取 `energy_coefficient`。
8. 用户手动 `#精力` 和 Garmin 自动精力有明确覆盖规则。
9. 所有相关测试通过。
10. 文档不包含任何 Garmin 凭证。

---

## 11. 推荐下一步

最值得优先派给其他 agent 的任务是 D2 和 E2：

- D2 让 `study_load=recovery/light/deep` 真正影响任务筛选和时段分配。
- E2 明确手动 `#精力` 和 Garmin 自动同步的覆盖规则，避免自动数据覆盖用户主观判断。

这两个做完后，身体可用能量就不只是“展示信息”，而会真正参与每天学习计划和事务安排。
