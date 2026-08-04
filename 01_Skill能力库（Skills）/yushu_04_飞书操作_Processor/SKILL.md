# yushu_04_飞书操作_Processor

> 标准信息段（依据 `Skill规范.md` 模板）

## 基础信息

| 项 | 值 |
|------|------|
| 名称 | yushu_04_飞书操作_Processor |
| 版本 | 2.0（2026-07-01 原子化拆分） |
| 状态 | 稳定 |
| 创建时间 | 2026-07-01 |
| 负责人 | 甲乙簿 |

## 功能定位

接收标准化字段，执行飞书 Base 写入与飞书任务创建。**系统唯一直接调用 lark-cli 写操作的 Skill**。含去重检查、提醒设置、任务 GUID 回写、批量操作。

## 触发方式

yushu_01_输入解析引擎_Router / yushu_02_意图分类_Router 产出 fields 后自动加载。

## 输入

标准化字段字典。

## 输出

`{ok: true, table, operation, ...}` 或 `{ok: false, error}`。

## 依赖

- 飞书（lark-cli 写）
- 系统注册表（Token / 表 ID / 命令模板）

## 数据

执行库、灵感库、Bug库、财务流水表、社交关系表、创作素材表、知识笔记表；飞书任务。

## 权限

- read：Base 查询 / 去重
- write：Base 记录 + 飞书任务
- admin：无

## 调用链

fields → 飞书操作 → lark-cli → 飞书 Base / 飞书任务

## 测试

测试方式：`python "02_执行引擎（Engine）/输入解析引擎/input_parser.py" "#任务 测试 --dry-run"` 观察 upsert 结构。
最后测试时间：2026-07-01

## 纲要

接收标准化记录字段，执行飞书 Base 写入和飞书任务创建。
**本 skill 是唯一直接调用 lark-cli 执行写操作的 skill。**
包含去重检查、提醒设置、任务 GUID 回写、批量操作。

## 触发

「yushu_01_输入解析引擎_Router」或「yushu_02_意图分类_Router」产出标准化字段字典后自动加载。

## 输出

`{ok: true, table: "执行库", ...}` 或 `{ok: false, error: "..."}`

## 后续流程

### 产出接口

```json
// 成功
{
  "ok": true,
  "table": "执行库",
  "operation": "upsert",
  "title": "做数学真题2010",
  "feishu_task_url": "https://applink.feishu.cn/client/todo/detail?guid=..."
}

// 去重跳过
{
  "ok": true,
  "deduplicated": true,
  "table": "执行库",
  "title": "做数学真题2010"
}

// 失败
{
  "ok": false,
  "error": "[写入失败] 无权限: --as=user 身份过期",
  "action": "请检查 lark-cli 登录状态"
}
```

### 下游技能

写入成功后无下游 skill。直接向用户返回确认消息。
写入失败时参见「系统注册表·统一错误处理」。

### lark-cli 命令

所有 lark-cli 命令模板参见「系统注册表·lark-cli 命令参考」，此处不再重复。

### 错误处理

遵循「系统注册表·统一错误处理」规范。

---

## 一、写入 Base（通用命令模板）

所有写入统一使用 lark-cli 命令：

```bash
lark-cli base +record-upsert \
  --base-token=TtzIboiQQaPgfVszO2vc56wLnof \
  --table-id=<TABLE_ID> \
  --as=user \
  --json='@<tmpfile>.json'
```

### 1.1 写入执行库

```json
{
  "标题": "做数学真题2010",
  "所属项目": "考研",
  "轻重缓急": "P2-紧急不重要",
  "状态": "待收集",
  "截止日期": "2026/07/05",
  "精力消耗等级": "高",
  "预估耗时": 120,
  "是否为今日硬骨头": false,
  "科目类别": "数学"
}
```

可选字段：责任人、关联知识库文档、任务GUID

### 1.2 写入灵感库

```json
{
  "标题": "用Anki卡片背408概念",
  "所属项目": "考研",
  "轻重缓急": "P2-紧急不重要",
  "状态": "待收集",
  "灵感原文": "想到可以用Anki卡片背408概念",
  "触发场景": "洗澡时",
  "转化状态": "待孵化",
  "优先级预判": "P2-紧急不重要"
}
```

### 1.3 写入Bug库

```json
{
  "标题": "考研英语App闪退",
  "所属项目": "考研",
  "轻重缓急": "P2-紧急不重要",
  "状态": "待收集",
  "Bug简述": "考研英语App闪退，点单词就崩",
  "严重程度": "功能缺陷",
  "修复状态": "待修复"
}
```

### 1.4 写入财务流水表

```json
{
  "标题": "午餐",
  "金额": 28.0,
  "类型": "支出",
  "分类": "餐饮",
  "日期": "2026/07/01"
}
```

注意：收入存负数，支出存正数。

### 1.5 写入社交关系表

```json
{
  "标题": "见了张三 聊考研",
  "联系人": "张三",
  "活动类型": "见面",
  "活动内容": "聊考研复习计划",
  "亲密度": "★★★",
  "日期": "2026/07/01"
}
```

可选字段：生日、关系标签

### 1.6 写入创作素材表

```json
{
  "标题": "公众号文章标题",
  "类型": "文章",
  "状态": "灵感",
  "内容摘要": "关于XX话题的公众号文章"
}
```

### 1.7 写入知识笔记表

```json
{
  "标题": "泰勒公式展开",
  "知识点": "泰勒公式展开式",
  "类型": "常青笔记",
  "分类": "数学",
  "来源": "书籍",
  "来源详情": "张宇P120"
}
```

## 二、去重检查（仅执行库）

写入前检查是否已存在同日期同名任务：

```bash
lark-cli base +record-list \
  --base-token=TtzIboiQQaPgfVszO2vc56wLnof \
  --table-id=tblNQCB4pn6Rso4a \
  --as=user \
  --limit=200 \
  --format=json
```

匹配规则：标题模糊匹配（±2字符误差容忍）+ 截止日期精确匹配
重复时：跳过写入，返回去重提示

## 三、创建飞书任务

### 3.1 获取用户 open_id

```bash
lark-cli auth status
# 提取 .identities.user.openId
```

用户 open_id: `ou_adf2c637b6ddd79c0af429ad5da3a746`

### 3.2 创建任务

```bash
lark-cli task +create \
  --summary "<标题>" \
  --description "<补充说明>" \
  --due "<ISO 8601 时间>" \
  --assignee "<open_id>"
```

截止时间：当天 23:59:59 的毫秒时间戳

### 3.3 设置提醒

```bash
lark-cli task +reminder --task-id "<guid>" --set "<提前分钟数>"
```

提醒时间选择规则：
| 截止时间 | 推荐提前量 |
|---------|-----------|
| 今天内（< 4小时） | 5-15分钟 |
| 今天内（> 4小时） | 30分钟 |
| 明天/后天 | 1小时 |
| 一周后 | 1天 |
| 用户指定 | 按用户要求 |

### 3.4 任务GUID回写

将飞书任务GUID和URL写回执行库，建立双向关联：

```bash
lark-cli base +record-batch-update \
  --base-token=TtzIboiQQaPgfVszO2vc56wLnof \
  --table-id=tblNQCB4pn6Rso4a \
  --as=user \
  --json='{"record_id_list":["<Base记录ID>"],"patch":{"关联知识库文档":"<task_url>","任务GUID":"<task_guid>"}}'
```

目的：
- GUID 用于 Base 工作流「一键同步任务状态」按钮查询状态
- URL 用于手动跳转到飞书任务

## 四、批量操作

一条输入包含多条内容时（如"今天做数学真题，还有记得买笔，哦对了想到一个学习方法"），拆分为多条记录分别写入。

每条记录独立执行写入流程（包括各自的去重检查）。

## 五、多轮次任务特殊处理

检测到「分N次」模式时：
1. 写入执行库一条总记录（用于整体追踪）
2. 创建第1次飞书任务（标题格式："原标题（第1/N次）"）
3. 轮次信息写入 `multi_round_tasks.json` 追踪文件
4. 后续轮次由自动化「多轮次任务自动迭代」每小时自动检查创建

## 六、lark-cli Windows 兼容

- JSON 参数通过 `@tmpfile.json` 方式传入（避免 shell 引号冲突）
- 临时文件用 UUID 命名防冲突
- 命令执行后清理临时文件
- 多编码 fallback：utf-8 → gbk → gb2312 → cp936
- Git Bash 路径 fallback：`Program Files\Git\usr\bin\bash.exe` → `Program Files\Git\bin\bash.exe` → `bash`

> 版本: 2.0 | 归属: 个人混合管理系统 | 创建: 2026-07-01
