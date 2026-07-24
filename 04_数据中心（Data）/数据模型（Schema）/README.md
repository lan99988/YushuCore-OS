# 数据模型中心（Schema Center）

> 系统全部数据结构的**唯一权威定义来源**。
> 系统注册表只记录「有哪些数据资产 / 去哪看定义 / 谁使用」，字段级定义一律在此。

---

## 设计原则

1. **Schema 是数据层真实世界的抽象，不是 Skill 的映射。**
   - 一个 Skill 可以操作多个数据模型；一个数据模型可以被多个 Skill 使用。
   - 数据模型数量 = 业务实体数量，不随 Skill 增减而增减。
2. **先定义 Schema，再写代码。** 任何新增 Skill 第一步先在此定义模型。
3. **注册表不维护字段。** 字段变化频繁，统一在 Schema 里版本化管理。

### 数据流

```
用户输入
  ↓
Skill（理解意图）
  ↓
Schema（数据结构定义）
  ↓
Repository（数据访问，未来）
  ↓
飞书 Base（真实存储）
```

---

## 数据资产分类（5 大类）

按数据性质分为 5 类，避免混在一起，未来扩展不破坏结构。

| 类别 | 目录 | 特征 |
|------|------|------|
| 01 核心执行 | `01_核心执行/` | 高频读写，每天运行 |
| 02 成长管理 | `02_成长管理/` | 长期趋势 |
| 03 项目管理 | `03_项目管理/` | 阶段管理 |
| 04 知识关系 | `04_知识关系/` | 长期资产 |
| 05 决策分析 | `05_决策分析/` | 分析与决策 |

---

## 数据资产总表（15 个模型）

| 编号 | 模型(English) | 中文名称 | 类别 | 对应飞书表 | Schema 状态 |
|------|---------------|----------|------|-----------|------------|
| 01 | Task | 任务 | 核心执行 | 执行库 `tblNQCB4pn6Rso4a` | ✅ v1.0 |
| 02 | Idea | 灵感 | 核心执行 | 灵感库 `tblx1ZaQGwXvoJhj` | ✅ v1.0 |
| 03 | Bug | 问题 | 核心执行 | Bug库 `tblPpPputYMACtQ5` | ✅ v1.0 |
| 04 | Energy | 精力状态 | 核心执行 | （无专属表，设计稿） | ✅ v1.0 |
| 05 | Habit | 习惯 | 成长管理 | 习惯追踪表 `tblSRdG4P3XE75Ll` | ✅ v1.0 |
| 06 | DeepWork | 深度工作 | 成长管理 | 深度工作追踪表 `tblmAz37er4CEbL0` | ✅ v1.0 |
| 07 | SubjectProgress | 科目进度基线 | 成长管理 | 科目进度基线 `tblQnjCO03WjQ7GC` | ✅ v1.0 |
| 08 | Competition | 比赛 | 项目管理 | 比赛管理表 `tblKPdoxMHy7FuV7` | ✅ v1.0 |
| 09 | Finance | 财务流水 | 决策分析 | 财务流水表 `tblPFKBGubeIYsfm` | ⏳ 第二批 |
| 10 | Social | 社交关系 | 知识关系 | 社交关系表 `tblt7uTkIcLhH7bs` | ⏳ 第二批 |
| 11 | Creation | 创作素材 | 项目管理 | 创作素材表 `tbl99pDAlTIDu7f5` | ⏳ 第二批 |
| 12 | Knowledge | 知识笔记 | 知识关系 | 知识笔记表 `tblgtdx4h0EJjRrh` | ⏳ 第二批 |
| 13 | Project | 项目管理 | 项目管理 | 项目管理 `tblCnVUb327SQ9mS` | ⏳ 第二批 |
| 14 | StockStrategy | 股市策略 | 决策分析 | 股市策略 `tblVWrqa8fNCcCjA` | ⏳ 第三批 |
| 15 | MultiRoundTracking | 多轮次追踪 | 决策分析 | 多轮次追踪表 `tblJmOfDHV83RsIg` | ⏳ 第三批 |

> 注：飞书 Base 根表「个人混合管理系统」(`tblPxhRiJg8SfXxD`) 为系统总览表，非业务数据模型，不计入上述 15 个数据资产。

---

## 字段命名规则

- **JSON 字段用英文名**（`title` / `status` / `created_at`），方便代码调用。
- **中文名作为 `中文名称` 字段**，对应飞书真实字段名。
  ```json
  { "name": "created_at", "中文名称": "创建时间" }
  ```
- **不要**把中文直接当字段名（如 `{ "name": "任务标题" }`），未来代码调用会麻烦。

### 字段类型归一化

| 飞书类型 | Schema 类型 | 说明 |
|----------|------------|------|
| text | `text` | 文本 |
| select | `enum` | 单选，附 `options` |
| datetime | `datetime` | 日期时间 |
| number | `number` | 数值 |
| checkbox | `boolean` | 布尔 |
| attachment | `attachment` | 附件 |
| formula | `formula` | 公式计算，`computed:true` |
| auto_number | `auto_number` | 自增序号，`computed:true` |
| created_at / updated_at | `system_timestamp` | 系统时间戳，`computed:true` |

---

## 单个 Schema JSON 标准结构

```json
{
  "model": "Task",
  "中文名称": "任务",
  "version": "1.0",
  "description": "模型说明",
  "source_skill": ["输入解析引擎", "随手录-飞书操作"],
  "feishu_table": { "id": "tblNQCB4pn6Rso4a", "name": "执行库" },
  "fields": [
    { "name": "title", "中文名称": "标题", "type": "text", "required": true },
    { "name": "status", "中文名称": "状态", "type": "enum", "options": ["待处理","进行中","已完成","已取消"] }
  ]
}
```

- `computed:true`：公式/自增/系统时间字段，非用户直接写入。
- `feishu_table:null`：设计稿模型（如 Energy），尚未独立落库。

---

## 版本

见同级 `../数据版本（Version）/版本记录.md`。
