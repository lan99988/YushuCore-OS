---
name: nutrition-system
description: "Body OS 营养模块：当用户记录蛋白质、饮水、补剂，或询问训练日营养策略、恢复期饮食时使用。触发词：#营养、蛋白质、饮水、肌酸、补剂。"
agent_created: true
version: 1.0.0
---

# 营养管理 (Nutrition System)

> Body OS 的低负担营养模块。Phase 1 只追踪蛋白质、饮水与补剂执行。

---

## 基础信息

| 项 | 值 |
|------|------|
| 名称 | 营养管理（Nutrition System） |
| 编号 | yushu_12 |
| 版本 | 1.0.0 |
| 状态 | Phase 1 设计稿 |
| 创建时间 | 2026-07-28 |
| 负责人 | 甲乙簿 |

## 功能定位

把营养追踪压到足够小：每天只要求记录蛋白质克数，可选记录饮水和补剂。

## 触发方式

`#营养` / 蛋白质 / 饮水 / 肌酸 / 补剂 / 训练日吃什么。

## 输入

- 蛋白质克数。
- 饮水毫升。
- 补剂执行情况。
- 今日训练类型与恢复状态。

## 输出

NutritionLog 记录草稿、蛋白质差额、训练日前后营养建议。

## 依赖

- yushu_10_身体总管_BodyController
- yushu_11_力量塑形_StrengthSystem
- NutritionLog Schema

## 数据

NutritionLog：`protein_g` 为 Phase 1 核心字段；补剂不独立成 Skill，写入 `supplements`。

## 权限

- read：NutritionLog、TrainingLog。
- write：NutritionLog（飞书表创建并确认后）。
- admin：无。

## 调用链

`#营养` → BodyController → NutritionSystem → NutritionLog。

## 测试

测试方式：

```bash
python -m unittest tests.test_body_os_contract -v
```

## 执行原则

1. 不追完整热量系统，先保证蛋白质达标。
2. 补剂只记录执行，不拆成独立模块。
3. 缺少体重目标时，不臆测蛋白目标，先提示补充体重或目标。
