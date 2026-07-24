# 比赛管理表 Schema

## Base 表信息

| 属性 | 值 |
|------|-----|
| 表名 | 比赛管理表 |
| 总字段数 | 28（不含自动系统字段） |
| 主键 | 比赛名称（text 字段，唯一标识） |

## 字段清单

### 基本信息（5 字段）

| 字段名 | 类型 | Select 选项 | 说明 |
|--------|------|-------------|------|
| 比赛名称 | text | — | 必填，唯一标识一场比赛 |
| 日期 | datetime (yyyy/MM/dd) | — | 比赛日期 |
| 地点 | text | — | 举办地 |
| 参赛人员 | text | — | 逗号分隔姓名，如"我自己,张三,李四" |
| 比赛链接 | text | — | 官网/报名页 URL |

### 报名阶段（3 字段）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 报名截止 | datetime (yyyy/MM/dd) | 报名截止日期 |
| 报名费用 | number | 报名费（元） |
| 报名备注 | text | 补充信息 |

### 初赛阶段（4 字段）

| 字段名 | 类型 | Select 选项 |
|--------|------|-------------|
| 初赛状态 | select | 未开始 / 进行中 / 已完成 / **跳过仅一轮** |
| 初赛日期 | datetime | — |
| 初赛结果 | select | 待定 / 晋级 / 未晋级 / 不适用 |
| 初赛备注 | text | — |

### 决赛阶段（4 字段）

| 字段名 | 类型 | Select 选项 |
|--------|------|-------------|
| 决赛状态 | select | 未开始 / 进行中 / 已完成 / **不适用** |
| 决赛日期 | datetime | — |
| 决赛结果 | select | 待定 / 获奖 / 未获奖 / 不适用 |
| 决赛备注 | text | — |

### 成绩与奖状（3 字段）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 最终成绩 | text | 如"一等奖"、"第3名"、"85分" |
| 奖状信息 | text | 奖状名称/编号等 |
| 奖状图片 | attachment | 奖状截图 |

### 附件字段（1 字段）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 报名费凭证 | attachment | 报名费+报销凭证截图 |

### 奖金申请（3 字段）

| 字段名 | 类型 | Select 选项 |
|--------|------|-------------|
| 奖金申请状态 | select | 未开始 / 进行中 / 已完成 |
| 奖金金额 | number | 元 |
| 奖金申请日期 | datetime | — |

### 报销阶段（4 字段）

| 字段名 | 类型 | Select 选项 |
|--------|------|-------------|
| 报销状态 | select | 未开始 / 进行中 / 已完成 |
| 报销金额 | number | 元 |
| 报销日期 | datetime | — |
| 报销备注 | text | — |

### 系统字段（1 字段）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| ID | auto_number | 自动编号 |

## 创建表的 lark-cli 命令

```bash
# 1. 创建表
lark-cli base +table-create --base-token=<token> --name="比赛管理表" --as=user

# 2. 创建字段（每字段一条命令）
# 示例：创建 text 字段
lark-cli base +field-create --base-token=<token> --table-id=<table_id> --json='{"type":"text","name":"比赛名称","style":{"type":"plain"}}' --as=user

# 示例：创建 select 字段
lark-cli base +field-create --base-token=<token> --table-id=<table_id> --json='{"type":"select","name":"初赛状态","multiple":false,"options":[{"name":"未开始"},{"name":"进行中"},{"name":"已完成"},{"name":"跳过仅一轮"}]}' --as=user

# 示例：创建 datetime 字段
lark-cli base +field-create --base-token=<token> --table-id=<table_id> --json='{"type":"datetime","name":"日期","style":{"format":"yyyy/MM/dd"}}' --as=user

# 3. 获取表 ID
lark-cli base +table-list --base-token=<token> --as=user
```

## 字段创建 JSON 模板

### Text 字段
```json
{"type": "text", "name": "字段名", "style": {"type": "plain"}}
```

### Select 字段（单选）
```json
{"type": "select", "name": "字段名", "multiple": false, "options": [{"name": "选项1"}, {"name": "选项2"}]}
```

### Number 字段
```json
{"type": "number", "name": "字段名", "style": {"type": "plain", "precision": 0, "format": "normal"}}
```

### Datetime 字段
```json
{"type": "datetime", "name": "字段名", "style": {"format": "yyyy/MM/dd"}}
```

### Checkbox 字段
```json
{"type": "checkbox", "name": "字段名"}
```

### Attachment 字段
```json
{"type": "attachment", "name": "字段名"}
```
