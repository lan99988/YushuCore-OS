---
name: recovery-system
description: "Body OS 恢复模块：当用户记录睡眠、酸痛、疲劳、压力、活动度，或需要判断是否降载/恢复时使用。触发词：#恢复、睡眠、酸痛、疲劳、压力、身体电量。"
agent_created: true
version: 1.0.0
---

# 恢复管理 (Recovery System)

> Body OS 的恢复约束模块。它决定今天能承受什么，而不是替代训练目标。

---

## 基础信息

| 项 | 值 |
|------|------|
| 名称 | 恢复管理（Recovery System） |
| 编号 | yushu_13 |
| 版本 | 1.0.0 |
| 状态 | Phase 1 设计稿 |
| 创建时间 | 2026-07-28 |
| 负责人 | 甲乙簿 |

## 功能定位

记录睡眠、酸痛、压力、静息心率、HRV、身体电量，并产出恢复/降载/可训练判断。

## 触发方式

`#恢复` / 睡眠 / 酸痛 / 疲劳 / 压力 / 身体电量 / readiness / 降载。

## 输入

- Energy 字段：sleep_hours、soreness、readiness_score、stress_level。
- Garmin 睡眠、心率、压力、Body Battery。
- 用户主观疲劳描述。

## 输出

恢复状态、降载建议、是否适合力量训练或 Zone2。

## 依赖

- yushu_10_身体总管_BodyController
- Energy Schema
- BodyMetrics Schema
- Garmin 7 天同步脚本

## 数据

Energy：每日状态输入；BodyMetrics：长期静息心率、HRV 趋势。

## 权限

- read：Energy、BodyMetrics、Garmin 映射 JSON。
- write：Energy/BodyMetrics（飞书表创建并确认后）。
- admin：无。

## 调用链

`#恢复` → BodyController → RecoverySystem → Energy/BodyMetrics。

## 测试

测试方式：

```bash
python -m unittest tests.test_garmin_bodyos_sync tests.test_body_os_contract -v
```

## 执行原则

1. 恢复差时优先保连续性，不硬推训练计划。
2. Garmin 指标只作为输入，不把 Garmin 字段名当业务字段。
3. readiness_score 缺失时，用睡眠、压力、身体电量综合估算。
