# 🤖 Agent Guide — 个人混合管理系统

> 最后更新：2026-06-30
> 用途：新AI快速对齐项目上下文

---

## 这是什么项目

以飞书多维表格为数据中枢，WorkBuddy/AI为输入入口，Agent每日主动推送的闭环个人管理系统。
当前覆盖：考研管理 + 财务追踪 + 社交管理 + 创作输出 + 知识沉淀 + 多项目推进。

系统哲学：**消除模糊** — 每条记录都回答"这条信息消除什么模糊了？"

## 当前状态

| 维度 | 值 |
|:----|:---|
| 当前阶段 | 开发 |
| 负责Agent | WorkBuddy（主力开发） |
| 项目优先级 | P0-核心 |
| 状态更新时间 | 2026-06-30 01:30 |

## 活跃Agent

| Agent | 在本项目中的角色 |
|:------|:--------------|
| **我自己** | 项目主人，决策者 |
| **WorkBuddy** | 主力开发Agent（就是你），实现系统功能 |
| **随手录** | 日常记录Agent，自然语言输入自动分类写入 |

## 数据源

### 飞书Base（唯一数据中枢）— 这里是所有状态同步的地方

Base地址：https://my.feishu.cn/base/TtzIboiQQaPgfVszO2vc56wLnof
操作身份：`--as=user`

**9张表：**

| 表名 | 表ID | 你能做什么 |
|:-----|:-----|:----------|
| 执行库 | tblNQCB4pn6Rso4a | ✅ 读+写（核心任务池） |
| 灵感库 | tblx1ZaQGwXvoJhj | ✅ 读+写 |
| Bug库 | tblPpPputYMACtQ5 | ✅ 读+写 |
| 项目管理表 | tblCnVUb327SQ9mS | ✅ 读+写（项目总控台） |
| 科目进度基线 | tblQnjCO03WjQ7GC | ✅ 只读（考研四科进度） |
| 财务流水表 | tblPFKBGubeIYsfm | ✅ 只读 |
| 社交关系表 | tblt7uTkIcLhH7bs | ✅ 写（仅当被请求） |
| 创作素材表 | tbl99pDAlTIDu7f5 | ✅ 写 |
| 知识笔记表 | tblgtdx4h0EJjRrh | ✅ 写 |

### 本地工作区

**根目录**：`D:\个人混合管理系统\`

| 文件 | 用途 |
|:-----|:-----|
| `02_执行引擎（Engine）/输入解析引擎/input_parser.py` | 输入解析引擎（前缀指令 → 飞书Base） |
| `02_执行引擎（Engine）/每日排程引擎/daily_scheduler.py` | 每日排程推送（每天早上7:00发消息） |
| `07_系统文档（Docs）/SYSTEM_BLUEPRINT.md` | 系统完整蓝图 |
| `07_系统文档（Docs）/模块设计-飞书Base一体化扩展.md` | 8表模块设计文档 |
| `07_系统文档（Docs）/多项目共享状态机制.md` | 多Agent协作同步机制说明 |
| `07_系统文档（Docs）/NEW_AGENT_ONBOARDING.md` | 新AI入职指南（可以读这个快速上手） |
| `01_Skill能力库（Skills）/00_Skill注册中心（Registry）/SKILL.md` | 系统SKILL定义（含多Agent协作规则） |

## 所有Agent的通用规则

### 核心：共享状态，不共享对话

**不直接跟其他Agent说话**，所有同步通过飞书Base的数据变化完成。

**三字段同步信号**：
1. **责任人** — 谁在处理（`责任人` 字段）
2. **状态** — 待收集 → 待排期 → 进行中 → 已完成
3. **状态更新时间** — 最后一次变动的时间戳（项目管理表）

### 启动时检查你的待办

不限项目，跨所有表扫描：

```bash
# 查执行库
lark-cli base +record-search \
  --base-token=TtzIboiQQaPgfVszO2vc56wLnof \
  --table-id=tblNQCB4pn6Rso4a \
  --as=user \
  --filter='{"conditions":[{"field_name":"责任人","operator":"is","value":["WorkBuddy"]}],"sorts":[{"field_name":"权重分","desc":true}]}'

# 查灵感库（把 --table-id 换成 tblx1ZaQGwXvoJhj）
# 查Bug库（把 --table-id 换成 tblPpPputYMACtQ5）
```

把 `"WorkBuddy"` 换成你的身份。

### 领任务 → 执行 → 完成

1. 更新 `状态` = "进行中"
2. 执行
3. 更新 `状态` = "已完成"
4. 卡住了 → 在项目管理表填 `阻塞原因`

## 输入格式（主人会这样跟你说话）

```
#任务 做数学真题 【项目：考研】【责任人：WorkBuddy】【精力：高】【耗时：120分钟】
#账单 午饭 28元 餐饮
#社交 见了张三 聊考研 同学 ★★★
#创作 公众号文章 文章 灵感
#知识 泰勒公式展开 数学 来源:张宇P120
```

支持的前缀：`#任务` `#灵感` `#Bug` `#精力` `#配置` `#账单` `#财务` `#社交` `#关系` `#创作` `#作品` `#知识` `#笔记`

## lark-cli速查

```bash
# 查表字段（写入前必读）
lark-cli base +field-list --base-token=TtzIboiQQaPgfVszO2vc56wLnof --table-id=tblNQCB4pn6Rso4a --as=user

# 写记录
lark-cli base +record-upsert --base-token=TtzIboiQQaPgfVszO2vc56wLnof --table-id=tblNQCB4pn6Rso4a --as=user --json='{"标题":"任务名","状态":"待收集"}'

# 更新记录
lark-cli base +record-upsert --base-token=TtzIboiQQaPgfVszO2vc56wLnof --table-id=tblNQCB4pn6Rso4a --record-id=<ID> --as=user --json='{"状态":"进行中"}'
```

## 当前已知阻塞

（无 — 项目正常运行中）

---

**看完后你就对齐了。现在去查你的待办吧。**
