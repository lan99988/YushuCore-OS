# Phase 5 Personal Model Interface Specification

## 定位

本接口只为未来 Personal Model、Prompt、Policy 和 Router 版本化预留边界，不训练模型、不上传个人核心认知、不替换基础模型。

## 接口

```text
ModelDescriptor describe_model()
ModelRoute select_route(task, sensitivity, network_mode)
ModelResponse analyze(context, prompt_version, policy_version)
```

## 强制字段

```yaml
model_id:
model_version:
prompt_version:
policy_version:
provider:
local_only:
max_sensitivity:
```

## 安全规则

- 默认使用本地模型。
- Level 3/4 数据不得发送到云模型，除非存在显式授权和审计记录。
- Model、Prompt、Policy 版本必须可追踪和回滚。
- `analyze` 只能返回分析或 Proposal，不得触发写入和外部执行。
- LoRA/Fine-tune/Personal Model 训练进入独立 Design Review，不属于当前 Phase 5.1-5.3。
