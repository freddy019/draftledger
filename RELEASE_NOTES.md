# DraftLedger v0.1.0-alpha.1

## 中文介绍

DraftLedger（稿脉）是一个面向长期 AI 创作的过程状态与多智能体接力层。它适用于文案策划、小说、剧本、世界观、研究综述、咨询报告、品牌与产品叙事等难以从成品倒推出过程的项目。

它保存已经核验的事实、仍待验证的假设、当前有效的指令、决策及其依据、被否决的方向、未决事项，以及不同 AI 线程之间的任务归属，使长期项目可以检查、修订和接力。

首个公开 Alpha 包含：

- 带生命周期的事实、假设、指令、决策和未决事项；
- 上下文编译、来源追踪、污染检测，以及控制层与数据层隔离；
- 状态差异比较、决策重验证和追加式状态版本控制；
- 面向多线程、多 AI 协作的机器可读接力文件，支持任务认领、租约、接管、范围冲突、依赖、进度、阻塞、取消与完成；
- 严格 JSON 解析、原子写入、并发锁、确定性测试和可复现发布包。

> **测试版提示：** 这是 `v0.1.0-alpha.1` 实验性预览，预期会有缺陷和破坏性变更。公开 Schema、命令与工作流在 v1.0 前不承诺向后兼容，请勿无人值守地用于关键生产流程。

## English

DraftLedger preserves the process that a finished artifact cannot reconstruct: verified facts, working assumptions, active instructions, decisions and their rationale, rejected directions, unresolved questions, and ownership across AI threads.

This first public alpha is aimed at long-running creative and knowledge projects such as copywriting, content planning, novels, scripts, worldbuilding, research synthesis, consulting reports, strategy, naming, and UX writing.

## Included

- Typed governed state with lifecycle-aware facts, assumptions, instructions, decisions, and open items.
- Context compilation, provenance tracing, contamination detection, semantic-retrieval gating, and a strict control/data boundary.
- State diff, explicit decision revalidation, and append-only local state version control.
- A machine-readable handoff board for multi-thread and multi-agent work, including claims, leases, takeovers, scope collision checks, dependencies, progress, blockers, cancellation, and completion.
- Strict bounded JSON parsing, atomic writes, advisory locking, deterministic tests, release auditing, and reproducible ZIP packaging.

## Alpha notice

Expect defects and breaking changes. Public schemas, commands, and workflows may change without backward-compatibility guarantees before v1.0. Do not run this preview unattended in critical production workflows.

The package version is `0.1.0-alpha.1`. Machine-readable state, context, and handoff documents currently use `version: "1.0"` as an internal format identifier retained from development; that identifier is not a public stability promise.

Runtime: Python 3.11+ with no third-party runtime dependencies. `jsonschema` is used only by development and release verification.

See [FINAL_AUDIT.md](FINAL_AUDIT.md) for verification evidence and [SECURITY.md](SECURITY.md) for the trust boundary and known limits.
