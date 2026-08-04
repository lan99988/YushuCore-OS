# 运行流程（WORKFLOW）

> 配套：`SYSTEM_BLUEPRINT.md` · `ARCHITECTURE.md` · `DATA_MODEL.md` · `SKILL_INDEX.md` · `DECISION_LOG.md`
> 最后更新：2026-08-03。本文是"动态行为"层——系统运行起来时发生什么。

---

## 一、一次 `#` 指令的完整生命周期（标准记录路径）

```
1. 用户输入：  #任务 做数学真题2010 【项目：数学二】【精力：高】【耗时：120分钟】
2. 入口：      main.py (CLI 解析) → router.dispatch(raw_text)
3. 路由：      _resolve_route_key()
                 → detect_prefix 命中 "执行库" → route_key=None（标准路径）
4. 处理：      _call_standard → handlers/standard_record.handle_standard_record()
                 Step2 提取变量：extract_variables()  → {project, energy, duration, ...}
                 Step3 主内容：  extract_main_content() → "做数学真题2010"
                 Step4 建记录：  build_record(table_name, title, vars)
5. 写入：      yushu_04 飞书操作 Processor → lark-cli record-upsert → 执行库(tblNQCB4pn6Rso4a)
6. 输出：      _format_output(result) → print（含详情块）
   （--dry-run 时额外打印 目标表/标题/变量/记录 JSON，不写库）
```

**特殊指令路径**：路由命中 `ROUTES` 表（如 `#习惯`→`habit`、`#身体`→`body_os`）→ 对应 handler 直接处理 → `sys.exit(0)`。

---

## 二、输入解析引擎 5 步（Step2-5 内部）

```
Step2  检测前缀  detect_prefix        → 决定目标表 / 是否特殊分支
Step3  提取变量  extract_variables     → 【项目】【精力】【耗时】【截止】…
Step4  建记录    build_record          → 组装飞书字段 dict
Step5a 入口      main.py → dispatch    → CLI 解析 + 分发（已迁出旧 main）
Step5b shim      input_parser.py       → from main import main（兼容旧链）
        （业务 handler 已 17/17 迁移并冻结；旧 2395 行留作 input_parser_old.py 基准）
```

---

## 三、每日排程推送流（07:00 automation）

```
每日 07:00
  → daily_scheduler.py
       读 18 张表（执行库/灵感/Bug/习惯/深度/科目进度/比赛/财务/社交/创作/知识…）
       排程算法：
         ① 权重分排序（P0>P1>P2>P3）
         ② 同权重按截止日期升序
         ③ 精力等级匹配时段（高→09:00-11:30 黄金段）
         ④ 超载顺延（累计耗时>可用时长 → 低权重顺延次日）
       生成推送文本（核心事件 + 时间轴 + 习惯专区 + 4DX 计分板 + 社交/财务概览）
  → calendar_sync.py
       对每个学习时段 +freebusy 查冲突 → +create 写飞书日历（🔴高/🟡中/🟢低）
       日志写 runtime/_calendar_log.json
  → lark-cli im +messages-send → 推送给主人(ou_adf...)
```

**手动触发**：`#排程到日历` / `#日历` → 同上 calendar_sync 路径。

---

## 四、每周复盘流（周日 21:00）

```
weekly_deep_review.py
  → 读深度工作表 + 习惯表
  → 生成 ASCII 柱状图 / 进度条 / 趋势（4DX：引领性指标周累计）
  → 推送到飞书
```

---

## 五、多 Agent 协作同步流（共享状态，不共享对话）

```
Agent A ──读写──▶ 飞书 Base（唯一状态中枢）◀──读写── Agent B
                    │
       同步信号 = 状态 + 责任人 + 状态更新时间 三字段
                    │
       daily_scheduler 每日状态广播给主人
```

**三条纪律**（见 `NEW_AGENT_ONBOARDING.md`）：① 只拿自己 `责任人` 的任务；② 领任务改 `状态=进行中`；③ 做完改 `状态=已完成` 并更新 `状态更新时间`。

---

## 六、训练计划落地约定（2026-07-30 固化）

安排多日训练计划时，**同时建飞书任务**（不进执行库 Base）：

```bash
lark-cli task +create --as user \
  --summary="Day2 渐进力量" \
  --description="动作清单… 练完用 #训练 打卡" \
  --due="<训练当天毫秒时间戳>" \
  --assignee="ou_adf2c637b6ddd79c0af429ad5da3a746"
```

**为什么**：只建日历不建任务时，每日排程引擎读不到训练、不进每日任务清单；建 Base 会与排程引擎建的飞书任务重复。已落地：5 天渐进力量计划（Day1 2026-07-30 已练完未建任务；Day2-5 已建飞书任务）。

---

## 七、BodyOS 精力流（每日）

```
Garmin 增量同步 (garmin_incremental_sync.py, 14天窗口)
  → raw_garmin_365d.json (镜像)
  → body_os_dataset_365d.json (清洗, 统计唯一入口)
  → body_os_today_energy.json + _energy_status.json (运行态)
  → 每日排程引擎读取 → 调可用时长（L1 建议级）
手动 #精力 优先于 Garmin 自动值。
```
