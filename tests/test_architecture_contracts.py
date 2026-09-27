from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "07_系统文档（Docs）"
ADR_DIR = DOCS / "ADR"

REQUIRED_GOVERNANCE_DOCS = {
    "PROJECT_CHARTER.md",
    "ARCHITECTURE_V2.md",
    "PLUGIN_STANDARD.md",
    "AUTONOMY_POLICY.md",
    "DOMAIN_REGISTRY.md",
}

EXPERIENCE_FLOWS = {"Capture", "Plan", "Today", "Adjust", "Review", "Explore"}
ARCHITECTURE_LAYERS = {
    "Experience Layer",
    "Cognitive Core",
    "Orchestration Layer",
    "Capability Plugin Layer",
    "Data / Integration Layer",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_governance_documents_exist():
    existing = {path.name for path in DOCS.iterdir() if path.is_file()}

    assert REQUIRED_GOVERNANCE_DOCS <= existing
    assert (ADR_DIR / "ADR-010_Experience_Orchestration_Plugin_Architecture.md").is_file()


def test_project_charter_freezes_all_experience_flows():
    charter = _read(DOCS / "PROJECT_CHARTER.md")

    assert all(flow in charter for flow in EXPERIENCE_FLOWS)


def test_project_charter_stays_at_mission_value_scope_and_non_goals():
    charter = _read(DOCS / "PROJECT_CHARTER.md")
    headings = re.findall(r"^## \d+\. (.+)$", charter, flags=re.MULTILINE)

    assert headings == ["使命", "用户价值", "范围", "非目标"]


def test_architecture_v2_maps_all_five_layers():
    architecture = _read(DOCS / "ARCHITECTURE_V2.md")

    assert all(layer in architecture for layer in ARCHITECTURE_LAYERS)
    assert "依赖只能自上而下" in architecture
    assert "上层只能调用下层公开接口" in architecture
    assert "Experience Layer | WorkBuddy、现有输入入口 | experience_layer" in architecture
    assert (
        "Cognitive Core | runtime_core.context / permissions / approval、"
        "cognitive_system、personal_intelligence"
    ) in architecture
    assert (
        "Orchestration Layer | runtime_core.kernel / router / scheduler | orchestration"
    ) in architecture
    assert "Capability Plugin Layer | handlers、agents、integrations 的现有能力 | capability_plugins" in architecture
    assert (
        "Data / Integration Layer | information_system、knowledge_system、"
        "integrations、飞书引擎"
    ) in architecture
    assert "联邦式事实源" in architecture
    assert "Knowledge Gateway" in architecture
    assert "飞书" in architecture
    assert "information_system" in architecture
    assert "Garmin" in architecture
    assert "移动端触达状态" in architecture
    assert "财务 | 月度快照" in architecture
    assert "runtime_core.context" in architecture
    assert "runtime_core.kernel" in architecture
    assert "概念层不与 Python 包一一对应" in architecture


def test_architecture_v2_pairs_each_data_class_with_its_authority():
    architecture = _read(DOCS / "ARCHITECTURE_V2.md")

    assert "任务、日历、项目执行态、承诺和移动端触达状态 | 飞书" in architecture
    assert "知识正文、经验、方法和原则 | D:\\Knowledge | 经 Knowledge Gateway" in architecture
    assert "认知资产投影 | IMA + 飞书双持久化 | 经 cognitive_system" in architecture
    assert "信息对象、识别状态、领域观察 | information_system SQLite" in architecture
    assert "身体原始数据 | Garmin / Body Dataset" in architecture
    assert "系统配置、插件清单 | Git 版本化本地文件" in architecture
    assert "财务 | 月度快照 | Finance Plugin" in architecture
    assert "IMA 是信息正文来源和捕获入口，不是业务数据库，也不是知识事实源" in architecture


def test_plugin_standard_separates_skill_from_plugin():
    standard = _read(DOCS / "PLUGIN_STANDARD.md")

    assert "Skill ≠ Plugin" in standard
    for field in (
        "domain",
        "availability",
        "enabled",
        "activation_state",
        "input_contract",
        "output_contract",
        "error_policy",
        "audit_policy",
        "capability_priorities",
        "capability_priority_reasons",
    ):
        assert field in standard
    assert "invoke(capability, payload, context)" in standard
    assert "partial_failure" in standard


def test_autonomy_policy_does_not_raise_agent_autonomy_for_approval():
    policy = _read(DOCS / "AUTONOMY_POLICY.md")

    assert "动作权限" in policy
    assert "Agent 自治等级" in policy
    assert "Approval Required" in policy
    assert "不表示" in policy
    assert "Level 2" in policy
    assert "权限拒绝不能通过审批解除" in policy
    assert "已注册且 ready" in policy


def test_domain_registry_freezes_low_friction_domain_rules():
    registry = _read(DOCS / "DOMAIN_REGISTRY.md")

    for domain in ("Goal", "Project", "Task", "Calendar", "Learning", "Knowledge", "Body"):
        assert domain in registry
    for domain in ("Social", "Finance", "Life Administration", "Creation", "Interest", "Experience"):
        assert domain in registry
    assert all(state in registry for state in ("Dormant", "Active", "Archived"))
    assert "Observation → Candidate → 用户确认" in registry
    assert "月度快照" in registry
    assert "渐进激活" in registry
    assert "不强制任务化" in registry


def test_network_default_remains_off():
    config = yaml.safe_load((ROOT / "config" / "network.yaml").read_text(encoding="utf-8"))
    network_mode = config["network_mode"]
    if network_mode is False:
        network_mode = "OFF"

    assert str(network_mode).upper() == "OFF"


def test_default_and_registered_agent_autonomy_do_not_exceed_two():
    system_config = yaml.safe_load((ROOT / "config" / "system.yaml").read_text(encoding="utf-8"))
    registry_config = yaml.safe_load((ROOT / "agents" / "registry.yaml").read_text(encoding="utf-8"))
    agents = registry_config["agents"]

    assert system_config["default_autonomy_level"] <= 2
    assert agents
    assert all(type(agent["autonomy_level"]) is int for agent in agents)
    assert all(0 <= agent["autonomy_level"] <= 2 for agent in agents)


def test_permission_defaults_preserve_runtime_boundaries():
    permission_config = yaml.safe_load(
        (ROOT / "config" / "permission.yaml").read_text(encoding="utf-8")
    )

    assert permission_config["default"] == "deny"
    assert permission_config["agent_direct_vault_access"] is False
    assert permission_config["agent_direct_external_api"] is False
    assert {
        "knowledge_change",
        "personal_memory_change",
        "core_self_model_change",
        "external_execution",
    } <= set(permission_config["human_approval_required_for"])


def test_strangler_migration_keeps_legacy_entrypoints():
    assert (
        ROOT / "02_执行引擎（Engine）" / "输入解析引擎" / "input_parser_old.py"
    ).is_file()
    assert (
        ROOT / "02_执行引擎（Engine）" / "输入解析引擎" / "handlers" / "body_os.py"
    ).is_file()


def test_legacy_single_source_wording_is_explicitly_historical():
    blueprint = _read(DOCS / "SYSTEM_BLUEPRINT.md")
    decisions = _read(DOCS / "DECISION_LOG.md")

    assert "旧“飞书唯一事实源”表述仅作为历史记录" in blueprint
    assert "D3 保留为历史记录" in decisions
    assert "为唯一数据中枢" not in blueprint
    assert "飞书 Base 为事实源" not in blueprint


def test_adr_010_reconciles_cognitive_dual_persistence():
    architecture = _read(DOCS / "ARCHITECTURE_V2.md")
    adr = _read(ADR_DIR / "ADR-010_Experience_Orchestration_Plugin_Architecture.md")
    adr_009 = _read(ADR_DIR / "ADR-009_Knowledge_Storage_Dual_Persistence.md")

    assert "认知资产投影" in architecture
    assert "IMA + 飞书双持久化" in architecture
    assert "ADR-009" in adr
    assert "不取代 ADR-009" in adr
    assert "ADR-010 权威语义修订" in adr_009
    assert "投影不是知识正文权威" in adr_009


def test_versioned_entry_documents_do_not_embed_base_token():
    readme = _read(ROOT / "README.md")
    blueprint = _read(DOCS / "SYSTEM_BLUEPRINT.md")

    assert "飞书 Base Token：" not in readme
    assert "飞书 Base Token：" not in blueprint
    assert re.search(r"TtzI[A-Za-z0-9]{20,}", readme) is None
    assert re.search(r"TtzI[A-Za-z0-9]{20,}", blueprint) is None
