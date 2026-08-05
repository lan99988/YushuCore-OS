# Phase 4 Known Limitations

## 外部服务

- Obsidian 本地 Vault 握手尚未在目标用户环境执行。
- llm_wiki 本地服务、MCP 双闸和实际 Token 尚未联调。
- Feishu API、审批人身份和生产凭据尚未联调。

## 运行模式

- 离线测试使用注入式 Client，不代表真实服务的可用性或吞吐量。
- `OFF` 模式不会执行外部网络调用；`ASSIST` 与 `SYNC` 需要显式策略启用。
- 外部 API 的真实限流、服务端幂等语义仍需联调验证。

## 数据与运维

- 当前性能验证针对本地 Markdown 和小规模状态数据，尚未完成大规模 Vault 压测。
- Git 回滚和 Feishu 补偿 Proposal 已有契约测试，但尚未进行生产灾备演练。
- 社区 Obsidian 插件评估已冻结为门槛，尚未授权自研插件。

## 不属于缺陷的明确排除

- llm_wiki.exe 未修改。
- llm_wiki 不提供文件写入接口。
- Feishu 不保存知识正文。
- Phase 5 Self Model、Decision Model 和 Personal Autonomous Intelligence 不属于 Phase 4 实现范围。
