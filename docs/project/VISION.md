# Clausula Product Vision

- Product: Clausula
- Positioning: a local-first operating system for investment decisions
- Scope: personal capital facts, policy, research evidence, decisions, and open capabilities
- Non-goal: an AI stock picker or autonomous trading bot

## Mission

Clausula 是个人财务与投资事实的权威系统，也是长期投资决策环境。它首先必须在
完全没有 LLM、网络服务或 Agent 的情况下成为正确、可用、可审计的软件；然后才
通过同一组 canonical capabilities 服务 CLI、Notebook、HTTP、Web、MCP 和任意
Agent runtime。

系统长期维护四类记忆：

1. **Capital State**：账户、交易、现金、持仓、成本、市场数据、估值和收益。
2. **Investment Policy**：用户当时生效的投资原则、约束、目标和违规结果。
3. **Research Knowledge**：不可变文档、Claim、Evidence、Contradiction 和 Thesis 修订。
4. **Decision Memory**：Recommendation、Decision、执行、Outcome 和 Review 的完整链路。

系统的价值不是每天制造交易建议，而是让用户随时回答：我拥有什么、这些数字来自
哪里、风险和偏离是什么、什么新信息真正改变了投资逻辑、为什么做过某项决定、
决策过程是否良好，以及哪些事项现在值得注意。

## Outcome Philosophy

Clausula 通过提升事实质量、反前视纪律、政策一致性、研究检索效率和决策反馈质量，
为更好的长期投资结果创造条件。它不保证收益，不把回测结果当作实盘真相，也不以
短期收益替代决策质量。可靠的“没有 alpha”“数据不足”“估值不完整”和“无需行动”
都是有效输出。

## Canonical Truth Boundaries

Canonical financial truth 包括经过明确 service operation 写入的账户、交易、持仓事实、
市场数据版本、Portfolio membership 和 Policy versions。以下对象不等同于事实：

- Research 文档和 Claim 是可互相矛盾的证据对象。
- Recommendation 是候选建议，默认从 `DRAFT` 开始。
- Decision 是用户或授权主体实际作出的选择，也可以是明确不操作。
- Transaction 是已经发生的经济事实，不能由 Recommendation 自动生成。
- Analytics 是带输入版本和方法版本的派生 artifact，不回写源事实。
- Agent output 是 Draft、Claim、Classification 或 Recommendation，不可直接修正 Ledger。

因此，核心链路始终保持：

```text
Document -> Claim -> Evidence -> Thesis
         -> Recommendation -> Decision -> Transaction -> Outcome -> Review
```

任何箭头都需要显式 operation、provenance 和权限，不允许通过共享 JSON 或 Agent memory
偷换实体语义。

## Product Invariants

1. Agent 不是 system of record；Agent memory 不拥有 canonical truth。
2. MCP 是 adapter，不是 domain layer；业务能力不得只存在于 MCP。
3. 每个 capability 在没有 Agent 时也可执行。
4. Ledger、估值、收益和 Policy evaluation 不依赖 LLM。
5. LLM output 不能直接修改 canonical financial truth。
6. Raw input 不可变，并回链 SourceArtifact、ImportBatch、transform/schema version 和 hash。
7. 核心事实显式区分 `effective_at`、`known_at`、`recorded_at`。
8. As-of 查询同时过滤经济时间和知识时间，禁止 hindsight contamination。
9. Proposal、Recommendation、Decision、Transaction 是不同实体。
10. Research 是 evidence，不是 financial truth；矛盾必须可共存且可追溯。
11. Plugin 只能通过受控 capability/SDK，不能获得任意 canonical SQL 权限。
12. 私人数据默认 local-first；云同步和托管是可选增强。
13. Domain、schema 和 capabilities 不包含 Codex、Hermes、Claude 等 runtime 概念。
14. v0.x 不提供自主实盘下单闭环。
15. 数据分辨率服从决策分辨率；分钟、tick、L2 和实验因子留在 Research Lab。
16. 正确的领域设计优先于 ClawAlpha 兼容性。
17. 金额、数量、费用、税和 FX 只使用 Decimal，并序列化为 canonical string。
18. 内部身份只使用 UUID；ticker 和 broker code 只是可变外部 identifier。
19. Financial facts 与 Policy/Portfolio 状态变化采用 append-only event/revision 语义。
20. 不完整或冲突的数据必须 fail closed，不能静默填零或选择方便的 provider。

## Architecture

依赖方向只能向内：

```text
Raw Sources / Brokers / Market / Documents
                    |
              Adapter Layer
                    |
           Canonical Domain Core
                    |
 Ledger - Portfolio - Policy - Decision - Research
                    |
              Analytics Layer
                    |
           Capability Registry
                    |
     CLI / Python / HTTP / MCP / Scheduler
                    |
       Web UI / TUI / Agent Clients
                    |
 Codex / Hermes / Claude / OpenCode / Human
```

Domain 不知道 SQLite、Web、MCP、Agent SDK 或具体 provider。Application services 是
canonical write gate。Analytics 接收 canonical inputs 并产生 deterministic artifacts。
Capabilities 编排服务并声明 typed schema、permissions、side effects、confirmation 和
provenance。所有 transport 都只是 capability projection。

## User Experience

无 Agent 的首屏是 Capital Cockpit，而不是聊天框。核心页面应覆盖 Overview、Accounts、
Portfolio、Allocation、Policy、Decisions、Research、Recommendations、Data、Plugins 和
Settings。用户常见流程必须低摩擦：导入、对账、看配置、模拟、记录决定、关联成交、
安排复盘和追溯证据。

Agent 主要通过页面上下文调用：解释暴露、分析集中度、比较再平衡方案、挑战 Thesis、
寻找反证、批评 Decision、解释 violation。Agent 返回结构化 artifact；聊天文本只是展示。

## Attention Model

自动化围绕明确 attention event，而不是每日内容生产：new cash、policy violation、
allocation drift、scheduled review、stale thesis、contradictory evidence、large movement、
data sync failure、reconciliation mismatch。

默认规则是：

```text
Nothing material changed -> no recommendation -> no notification.
```

## Final End-to-End Acceptance Story

Public Beta 必须自然完成以下故事，并且替换 Agent runtime 后仍成立：

```text
导入真实券商交易
-> 重建账户与持仓并完成 reconciliation
-> 获取有版本和 provenance 的日频市场数据
-> 计算资产配置、收益和可解释暴露
-> 用当时生效的 Policy 找出偏离
-> 产生值得注意的 Attention Item
-> Agent 或人调用同一组 capabilities
-> 检索 Research / Evidence / Thesis
-> 生成结构化 Recommendation Draft
-> 用户比较 alternatives 并接受或拒绝
-> 接受后创建 Decision，而不是 Transaction
-> 后续真实成交关联 Decision
-> Portfolio 更新
-> 30/90 日后生成 Review
-> 分开评估 Process Quality 和 Outcome Quality
-> 后续分析可利用完整历史，但不能看到当时未知的信息
```

## v0.x Non-Goals

不做自动实盘下单、日内择时、L2 runtime、毫秒行情、策略市场、复杂衍生品、完整税务
软件、社交交易、KOL 跟单、全自动 robo-advisor、LLM 自主改 Policy、LLM 自主修 Ledger、
复杂多 Agent orchestration、无限 provider 抽象、Kafka/Redis/微服务或默认云托管。

这些能力未来只能通过明确 Plugin/Action boundary 演进，不能污染 Core MVP。
