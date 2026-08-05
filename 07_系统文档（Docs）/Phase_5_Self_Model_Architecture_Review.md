# Phase 5 Self Model Architecture Review

| Layer | 数据来源 | 更新方式 | 权限等级 | AI 能力范围 |
|---|---|---|---|---|
| Identity Layer | Human 明确声明、身份资料 | Human Only | Level 4 | 授权读取、有限分析、禁止建议和修改 |
| Value Layer | Human 价值排序、长期选择 | Human Review | Level 4 | 读取、有限分析、可提出问题，禁止自动修改 |
| Principle Layer | `03_Principles`、批准后的原则记录 | Proposal + Human Approval | Level 3/4 | 读取、有限分析、可提出建议，禁止自动修改 |
| Preference Layer | 已批准偏好、稳定选择 | Proposal + Human Approval | Level 2/3 | 读取、分析、建议，修改需确认 |
| Behavior Pattern Layer | Decision History、Life Log、Agent 分析 | Proposal + Human Approval | Level 2 | 读取、分析、建议，修改需确认 |
| Experience Layer | 训练、学习、项目和反思记录 | 追加记录 + Review | Level 2 | 读取、分析、建议，写入需确认 |

## 分层规则

- 高层数据不能由低敏层自动推断为事实。
- 推断结果必须标记为 observation 或 proposal，不得伪装成 Identity/Value/Principle。
- Agent 默认不得直接访问 Identity、Value 和 Principle；必须使用 Gateway 临时授权。
- 所有层都保留来源、置信度、状态、版本和更新时间。
