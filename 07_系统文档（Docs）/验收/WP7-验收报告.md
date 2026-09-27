# WP7 个人领域插件验收报告

> 日期：2026-09-27
> 结论：PASS
> 分支：codex/yushu-wp7-personal-domains
> 起点 HEAD：b9ef2e8d16ab916fd758e5e485bda26c6bb5bf29

## 1. 目标与边界

WP7 按“低摩擦、渐进激活、提案先行”加入 Social、Life Admin、Finance、Creation、Interest、Experience 六个个人领域插件。六个插件均默认 dormant，不预建空记录，不直接写外部系统。

## 2. 交付物

- Social：Person、Interaction、Commitment 三类最小 Schema；一次自然语言输入形成待审记录与承诺提案。
- Life Admin：仅支持证件、住房设施、个人资产维护、服务合同、行政手续五类领域；首次真实需求提出激活与提醒计划。
- Finance：只生成月度聚合快照；OCR、历史与分析均通过注入端口；固定 fixture 离线测试。
- Creation：固定 Idea → Draft → Production → Publish → Feedback → Archive 生命周期；正文只保存 Knowledge 指针。
- Interest：主题记录、轻量探索、回顾和用户主动转 Project；没有 KPI、连续记录或截止日。
- Experience：固定 Wishlist → Planned → Booked → Experienced → Reflection 生命周期；Reflection 升格需要用户确认和权威状态读取。
- 六组 manifest、六组插件实现、九个领域 Schema、Finance fixtures 及专项测试。

## 3. 渐进激活与外部动作

- 六个 manifest 均为 on-demand、dormant，可由 Registry 单独关闭。
- manifests 的 writes 均为空；插件只返回 pending_human_review 提案，不执行写入。
- Dormant 插件不会生成后台提醒、空表或维护任务。
- Social 承诺中的消息/资料发送动作明确 requires_human_review=true、executed=false。
- Life Admin 只有识别到有效、未过期且时间上下文充分的事项才提出领域激活和提醒。
- Interest 只有 user_requested=true 时才提出 Project 转换。
- Experience Reflection 只有用户确认且注入的权威状态确为 reflection 时才允许升格。

## 4. 领域验收

### 4.1 Social

- 验收句“昨天和小王吃饭，他准备年底换工作；我答应周末发简历模板。”一次解析出 Person、Interaction、上下文和 Commitment。
- 用户不需要填写联系人表；Person 仅保留姓名、关系、上次联系、下次关注、未完成承诺。
- 用户只需提供自然语言；插件通过可注入 clock 自动补充 captured_at。测试使用固定时钟，生产默认使用系统时钟。
- 生成值在进入提案前校验 Schema 长度边界，避免下游拒绝。

### 4.2 Life Admin

- “护照明年 3 月到期”在提供权威 today 后提出 identity_documents 激活与提醒计划。
- 过去月份、缺少年份或相对日期缺少 today 时均 needs_clarification，不激活、不建事项、不提醒。
- 仅提汽车不会创建或激活汽车领域。

### 4.3 Finance

- 快照只含收入、支出、结余、储蓄率、消费结构、大额分类、环比、异常、分析和下月关注。
- 未定义 transaction/ledger 模型，OCR 返回逐笔数据时 fail-closed。
- 月份仅接受合法 ASCII YYYY-MM，拒绝年份 0000，避免前月计算下溢。
- 插件无直接网络或文件 IO；端口未配置或 provider 失败时返回稳定、脱敏错误。

### 4.4 Creation / Interest / Experience

- Creation 严格限制生命周期转换和输入字段，不双写作品正文。
- Interest Schema 和输出不含 KPI、score、streak、target、deadline。
- Experience 状态不信任请求自报；缺少权威 reader、状态不符或 provider 异常时均安全拒绝。

## 5. TDD 与独立审查

- 六个领域均先建立失败测试，再以最小实现转绿。
- Life Admin 独立审查发现过去月份、裸月份与主机日期回退问题；补充 RED 测试并改为明确澄清。
- Creation/Interest/Experience 独立审查发现未知字段和 Experience 状态伪造风险；补充严格字段校验与权威状态读取。
- Social/Finance 独立审查发现输出长度越过 Schema、年份 0000 与 Unicode 数字月份漏洞；补充 RED 测试并修复。
- Social 额外补充缺少 reference timestamp 的失败测试，移除隐式主机时钟。

## 6. 最终验证

- WP7 六插件及 Registry/Loader 聚焦回归：89 passed。
- Social + Finance 边界复测：18 passed。
- scripts/verify.py：885 passed、47 subtests passed，退出码 0。
- 三组交叉独立审查均完成；发现项修复后复核通过。
- WP7 文件尾随空白扫描与受影响路径 diff check：通过。

## 7. 分支与工作区说明

总纲建议每个领域单独分支和提交。当前共享工作区在 WP7 开始前已有大量未提交用户修改，拆分提交会混入或误覆盖既有工作，因此本轮采用单一聚合分支并按插件目录、Schema、测试和验收报告进行逻辑隔离；没有重置、清理或提交用户修改。

## 8. 设计性运行前提

- 宿主负责在真实请求到来时激活 dormant 插件，并为 Social 提供采集时间、为 Life Admin 提供权威 today。
- Finance 生产环境必须注入 OCR、历史快照和分析端口；测试不依赖云模型。
- Experience 升格必须注入权威状态读取器；没有读取器时默认拒绝。
- 本轮所有结果均为只读结果或待审提案，真实外部写入由后续 ActionPolicy 执行链处理。

## 9. 回滚

回滚仅移除六个 WP7 插件包及 manifests、九个个人领域 Schema、Finance fixtures、对应专项测试和本报告；不得删除 WP0–WP6 的公共契约与逻辑链，也不得覆盖 WP0 前已有修改。
