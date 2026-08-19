# Clausula Project Context

本目录是 Clausula 的长期上下文入口。开始任何新 milestone、语义审计或
fresh-context 工作前，按以下顺序阅读：

1. 根目录 `AGENTS.md`：不可违反的产品与工程约束。
2. `docs/project/VISION.md`：产品目标、事实边界和最终验收故事。
3. `docs/project/STATUS.md`：当前已冻结成果、未提交工作和真实测试状态。
4. `docs/project/IMPLEMENTATION_PLAN.md`：从当前断点到 Public Beta 的实施顺序。
5. `docs/adr/`：已经接受的语义决定。
6. `capability_mapping.yaml` 与 `migration_inventory.yaml`：能力和旧资产映射。

这些文档的职责不同：Vision 只记录长期稳定方向；Status 可以频繁更新；
Implementation Plan 记录依赖、验收门槛和接续步骤；具体领域裁决进入 ADR。

当前 fresh-thread handoff 同时保存在：

```text
/tmp/clausula-handoff-20260819/
```

`STATUS.md` 是判断“什么已经完成”的唯一入口。存在代码不代表 milestone 已冻结；
必须完成 deterministic tests、semantic/architecture audit、remediation、完整回归和
独立提交，才可将状态改为 frozen。
