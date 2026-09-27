# WP1 插件契约与注册中心验收报告

> 日期：2026-09-26
> 结论：PASS
> 分支：codex/yushu-wp1-plugin-registry
> 起点 HEAD：b9ef2e8d16ab916fd758e5e485bda26c6bb5bf29

## 1. 目标与边界

WP1 只建立能力插件的声明、加载、发现、生命周期和审计骨架，不迁移现有业务实现，不动态导入插件代码，也不执行任何外部写入。

本轮继续保留工作区在 WP0 前已存在的未提交变化，没有重置、清理或恢复用户文件。

## 2. 交付物

新增：

- capability_plugins/__init__.py
- capability_plugins/contracts.py
- capability_plugins/manifest.py
- capability_plugins/loader.py
- capability_plugins/registry.py
- capability_plugins/lifecycle.py
- capability_plugins/manifests/ 下 8 份首批能力声明
- tests/test_capability_contracts.py
- tests/test_capability_loader.py
- tests/test_capability_registry.py
- tests/test_verify_script.py

修改：

- scripts/verify.py：使用当前 Python 解释器运行 pytest，并编译 capability_plugins。
- PLUGIN_STANDARD.md：补齐 domain 与多 provider 优先级字段。
- tests/test_architecture_contracts.py：锁定新增标准字段。

## 3. 已冻结的行为

- Availability、Enabled、ActivationState 为三个正交维度。
- Manifest 严格拒绝缺失字段、未知字段、非法枚举、非法 domain、重复 capability 和错误字段类型。
- activation_mode 仅允许 always 与 on_demand。
- Registry 拒绝重复 plugin_id、缺失/不可用依赖、自依赖和依赖环。
- capability 多 provider 必须同时声明优先级与选择理由，最高优先级必须唯一。
- 优先级和理由可由 YAML Manifest 直接声明，并由 from_manifests 自动使用。
- provider 选择只在 ready provider 中进行；高优先级 dormant、disabled、unavailable 或 archived provider 不会遮蔽可用 fallback。
- disabled、dormant、unavailable、archived、missing_dependency、dependency_unavailable 和 ready 状态可分别解释。
- Registry 从 YAML 构建时按 plugin_id 稳定排序，输入顺序不影响能力清单与注册审计顺序。
- Loader 只使用 PyYAML safe_load 读取 UTF-8 声明，不导入实现、不访问网络、不触发外部系统。
- 生命周期 reason 只允许受控 reason_code，审计事件不记录 payload 或自由文本正文。
- 首批登记 task、calendar、project、goal、learning、knowledge、body、information；无法证明完整实现的 goal 明确标记 unavailable，未伪装成可用能力。

## 4. TDD 证据

主要 RED：

- 契约包不存在时，合同测试因缺少 capability_plugins 失败。
- loader 不存在时，11 项加载测试按预期失败。
- registry/lifecycle 不存在时，注册测试在收集阶段按预期失败。
- 集成验收新增后出现 5 项失败：缺失/空目录静默成功、无 YAML→Registry 构建入口、生命周期审计缺 actor/reason_code、verify 选择错误 Python。
- 架构复审新增后，provider 状态过滤、YAML 优先级元数据、不可用依赖和受控 reason_code 用例先失败。
- PLUGIN_STANDARD 缺少 domain 和优先级字段时，架构合同测试失败。

对应 GREEN：

- 实现严格合同、loader、registry 和 lifecycle 后，基础 WP1 测试通过。
- 补充 from_manifests、目录错误、审计元数据和当前解释器验证后，集成测试通过。
- 修复 ready-only provider 选择、YAML 优先级、依赖状态与 reason_code 后，专项测试通过。
- 补充失败注册/非法转换事务性、输入顺序确定性和实际 YAML 多 provider 端到端测试后均通过。

## 5. 最终验证

- WP1 合同、loader、registry、verify 专项测试：全部通过。
- WP0 架构合同与 WP1 专项联合测试：全部通过。
- scripts/verify.py：550 passed、47 subtests passed；compileall、配置只读约束和 Agent 边界检查全部通过，退出码 0。
- capability_plugins 从项目虚拟环境解析到仓库内新包；未使用会与宿主 Hermes 冲突的顶层 plugins 名称。
- scripts/verify.py scoped git diff --check：通过。
- WP1 新增文件尾随空白扫描：无命中。
- 敏感模式扫描：未发现凭证、Token、密码或 API Key。

## 6. 独立审查

- 架构复审：初审发现 2 项高风险与 2 项中风险问题；修复后复审 PASS。
- 测试充分性复审：初审发现 4 项事务性/确定性缺口；补测后复审 PASS。
- 差异与集成安全复审：PASS，无导入冲突、敏感信息或外部副作用。

## 7. 已知非阻断项

- PluginManifest 是冻结 dataclass，但合同与策略字典仍属于浅层冻结。后续应在不破坏序列化合同的前提下做不可变快照或防御性复制。
- Registry 当前只保留注册与生命周期的最小元数据审计。correlation_id、timestamp、result、payload_digest 等完整字段由 WP2 的统一 Action Policy / Audit 接管，不能把当前内存事件当作最终审计系统。
- 全仓 git diff --check 仍可能报告 WP0 前已修改的 handlers/body_os.py 行尾问题；WP1 未编辑该文件。

## 8. 外部副作用与回滚

- 外部写入：无。
- 飞书调用：无。
- Knowledge 写入：无。
- 网络访问：无。

回滚仅需移除 capability_plugins、四份 WP1 测试与本报告，并撤销 scripts/verify.py、PLUGIN_STANDARD.md 和架构合同测试中的 WP1 增量；不得覆盖这些文件在 WP1 前已有的用户修改。
