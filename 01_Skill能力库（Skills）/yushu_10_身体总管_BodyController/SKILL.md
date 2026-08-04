---
name: body-controller
description: "Body OS 唯一入口：当用户询问身体状态、今天练什么、训练/营养/恢复综合决策、Garmin 数据解读时使用。触发词：#身体、Body OS、今天适合练什么、力量还是跑步、恢复还是降载。"
agent_created: true
version: 1.0.0
---

# 身体总管 (Body Controller)

> Body OS 的决策入口与调度层。用户不需要思考调用哪个身体子模块，所有身体相关问题先从这里进入。

---

## 基础信息

| 项 | 值 |
|------|------|
| 名称 | 身体总管（Body Controller） |
| 编号 | yushu_10 |
| 版本 | 1.0.0 |
| 状态 | Phase 1 设计稿 |
| 创建时间 | 2026-07-28 |
| 负责人 | 甲乙簿 |

## 功能定位

统一接收身体管理输入，综合训练、营养、恢复与身体指标，输出今天的行动建议：力量训练、Zone2、恢复、降载或记录补充。

## 触发方式

`#身体` / `Body OS` / 今天适合练什么 / 身体状态 / 训练建议 / 力量还是跑步 / 恢复还是降载。

## 输入

- 用户自然语言身体状态与训练问题。
- Garmin 7 天映射结果 `body_os_mapped_7d.json`。
- Energy、TrainingLog、NutritionLog、BodyMetrics 记录。

## 输出

`{ok, type:"body_os", message}`，包含今日建议、理由、需要记录或补充的数据。

## 依赖

- yushu_11_力量塑形_StrengthSystem
- yushu_12_营养管理_NutritionSystem
- yushu_13_恢复管理_RecoverySystem
- yushu_14_身体分析_BodyAnalytics
- `08_工具脚本（Tools）/身体管理/garmin_sync_7d.py`

## 数据

- TrainingLog：训练与跑步统一记录。
- NutritionLog：蛋白质、饮水、补剂。
- BodyMetrics：体重、体脂、围度、静息心率、HRV。
- Energy：睡眠、酸痛、压力、准备度。

## 权限

- read：Body OS 四类 Schema 与 Garmin 映射 JSON。
- write：Phase 1 仅在用户确认后写入飞书 Base；表未创建前只生成本地 JSON。
- admin：无。

## 调用链

`#身体` → input_parser router → body_os handler → BodyController → 子模块 → Schema → 飞书 Base/本地 JSON。

## 测试

测试方式：

```bash
python -m unittest tests.test_body_os_contract tests.test_garmin_bodyos_sync -v
python -m unittest 输入解析引擎.tests.test_router -v
```

## 决策规则

1. 恢复不足优先保护长期连续性：睡眠不足、压力高、身体电量低时推荐恢复或降载。
2. 力量训练是核心目标：准备度足够时优先执行力量计划。
3. 跑步是心肺底座：不独立成 Skill，不独立成表，作为 TrainingLog 的 `activity_type=running`。
4. Garmin 只提供传感器输入：不让设备 API 形状渗透到业务字段。
