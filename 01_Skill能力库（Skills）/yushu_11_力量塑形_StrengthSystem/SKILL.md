---
name: strength-system
description: "Body OS 力量塑形模块：当用户记录力量训练、规划训练课、调整渐进超负荷、处理跑步与力量训练冲突时使用。触发词：#训练、力量、塑形、卧推、深蹲、硬拉、跑步记录。"
agent_created: true
version: 1.0.0
---

# 力量塑形 (Strength System)

> Body OS 的训练执行模块。力量训练/塑形是核心；中长跑作为心肺底座并入同一训练记录。

---

## 基础信息

| 项 | 值 |
|------|------|
| 名称 | 力量塑形（Strength System） |
| 编号 | yushu_11 |
| 版本 | 1.0.0 |
| 状态 | Phase 1 设计稿 |
| 创建时间 | 2026-07-28 |
| 负责人 | 甲乙簿 |

## 功能定位

维护训练计划、训练记录、训练容量、RPE 与渐进超负荷。跑步不独立建模，统一进入 TrainingLog。

## 触发方式

`#训练` / 力量 / 塑形 / 卧推 / 深蹲 / 硬拉 / 引体 / Zone2 / 跑步记录。

## 输入

- 手动训练记录。
- Garmin 活动记录。
- BodyController 给出的今日训练方向。
- RecoverySystem 给出的恢复约束。

## 输出

训练记录草稿、训练建议、降载建议、下一次训练重点。

## 依赖

- yushu_10_身体总管_BodyController
- yushu_13_恢复管理_RecoverySystem
- TrainingLog Schema

## 数据

TrainingLog：`activity_type` 区分 `strength/running/mobility/other`；力量动作明细先用 JSON 文本保存在 `exercises`。

## 权限

- read：TrainingLog、Energy。
- write：TrainingLog（飞书表创建并确认后）。
- admin：无。

## 调用链

`#训练` → BodyController → StrengthSystem → TrainingLog。

## 测试

测试方式：

```bash
python -m unittest tests.test_body_os_contract -v
```

## 执行原则

1. 每次只推动一个训练目标：容量、强度、技术或恢复。
2. RPE 高且恢复差时不追求渐进超负荷。
3. 跑步记录写入 TrainingLog，不创建 Running Skill/Table。
