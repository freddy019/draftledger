# DraftLedger（稿脉）

**面向长期 AI 创作的过程状态与多智能体接力层。**

DraftLedger 是一个面向长期创作与知识工作的 Agent Skill。它保存成品本身无法呈现的过程：资料来源、约束、工作假设、被否决的方向、决策依据，以及不同 AI 线程之间的任务归属。

> **实验性预览 · v0.1.0-alpha.1**
>
> 这是公开测试版本，预期会有问题和破坏性变更。Schema、命令和工作流都可能在没有兼容保证的情况下调整，请勿让它无人值守地运行在关键生产流程中。

运行时要求 Python 3.11+，仅使用标准库。当前机器可读文档中的 `version: "1.0"` 是内部格式标识，不代表公开 Alpha 已提供稳定性承诺。

## 它解决什么问题

大型任务持续几十轮、几天甚至几个月以后，失败往往并不是因为模型突然“不会推理”，而是因为项目状态发生了漂移：

- 自动摘要属于有损压缩；
- “暂时按 30% 假设”经过几轮摘要后可能变成“就是 30%”；
- 很早以前的一条临时要求可能继续影响现在的回答；
- 新旧指令发生冲突，但模型没有显式处理；
- 决策结论保留下来了，决策理由和前提却消失了；
- Session 或 Agent 交接时只传递一段 prose summary，真正的状态没有传递；
- 用户无法知道究竟是哪条历史 prompt 还在影响模型。

这套方法把问题定义为 **State Governance（状态治理）**，而不是简单的 Memory（记忆）问题。

## 它适合什么项目

DraftLedger 最适合那些**很难从最终结果倒推出创作过程**的项目，例如：

- 文案、内容策划、营销活动、品牌语气与编辑日历；
- 小说、剧本、游戏叙事、世界观设定等强连续性创作；
- 研究综述、咨询报告、政策草案与战略规划；
- 产品叙事、UX 文案、命名和定位项目；
- 跨多轮、多天、多线程或多个 AI Agent 的长期内容工程。

一份完成度很高的成品，通常看不出哪些事实已经核验、哪些仍是假设、某个方向为什么被否决、哪条要求已经失效，或下一步究竟由谁负责。DraftLedger 把这部分看不见的过程保留下来，使它可以检查、修订和接力。

## 核心结构

```text
原始对话 / 文件 / 工具结果
            │
            ▼
┌──────────────────────────┐
│      Governed State      │
│                          │
│  Facts       已确认事实   │
│  Assumptions 工作假设     │
│  Instructions 有效指令    │
│  Decisions   已做决策     │
│  Open Items  未决事项     │
└──────────────────────────┘
            │
            ▼
       当前推理上下文
            │
            ▼
         派生摘要
```

一句话：**摘要只是缓存，不是数据库。**

## 最关键的区别

这套 Skill 不只是让 AI “多记一点”，而是要求每一类重要状态拥有明确的生命周期。

例如：

- Fact：`active / disputed / superseded`
- Assumption：`active / confirmed / rejected / expired`
- Instruction：`active / superseded / expired / revoked`
- Decision：`active / superseded / reversed`

这样，“暂时假设”就不会因为出现次数多而悄悄升级成“事实”；已经失效的 prompt 也不会永久残留在任务里。

## Context Compiler

Context Compiler 用于在推理开始前主动减少上下文污染。它不会把整个项目历史塞给模型，而是针对当前任务，只从 Governed State 中选择最小必要的 active state。

选择顺序为：显式要求的 ID → 当前 scope 生效的 Instruction → 与任务目标相关的 active state → 被选中 Decision 的依赖闭包。若必要控制状态超过预算，编译直接失败，而不是静默丢弃。

```bash
python scripts/context_compile.py examples/sample-state.json \
  --task-file examples/compiler-task.json \
  --context-output /tmp/context.txt \
  --manifest-output /tmp/context-manifest.json
```

输出的 Context Manifest 可以继续交给 `context_trace.py` 做 provenance 与 contamination 检查。详见 `references/context-compiler.md`。

## Semantic Retrieval 与 Trust Boundary

DraftLedger 允许 embedding、LLM retriever 或向量数据库参与上下文召回，但它们只有“提名权”，没有“解释权”和“指令权”。Retriever 只能返回已经存在于 Governed State 中的 ID 与 0~1 的相关度分数；Compiler 会重新检查 lifecycle、scope、exclude、authority 和 trust。

```bash
python scripts/retrieval_gate.py \
  examples/sample-state.json \
  examples/compiler-task.json \
  examples/semantic-candidates.json

python scripts/context_compile.py examples/sample-state.json \
  --task-file examples/compiler-task.json \
  --semantic-candidates examples/semantic-candidates.json \
  --output /tmp/compiled-context.json
```

编译后的上下文明确分成 `CONTROL PLANE` 与 `DATA PLANE`。只有 Governed State 中 active、scope 匹配、authority=`control` 且 trust 为 `trusted/reviewed` 的 Instruction 才能进入控制层。Fact、Assumption、Decision、网页、文件、工具结果或 retriever 返回的文本，即使里面包含“忽略之前指令”之类的命令句，也只能作为数据。

核心原则：**Data 不能因为进入 Context 就自动升级为 Instruction。**

详见 `references/semantic-retrieval.md` 与 `references/trust-boundary.md`。

## Hardening

DraftLedger 对状态与控制边界进行了可靠性和安全加固。所有 CLI 的 JSON 输入使用 strict parser：拒绝重复 key、`NaN/Infinity`、非法 UTF-8，并限制文件大小、嵌套深度、节点数量和单个字符串大小；关键状态写入使用同目录临时文件、`fsync` 与原子替换。State VCS 的变更操作带有进程级 advisory lock，Context Trace 也会检测 summary provenance cycle。

可以直接运行：

```bash
python scripts/hardening_check.py examples/sample-state.json --strict
```

测试集同时加入确定性 fuzz、Checkpoint 篡改检测、并发 VCS 写入、symlink-safe 原子替换，以及中英文 prompt injection regression corpus。详见 `references/hardening.md`。这些检查用于降低已知风险，并不等价于“证明不存在漏洞”。

## Context Audit

Skill 定义了一个核心操作：**Context Audit**。

它会把当前正在影响模型的关键状态摊开：

```text
Active instructions: 8
Active assumptions: 5
Unverified assumptions: 2
Superseded instructions: 11
Active decisions: 4
Open items: 3
Potential conflicts: 1
```

用户可以直接撤销、修改 scope、确认或 supersede 某一条状态，而不是发现回答“不对劲”以后，只能不断重写 prompt。

## 设计原则

- Facts 和 Assumptions 必须分离；
- Instruction 必须具有 scope、priority 和生命周期；
- Decision 必须保留 rationale 和依赖前提；
- Compression 不允许改变信息的 epistemic status；
- 优先增量更新，不要每轮重写整个状态；
- 状态必须可审计、可编辑、可撤销；
- Raw history 保留为证据，Governed State 负责驱动当前任务。


## Context Lint

除了语义层面的 `Context Audit`，Skill 还提供确定性的 `Context Lint`。

Audit 负责判断“当前状态是否仍然合理”；Lint 负责检查“状态是否违反了生命周期和依赖关系的不变量”。它可以机械检查：

- ID 重复或引用断裂；
- active decision 仍依赖 superseded fact；
- active decision 仍依赖 rejected / expired assumption；
- instruction supersession cycle；
- 同一个 `key + scope + scope_id` 同时存在多个 active instruction；
- assumption 已 confirmed，但没有被提升为 fact。

无需第三方依赖：

```bash
python scripts/context_lint.py .agent-state/state.json
python scripts/context_lint.py .agent-state/state.json --strict
python scripts/context_lint.py .agent-state/state.json --json
```

这里的核心思路是：**能机械验证的状态错误，不应该继续依赖模型“自己发现”。**

## State Diff 与依赖重验证

只有“当前状态”还不够。事实、假设或指令发生变化后，旧决策可能仍然存在，但其前提已经失效。`State Diff` 会比较两个状态快照，并沿着依赖关系找出需要重新验证的决策。

```bash
python scripts/state_diff.py before.json after.json
python scripts/state_diff.py before.json after.json --fail-on-review
python scripts/state_diff.py before.json after.json --write-review-state state.review.json
```

核心规则：**允许前提变化，但不允许继续静默信任建立在旧前提上的结论。**


## 显式 Revalidation Workflow

`State Diff` 只能告诉我们“哪些旧决策已经不安全”，不能证明“替换前提以后旧结论仍然成立”。Revalidation Workflow 负责显式处理这些结果。

```bash
python scripts/state_diff.py before.json after.json \
  --write-review-state state.review.json

python scripts/revalidate.py plan state.review.json \
  --output revalidation-plan.json

python scripts/revalidate.py apply state.review.json resolution.json \
  --output state.revalidated.json

python scripts/context_lint.py state.revalidated.json --strict
```

Planner 可以沿 lineage 自动找到候选替代关系，例如 `F-001 -> F-002`、`I-001 -> I-002`，也可以识别 rejected / expired assumption 形成的 blocker。

但它不会自动把旧决策重新激活。语义审核必须明确选择四种结果之一：

- `revalidated`：同一个决策在新前提下仍然成立；
- `superseded`：结论已经实质变化，新建 Decision 替代旧 Decision；
- `reversed`：旧决策明确失效；
- `blocked`：现有信息不足，继续保持 `needs_review`，并可生成 blocker。

核心原则是：**dependency migration 只是候选迁移，不等于 decision validation。**

## State Checkpoint、Branch、Rollback 与 Merge

DraftLedger 提供一层面向 Governed State 的轻量版本控制。它不是用来替代 Git，而是专门解决“同一个长期任务同时存在多套合理状态”的问题。

例如，可以把保守方案留在 `main`，把激进方案放到 `scenario-b`，两边分别修改 Facts、Assumptions、Instructions 和 Decisions，而不会互相污染。

```bash
python scripts/state_vcs.py init .agent-state/state.json
python scripts/state_vcs.py branch scenario-b
python scripts/state_vcs.py switch scenario-b --output .agent-state/state.json
python scripts/state_vcs.py checkpoint .agent-state/state.json -m "scenario B"
python scripts/state_vcs.py diff main scenario-b
python scripts/state_vcs.py switch main --output .agent-state/state.json
python scripts/state_vcs.py merge scenario-b --output .agent-state/state.json
```

它遵循几个原则：

- Checkpoint 不可修改，只能追加；
- Rollback 不会删除历史，而是创建一个“恢复到旧状态”的新 Checkpoint；
- Branch 用于隔离不同假设、方案和实验；
- Merge 使用三方合并，同一字段发生冲突时显式报错，不偷偷选择一边；
- Merge 即使结构上成功，也不代表旧 Decision 仍然成立；
- Merge 引入的 Fact / Assumption / Instruction 变化会沿依赖关系自动把相关 Decision 标记为 `needs_review`。

因此完整链路开始变成：

```text
checkpoint -> branch -> diff -> merge -> revalidate
                 \-> rollback
```

本质上，这是给长期 Agent 增加一层 **semantic state version control**。

## 多线程、多 AI 接力协作

v1.1 新增了可机器校验的接力协作板，用于多个线程、Session 或 AI 同时处理一个项目。它记录工作项范围、依赖、单一当前负责人、有期限的领取、进度、阻塞、产出与审计事件。

```bash
python scripts/handoff.py --board .agent-state/handoff.json init \
  --project-name my-project --objective "准备发布" \
  --state .agent-state/state.json

python scripts/handoff.py --board .agent-state/handoff.json add W-docs \
  --title "审核文档" --objective "检查对外声明" \
  --scope README.md --accept "声明与实际功能一致"

python scripts/handoff.py --board .agent-state/handoff.json register docs-agent \
  --thread-ref thread-123 --expected-revision 1

python scripts/handoff.py --board .agent-state/handoff.json claim W-docs \
  --agent docs-agent --expected-revision 2
```

进程锁防止本机并发写入互相覆盖，`--expected-revision` 防止读到旧版的 Agent 在稍后提交过期操作。租约过期后也不会自动转移所有权，必须显式接管并留下审计事件；依赖任务未完成时，下游任务不能被领取。

接力文件始终属于 Data Plane。即使其中包含“忽略之前指令”这类文本，也不能自行升级为 Instruction。协作板可以绑定 Governed State 指纹，便于发现“按旧状态分配的工作”。详见 [`references/multi-agent-handoff.md`](references/multi-agent-handoff.md)。

## Context Provenance 与污染检测

Context Provenance 区分两件很容易混在一起的事：**状态是否正确**，以及**真正送进模型推理的上下文是否来自正确状态**。

即使 Governed State 完全干净，旧摘要、旧 handoff、过期 memory fragment 或已经 superseded 的 instruction 仍然可能残留在当前上下文里。`context_trace.py` 用一个显式的 Context Manifest 记录本次推理实际声明使用了哪些状态和摘要，再与当前状态做校验。

```bash
python scripts/context_trace.py build .agent-state/state.json \
  --ids F-001 A-001 I-009 D-001 \
  --output .agent-state/context-manifest.json

python scripts/context_trace.py lint \
  .agent-state/state.json \
  .agent-state/context-manifest.json --strict

python scripts/context_trace.py explain \
  .agent-state/state.json \
  .agent-state/context-manifest.json
```

它可以机械发现：

- 已失效状态仍在上下文中；
- superseded instruction 仍在影响推理，而同一 key/scope 已有 active replacement；
- 同一个 ID 内容被原地修改，导致旧 snapshot 与当前状态不一致；
- 摘要依赖了失效或缺失的状态；
- summary-of-summary 的污染继续向下传播；
- 无法验证生命周期的 unmanaged context。

这里有一个明确边界：它只能审计 Agent 或 Host **声明出来的可控上下文**，不能声称读取平台隐藏 system prompt 或模型内部状态。

核心区别是：

- `Context Lint`：Governed State 自己是否正确？
- `Context Trace`：当前真正参与推理的 Context 是否来自有效状态？

数据库干净，不代表应用层没有在继续读取旧缓存。

## 使用

把整个目录放入 Agent 支持的 skills 目录即可，例如：

```text
.agents/skills/draftledger/
.claude/skills/draftledger/
.cursor/skills/draftledger/
.codex/skills/draftledger/
```

然后可以直接要求：

```text
为这个长期创作项目启用 $draftledger。
把已确认事实、工作假设、有效指令、已做决策、被否决方向和未决事项分开管理。
任何摘要都不得把假设升级成事实；项目进入新阶段前执行 Context Audit，跨 AI 线程时使用 Handoff Board 接力。
```

## 当前版本

`v0.1.0-alpha.1`：首个公开实验性预览，包含受治理状态、上下文审计以及多线程、多 AI 接力协作。运行时保持零第三方依赖。验证范围见 [最终审计](FINAL_AUDIT.md)，变更见 [发布说明](RELEASE_NOTES.md)，GitHub CI 门禁见 [发布步骤](PUBLISHING.md)。

## 发布前审计

发布前运行完整审计：

```bash
python -m pip install -r requirements-dev.txt
python scripts/release_audit.py --full --strict
```

运行时依旧零第三方依赖；`jsonschema` 只用于开发阶段校验公开 Schema 与示例。`scripts/build_release.py` 会先执行完整审计，再生成确定性的 ZIP，排除缓存和本地状态，同时输出 SHA-256 校验文件。详见 `references/release-audit.md` 与 `SECURITY.md`。

## License

MIT
