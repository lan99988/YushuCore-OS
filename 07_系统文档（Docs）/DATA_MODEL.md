# 数据模型（DATA_MODEL）

> 配套：`SYSTEM_BLUEPRINT.md` · `ARCHITECTURE.md` · `SKILL_INDEX.md` · `WORKFLOW.md` · `DECISION_LOG.md`
> 最后更新：2026-08-03。本文是"数据地图"——有哪些表、字段定义在哪、BodyOS 三层契约。

---

## 一、核心原则

1. **飞书 Base 是唯一事实源**。本地 `04_数据中心` 只存：① Schema 定义（JSON，版本化）② Runtime 状态（推送/同步中间产物）③ 系统配置。不维护本地主数据库。
2. **Schema 中心（字段级定义的唯一来源）** = `04_数据中心（Data）/数据模型（Schema）/`。系统注册表（yushu_00）只登记"有哪些资产 / 去哪看定义 / 谁使用"，**不维护字段**。
3. **先定义 Schema，再写代码**。新增 Skill 第一步在此定义模型。
4. 字段命名：JSON 用英文（`title`/`status`），中文名作 `中文名称` 字段对应飞书真实字段。

---

## 二、飞书 Base 表速查（18 数据资产 + 1 总览）

Base Token：`TtzIboiQQaPgfVszO2vc56wLnof` · 操作身份：`--as=user` · 主人 open_id：`ou_adf2c637b6ddd79c0af429ad5da3a746`

| 编号 | 模型 | 中文名 | 飞书表 ID | Schema | 状态 |
|------|------|--------|-----------|--------|------|
| 0 | — | 系统总览（根表） | `tblPxhRiJg8SfXxD` | — | 非业务，不计入 |
| 01 | Task | 任务 | `tblNQCB4pn6Rso4a` | ✅ | 业务 |
| 02 | Idea | 灵感 | `tblx1ZaQGwXvoJhj` | ✅ | 业务 |
| 03 | Bug | 问题 | `tblPpPputYMACtQ5` | ✅ | 业务 |
| 04 | Energy | 精力状态 | （设计稿，无专属表） | ✅ | 状态数据 |
| 05 | Habit | 习惯 | `tblSRdG4P3XE75Ll` | ✅ | 业务 |
| 06 | DeepWork | 深度工作 | `tblmAz37er4CEbL0` | ✅ | 业务 |
| 07 | SubjectProgress | 科目进度基线 | `tblQnjCO03WjQ7GC` | ✅ | 只读基线 |
| 08 | Competition | 比赛 | `tblKPdoxMHy7FuV7` | ✅ | 业务 |
| 09 | Finance | 财务流水 | `tblPFKBGubeIYsfm` | ⏳ | 业务 |
| 10 | Social | 社交关系 | `tblt7uTkIcLhH7bs` | ⏳ | 业务 |
| 11 | Creation | 创作素材 | `tbl99pDAlTIDu7f5` | ⏳ | 业务 |
| 12 | Knowledge | 知识笔记 | `tblgtdx4h0EJjRrh` | ⏳ | 知识 |
| 13 | MultiRoundTracking | 多轮次追踪 | `tblJmOfDHV83RsIg` | ⏳ | 分析 |
| 14 | Project | 项目管理 | `tblCnVUb327SQ9mS` | ⏳ | 业务 |
| 15 | StockStrategy | 股市策略 | `tblVWrqa8fNCcCjA` | ⏳ | 专业 |
| 16 | TrainingLog | 训练记录 | （待创建） | ✅ | 业务 |
| 17 | NutritionLog | 营养记录 | （待创建） | ✅ | 业务 |
| 18 | BodyMetrics | 身体指标 | （待创建） | ✅ | 趋势 |

> ✅ = 第一批 8 个（Task/Idea/Bug/Energy/Habit/DeepWork/SubjectProgress/Competition）Schema 已完成；⏳ = 其余 7 个待补。Energy/TrainingLog/NutritionLog/BodyMetrics 暂无飞书专属表。

**共享枚举（多选下拉）**：`考研 / 项目A / 项目B / 项目C / 项目D / 生活区 / 全局 / 考试`

---

## 三、Schema JSON 标准结构

```json
{
  "model": "Task",
  "中文名称": "任务",
  "version": "1.0",
  "description": "模型说明",
  "source_skill": ["yushu_01_输入解析引擎_Router", "yushu_04_飞书操作_Processor"],
  "feishu_table": { "id": "tblNQCB4pn6Rso4a", "name": "执行库" },
  "fields": [
    { "name": "title", "中文名称": "标题", "type": "text", "required": true },
    { "name": "status", "中文名称": "状态", "type": "enum", "options": ["待处理","进行中","已完成","已取消"] }
  ]
}
```

**字段类型归一化**：`text` · `enum`(select) · `datetime` · `number` · `boolean`(checkbox) · `attachment` · `formula`(computed) · `auto_number`(computed) · `system_timestamp`(created/updated_at, computed)。

> 版本记录见 `04_数据中心（Data）/数据版本（Version）/版本记录.md`。

---

## 四、BodyOS Garmin 数据契约（2026-07-29 固化）

身体域三层数据，文件名**不改**：

| 层 | 文件 | 角色 | 说明 |
|----|------|------|------|
| 镜像层 | `raw_garmin_365d.json` | 非事实源（Garmin 拉取镜像） | `meta.schema_version=1.0` |
| 清洗层 | `body_os_dataset_365d.json` | **统计唯一入口** | 派生指标，所有查询读这里 |
| 运行态 | `body_os_today_energy.json` + `_energy_status.json` | 当日精力 | 每日生成 |

- **valid_start 唯一来源**：`04_数据中心（Data）/系统配置（Config）/body_os_config.json`（回退 2025-12-11）。
- **增量同步**：`garmin_incremental_sync.py`（14 天窗口，`activityId` 去重）。
- **命名约定**：内部 `body_battery_score`（`body_battery` 兼容别名），展示为「身体可用能量」，**禁用「精神电量」**。
- **排程分级**：L1 建议 / L2 内部优先级 / L3 改日历需确认（当前仅 L1）；手动 `#精力` 优先于 Garmin。
- **阶段二待做**：C1 `energy_policy` + C2 `training_policy`（activityType 级规则）。

---

## 五、关键本地 JSON 文件（Runtime / Config）

| 文件 | 位置 | 作用 |
|------|------|------|
| `_schedule_config.json` | 运行状态（Runtime） | 排程配置（时段/可用时长） |
| `_calendar_log.json` | 运行状态（Runtime） | 已同步日历事件日志 |
| `_sync_result.json` | 运行状态（Runtime） | 同步结果 |
| `_analytics.db` | 运行状态（Runtime） | analytics 本地 SQLite |
| `_overflow_tracker.json` | 运行状态（Runtime） | 超载顺延追踪 |
| `_energy_status.json` | 运行状态（Runtime） | 当日精力状态 |
| `body_os_config.json` | 系统配置（Config） | BodyOS 配置（valid_start 源） |
| `manual_training_log.json` | 运行状态（Runtime） | 手动训练记录 |

> ⚠️ `运行状态（Runtime）/`（含 `_*.json`）必须进 `.gitignore`，绝不提交（含状态/中间产物）。
