# Body OS Phase 1 — 项目交接文档

> 生成时间：2026-07-28 23:50
> 项目：个人混合管理系统 `D:/个人混合管理系统/`
> 负责 Agent：甲乙簿

---

## 一、项目摘要

Body OS 是「个人混合管理系统」的新增物理身体管理子系统——以力量训练/塑形为核心、中长跑作为心肺底座的身体资产管理模块。

当前处于 **Phase 1 设计方案已定、Garmin 数据接入正在调试**的阶段。

---

## 二、架构决策（已锁定，不可变）

### 2.1 Skill 粒度：5 Skill

| 编号 | Skill 名 | 职责 | 状态 |
|------|----------|------|------|
| yushu_10 | 身体总管_BodyController | 决策入口、调度层 | 待创建 |
| yushu_11 | 力量塑形_StrengthSystem | 训练计划、记录、渐进超负荷 | 待创建 |
| yushu_12 | 营养管理_NutritionSystem | 蛋白质、补剂、营养策略 | 待创建 |
| yushu_13 | 恢复管理_RecoverySystem | 睡眠、疲劳、活动度 | 待创建 |
| yushu_14 | 身体分析_BodyAnalytics | 趋势分析、Body Score | 待创建 |

**命名规范**：必须对齐现有 `yushu_NN_中文_English` 模式，不要用连字符命名。

### 2.2 数据模型：3 新 + 1 升级

| 模型 | 类别 | 飞书表 | 说明 | 状态 |
|------|------|--------|------|------|
| TrainingLog | 01_核心执行 | 新建 | 力量+跑步统一记录，activity_type 区分 | Schema 待创建 |
| NutritionLog | 01_核心执行 | 新建 | Phase 1 只记蛋白质+饮水 | Schema 待创建 |
| BodyMetrics | 02_成长管理 | 新建 | 体重/体脂/围度/静息心率/长期趋势 | Schema 待创建 |
| Energy（升级） | 01_核心执行 | 原地升级 | 增加 sleep_hours/soreness/readiness_score，作为 Controller 每日状态输入源 | 待升级 |

### 2.3 架构原则

```
Personal Hybrid OS
  └── Body OS
        └── yushu_10_身体总管_BodyController  ← 唯一入口
              ├── yushu_11_力量塑形_StrengthSystem
              ├── yushu_12_营养管理_NutritionSystem
              ├── yushu_13_恢复管理_RecoverySystem
              └── yushu_14_身体分析_BodyAnalytics
                      ↓
              Schema 层（TrainingLog / NutritionLog / BodyMetrics / Energy）
                      ↓
              飞书 Base（存储）
```

**核心原则**：
- 用户不应该思考调哪个 Skill → 全部通过 Controller 入口
- 跑步不独立成 Skill/Table → 归入 TrainingLog，用 `activity_type=running` 区分
- 补剂不独立成 Skill → 合入 NutritionSystem
- Garmin 数据只作为传感器层 → 不直接耦合业务逻辑

---

## 三、Phase 1 已完成的搭建

### 3.1 技术环境

| 项 | 状态 |
|----|------|
| Garmin MCP server 安装 | ✅ `garmin-mcp-server==0.3.4` |
| garminconnect 库安装 | ✅ `garminconnect==0.3.7` |
| curl_cffi 安装 | ✅ `curl_cffi==0.15.0` |
| Python venv 创建 | ✅ `C:\Users\26326\.workbuddy\binaries\python\envs\default` |
| mcp.json 配置 | ✅ 已新增 garmin server |
| MCP 可执行文件 | ✅ 均可启动 |
| MCP 工具数量 | ✅ 89 个 Garmin tools 自动注册 |

### 3.2 安全修复

- ✅ `C:\Users\26326\.garminconnect\cn_login.py` 已脱敏，硬编码密码已移除，改为环境变量/运行时输入读取
- ✅ `mcp.json` 不包含 Garmin 账号密码
- ✅ Garmin 中国区账号已设 `GARMIN_IS_CN=true`

### 3.3 配置文件路径

| 文件 | 路径 |
|------|------|
| WorkBuddy MCP 配置 | `C:\Users\26326\.workbuddy\mcp.json` |
| Garmin token 存储 | `C:\Users\26326\.garminconnect\garmin_tokens.json` |
| CN 专用登录脚本 | `C:\Users\26326\.garminconnect\cn_login.py` |
| Garmin MCP server | `C:\Users\26326\.workbuddy\binaries\python\envs\default\Scripts\garmin-mcp-server.exe` |
| Garmin 登录工具 | `C:\Users\26326\.workbuddy\binaries\python\envs\default\Scripts\garmin-mcp-server-login.exe` |
| Python 环境 | `C:\Users\26326\.workbuddy\binaries\python\envs\default` |

---

## 四、Phase 1 剩余工作量

### 4.1 阻塞项：Garmin 认证（需用户手动执行）

**问题描述**：
- `garmin_tokens.json` 有 DI token（`di_client_id`、`di_refresh_token`、`di_token` 非空）
- 但 `jwt_web` 为**空**
- 导致 MCP 工具调用失败：`No valid Garmin tokens found`

**原因**：中国区 Garmin 账号（garmin.cn）需要特定 portal+cffi 认证策略才能完整生成 token，标准 `garmin-mcp-server-login.exe` 可能不兼容。

**解决方式**：用户需要在终端交互式运行 CN 补丁登录脚本：

```bash
GARMIN_IS_CN=true GARMIN_TOKEN_DIR="C:/Users/26326/.garminconnect" "C:/Users/26326/.workbuddy/binaries/python/envs/default/Scripts/python.exe" "C:/Users/26326/.garminconnect/cn_login.py"
```

执行后会提示输入邮箱、密码、MFA 验证码。

**成功标志**：

```text
Tokens saved to: C:\Users\26326\.garminconnect\garmin_tokens.json
File size: ...
User: ...
```

**失败处理**：
- 如果失败，尝试标准 MCP 登录：

```bash
GARMIN_IS_CN=true GARMIN_TOKEN_DIR="C:/Users/26326/.garminconnect" "C:/Users/26326/.workbuddy/binaries/python/envs/default/Scripts/garmin-mcp-server-login.exe"
```

- 如果标准登录也失败，考虑走同步脚本路线（不走 MCP）直接调 `garminconnect` 库生成原始 JSON。

### 4.2 MCP 配置后激活

用户需到 WorkBuddy 连接器管理页右上角自定义连接器入口，找到 `garmin`，点击 **Trust** 后 MCP 才实际生效。

### 4.3 待创建的文件清单

| 文件 | 优先级 |
|------|--------|
| Schema/TrainingLog.json | P0 |
| Schema/NutritionLog.json | P0 |
| Schema/BodyMetrics.json | P0 |
| Schema/Energy.json（升级版） | P0 |
| Garmin 7 天同步脚本 | P0 |
| 5 个 Body OS Skill 的 SKILL.md | P1 |
| 系统注册表更新（yushu_00） | P1 |

### 4.4 待确认事项

| 事项 | 状态 |
|------|------|
| 用户 Garmin 账号邮箱 | 已确认：`2632610394@qq.com`（中国区 garmin.cn） |
| Garmin 登录是否需 MFA | 待确认 |
| Energy 模型升级字段定义 | 待确认 |
| 飞书 Base 新增表创建 | 待确认 |
| 是否使用 WorkBuddy MCP connector 管理页 Trust 激活 | 待确认 |

---

## 五、Phase 1 验收标准

```text
1. Garmin 认证成功 → MCP get_full_name 可调用
2. 拉取最近 7 天至少 3 类数据：睡眠/恢复、活动/训练、心率/压力
3. 生成 raw_garmin_7d.json（原始精简）
4. 生成 body_os_mapped_7d.json（映射成 Body OS 字段）
5. 基于映射结果能回答：今天适合力量训练、Zone2、恢复、还是降载
```

---

## 六、关键风险

| 风险 | 描述 | 缓解措施 |
|------|------|---------|
| Garmin 非官方 API 稳定性 | garminconnect 库基于逆向工程，Garmin 可能改接口 | 隔离为传感器层，变换数据源不影响 Body OS 业务 |
| 中国区账号兼容性 | garmin.cn 域名认证流程与 .com 不同 | 已用 CN portal+cffi 补丁脚本，保留纯同步脚本备选 |
| 手动数据输入疲劳 | 营养追踪等用户输入类功能坚持率低 | Phase 1 只追踪蛋白质一个指标，且只要求每天输入一个数字 |
| Skill 数量膨胀 | 10+ Skill 会使导航和 AI 调度复杂化 | 已收敛为 5 Skill，并用 Controller 作为唯一入口 |

---

## 七、与现有系统的集成点

| 集成点 | 说明 |
|--------|------|
| 系统注册表 `yushu_00` | 需注册 Body OS 的 5 个新 Skill 和 4 个数据模型 |
| 输入解析引擎 `yushu_01` | 需新增 `#训练` `#身体` 等 Body OS 指令路由 |
| Energy 模型 | 需升级，增加睡眠/恢复字段；Body OS 和每日排程共用 |
| 飞书 Base | 需创建新表 TrainingLog、NutritionLog、BodyMetrics |

---

## 八、对话上下文摘要

本项目的决策历程（方便接手的 Agent 理解上下文）：

1. **最初**：用户想做「跑步系统」
2. **重新定位**：改成以力量训练/塑形为核心、中长跑作为心肺底座的身体管理系统
3. **架构设计**：确定 5 Skill 方案（BodyController + 4 能力模块），拒绝 3 Skill（缺控制层）和 10+ Skill（太碎）
4. **设备选型**：用户用 Garmin 手表，数据作为传感器层接入
5. **接入路径**：同时做 Garmin MCP（交互查询）+ garminconnect 同步脚本（数据沉淀）
6. **认证瓶颈**：中国区 garmin.cn 账号 token 不完整，等待用户交互登录
7. **安全修复**：cn_login.py 已脱敏，移除硬编码密码
