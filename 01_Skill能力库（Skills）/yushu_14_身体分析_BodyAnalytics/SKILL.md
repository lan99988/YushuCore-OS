---
name: body-analytics
description: "Body OS 分析模块：当用户查看身体趋势、训练负荷、体重体脂围度变化、Body Score 或 7 天 Garmin 映射摘要时使用。触发词：#体测、身体趋势、Body Score、训练负荷。"
agent_created: true
version: 1.0.0
---

# 身体分析 (Body Analytics)

> Body OS 的趋势分析模块。它负责解释长期变化，不直接接管每日执行入口。

---

## 基础信息

| 项 | 值 |
|------|------|
| 名称 | 身体分析（Body Analytics） |
| 编号 | yushu_14 |
| 版本 | 1.0.0 |
| 状态 | Phase 1 设计稿 |
| 创建时间 | 2026-07-28 |
| 负责人 | 甲乙簿 |

## 功能定位

汇总 TrainingLog、NutritionLog、BodyMetrics、Energy，输出趋势、异常、Body Score 与可行动建议。

## 触发方式

`#体测` / 身体趋势 / 体重变化 / 体脂 / 围度 / Body Score / 训练负荷 / Garmin 7 天。

## 输入

- TrainingLog：训练频率、负荷、跑步距离。
- NutritionLog：蛋白质与饮水执行。
- BodyMetrics：体重、体脂、围度、静息心率、HRV。
- Energy：睡眠、压力、准备度。

## 输出

身体趋势摘要、7 天状态摘要、Body Score、下一步调整建议。

## 依赖

- yushu_10_身体总管_BodyController
- TrainingLog Schema
- NutritionLog Schema
- BodyMetrics Schema
- Energy Schema

## 数据

四类 Body OS Schema 均可读；Phase 1 不直接写业务表，除非用户明确记录体测数据。

## 权限

- read：TrainingLog、NutritionLog、BodyMetrics、Energy。
- write：BodyMetrics（飞书表创建并确认后）。
- admin：无。

## 调用链

`#体测` → BodyController → BodyAnalytics → BodyMetrics/趋势摘要。

## 测试

测试方式：

```bash
python -m unittest tests.test_body_os_contract tests.test_garmin_bodyos_sync -v
```

## 分析原则

1. 趋势优先于单日波动。
2. Body Score 必须说明构成，不输出神秘分数。
3. 指标不足时先列缺口，不编造结论。
