# ADR-009: Knowledge Storage Strategy — IMA + Feishu Dual Persistence

- 状态：Accepted
- 日期：2026-09-15
- 关联：ADR-008（IMA 信息层）、`plans/2026-09-15-cognitive-dual-persistence-plan.md`

## 背景

知识库主承载由「飞书唯一事实源」调整为「IMA 知识库」后，最终主库归属
（IMA First / Feishu First / Hybrid）缺乏真实运行数据支撑。本决策采用
**双库并行 + 统一认知模型**，把最终架构决策推迟到有数据之后。

## 决策

1. **本阶段不决定最终主库。** 默认策略 `PersistencePolicy(primary="dual")`，
   运行后按指标（检索准确率/延迟/同步失败率/维护成本）评审切换。
2. **cognitive_id 是跨系统唯一主标识**，格式 `<PREFIX>-<YYYYMMDD>-<6位序号>`
   （SRC/NOTE/EXP/KNW/CON/INS/BEL/DEC 八前缀）。IMA media_id 只存 `ima_ref`，
   飞书 record_id 只存 `feishu_ref`，均不得作主键（禁令 2/3）。
3. **认知模型高于数据库模型**：八类对象（Source/Note/Experience/Knowledge/
   Concept/Insight/Belief/Decision）由 `cognitive_system/mapping.py` 从信息层
   InformationObject 显式映射产出，不由 IMA/飞书字段反向决定。
4. **Persistence Layer 解耦**：业务只面对 `CognitivePersistenceLayer`；
   IMA 写入 = create_note + 挂载（更新=append-only 事件，删除=平台不支持）；
   飞书写入 = lark-cli `base +record-upsert / +record-batch-update`。
5. **认知状态与持久化状态分离**：cognitive_status（active/revised/superseded/
   rejected/archived）≠ ima_status / feishu_status（pending/synced/failed/conflict）。
   汇总 sync_state 六态：SYNCED / IMA_ONLY / FEISHU_ONLY / CONTENT_CONFLICT /
   SYNC_FAILED / PENDING。
6. **最终一致性**：单库失败入 `cognitive_retry_queue`，`retry_pending()` 补写；
   不要求用户重输（禁令 6）。
7. **冲突不自动覆盖**：以 content_hash + version 判定，不一致 → CONTENT_CONFLICT，
   高置信度自动合并留待后续。
8. **标签一律中英双语**（用户要求）：`cognitive_tag_registry` 以 zh 为主键、en 必填
   才算 confirmed；未登记标签入候选区（与 ADR-008 观察区治理一致）。IMA markdown
   渲染 `#中文 #english`；飞书分列「标签中文」「标签英文」。

## 落点

- 代码：`cognitive_system/{models,ids,tags,mapping,store,ima_writer,feishu_writer,persistence,retrieval}.py`
- 数据：`information_objects.db` 新增 4 表（cognitive_asset / cognitive_tag_registry /
  cognitive_retry_queue / cognitive_sync_log）
- 检索：`cognitive_system/retrieval.py` 双源并行 + cognitive_id 去重（IMA 靠标题
  `[cognitive_id]` 前缀解析；无前缀条目不参与合并）
- 门禁：`scripts/verify.py` compileall 加入 `cognitive_system`；测试 373 passed

## 边界与未决事项

- **未接自动触发**：从信息层输入到认知资产双写须显式调用
  `extract_cognitive_assets()` + `persist()`（与 note_taxonomy 先例一致：
  写外部系统不自动触发）。触发时机 + 置信度门槛待定。
- 飞书认知资产表（认知ID/类型/标题/内容/标签中文/标签英文/状态/置信度/版本/
  内容哈希/IMA状态/IMA引用/创建时间）需在 Base 中建表并登记
  `config`（base_token + table_id）后启用；未配置时该通道报 writer 未配置并保持 PENDING。
- IMA 写入为异步解析，双写后不可立即检索（ADR-008 既有边界）。
- IMA 无删除/覆盖写为**平台边界**（PARTIALLY_SUPPORTED），不是待办。

## Architecture Review 触发条件

上线运行积累 ≥4 周数据后评审：检索准确率、延迟、写入成功率、同步失败率、
维护成本、AI 调用效果 → 决定 IMA First / Feishu First / Hybrid（计划书第四十三节）。

## ADR-010 权威语义修订（2026-09-26）

ADR-010 收窄本 ADR 的权威范围：IMA + 飞书双持久化保存的是 cognitive_system 的认知资产投影、同步状态和检索副本；投影不是知识正文权威。

长期知识正文、经验、方法和原则以 D:\Knowledge 为权威，并只经 Knowledge Gateway 访问。认知资产投影可以从受控信息和知识上下文重建，不得反向静默覆盖正文。

原“最终主库未定”的评审范围调整为认知资产投影的首选持久化通道，不再用于决定长期知识正文的事实源。
