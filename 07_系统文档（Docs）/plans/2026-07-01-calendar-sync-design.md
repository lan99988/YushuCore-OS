# 飞书日历同步工程设计方案

**日期**: 2026-07-01 | **状态**: 设计确认，待实施

## 动机

现有系统通过 `daily_scheduler.py` 生成每日排程时间轴，推送到飞书消息和飞书任务。
但飞书任务是"全天截止"类型，无法在日历上直观看到每个时段该做什么。

新增日历同步功能，将排程结果直接写入飞书日历，让用户：
- 打开日历就看到今天每个时间段的安排
- 直观感知冲突（会议 vs 学习）
- 通过日历提醒功能准时开始任务

## 架构决策

### 新增独立模块 `calendar_sync.py`

不直接塞入 `daily_scheduler.py`，而是保持解耦，原因：
- 日历同步是独立职责，可单独测试
- 支持双入口：自动跟随排程 + 手动 `#排程到日历` 指令
- 未来可扩展为其他场景（比如直接把任务拖入日历）

### 数据流

```
daily_scheduler.py  →  generate_schedule()  →  timeline[]
                                                      │
                    #排程到日历 (手动) ─────┐           │
                                          ▼           ▼
                                     calendar_sync.py
                                           │
                      ┌────────────────────┼────────────────────┐
                      ▼                    ▼                    ▼
              1. +freebusy 查空       2. 检测冲突         3. +create 写日历
                                                          4. 报告结果
```

## 核心模块设计

### `calendar_sync.py` API

```python
def sync_schedule_to_calendar(schedule, target_date=None, dry_run=False):
    """
    将排程结果同步到飞书日历
    
    Args:
        schedule: 来自 daily_scheduler.generate_schedule() 的排程数据
        target_date: 目标日期 (yyyy/MM/dd)
        dry_run: 测试模式
        
    Returns:
        {
            "ok": True/False,
            "created_events": [event_id, ...],
            "conflicts": [{"slot": "高效段①", "time": "09:00-10:30", "conflicting_events": [...]}],
            "summary": "字符串摘要"
        }
    """

def check_date_freebusy(target_date=None):
    """查询指定日期的忙闲状态"""
    
def create_calendar_event(summary, start_iso, end_iso, description, dry_run=False):
    """创建单个日历事件"""
    
def find_next_available_slot(duration_minutes, after_iso, timezone="+08:00"):
    """找下一个空闲时段"""
    
def clear_today_schedule_events(dry_run=False):
    """清空今日已同步的排程事件（用于重新排程时）"""
```

### lark-cli 命令映射

| 操作 | lark-cli 命令 |
|------|--------------|
| 查询忙闲 | `calendar +freebusy --start <ISO> --end <ISO> --as user` |
| 创建事件 | `calendar +create --summary <TITLE> --start <ISO> --end <ISO> --description <DESC> --as user` |
| 搜索事件 | `calendar +search-event --start <ISO> --end <ISO> --as user` |
| 建议时段 | `calendar +suggestion --duration-minutes <N> --start <ISO> --as user` |

## 冲突处理流程

### 三层架构

**第一层：冲突检测**
- 遍历排程的每个时段（高效段①/②、完整段①/②、零散段）
- 调用 `+freebusy` 查询该时段是否已有日历事件
- 返回冲突事件清单

**第二层：决策层（推送消息问我）**
```
⚠️ 【日历冲突】
高效段①(09:00-10:30) 与「产品评审」(10:00-11:00) 重叠
→ 可以并行？还是重新安排？
```

**第三层：自动顺延**
- 用户选择「重新安排」
- 调用 `+suggestion` 寻找下一个可用时段
- 在建议时段创建事件
- 推送新时间确认

## 日历事件格式

### 学习时段事件（区块事件）

```
标题：🔴 高效段① · 数学
时间：2026/07/01 09:00 - 10:30
描述：
  📋 今日任务：
  · 做数学真题2010（120分钟）
  · 复习泰勒公式（30分钟）
  ⭐ 硬骨头：做数学真题2010
```

时段图标映射：
- 🔴 高精力（高效段）
- 🟡 中精力（完整段）
- 🟢 低精力（零散段）

### 独立任务事件（非学习的零散任务）

```
标题：🤝 微信联系张三（久未联系15天）
时间：2026/07/01 20:00 - 20:15
描述：亲密度：★★ ｜ 已15天没联系
```

## 集成方案

### 自动跟随（daily_scheduler.py）

在 `main()` 末尾，创建任务之后、推送消息之前，增加：

```python
from calendar_sync import sync_schedule_to_calendar
result = sync_schedule_to_calendar(schedule)
if result.get("conflicts"):
    # 冲突信息追加到推送文本末尾
    push_text += "\n\n⚠️ 【日历冲突】" + result["summary"]
```

### 手动触发（input_parser.py）

注册新前缀指令：

```python
"#排程到日历": None,  # 特殊处理：手动同步今日排程到日历
```

处理逻辑：
1. 读取飞书Base执行库当天的任务
2. 调用 `daily_scheduler.generate_schedule()` 生成排程
3. 调用 `calendar_sync.sync_schedule_to_calendar()` 同步到日历
4. 返回结果

### 运行日志（runtime/_calendar_log.json）

```
{
    "date": "2026-07-01",
    "events": [
        {"event_id": "event_id_xxx", "summary": "🔴 高效段① · 数学", "start": "09:00", "end": "10:30", "slot": "高效段①", "status": "created"}
    ],
    "conflicts": [...]
}
```

用于：
- 重新排程时先清理今日事件
- 追踪同步状态

## 后续迭代方向

- 交互卡片：在飞书消息中嵌入「可以并行/重新安排」按钮，点击直接处理冲突
- 多日排程：提前将一周的排程写入日历
- 日历事件更新：如果排程有调整，自动更新而非删除重建
