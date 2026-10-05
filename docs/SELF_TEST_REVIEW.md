# 自测方案对抗审查记录

日期：2026-10-05。最终结论：**PASS_PLAN_ONLY**。两位独立审查者未发现未解决的 P0/P1 设计阻断项。

## 审查范围与版本

- 方案：[SELF_TEST_PLAN.md](SELF_TEST_PLAN.md)，版本 1.0。
- 起草与第一轮修订：`/root/selftest_protocol_author`，`gpt-6-luna`，medium。
- 科学/评测审查：`/root/selftest_scientific_review`，`gpt-6-luna`，medium；只读，不参与起草。
- 工程/安全审查：`/root/selftest_engineering_review`，`gpt-6-luna`，medium；只读，不参与起草。
- 主 agent：编排、复核、补充阻断项、接管最后一致性修订与冻结。没有把“要求通过”理解为必须得到多 agent 优势。
- 两位审查者共同签认的 140 行版本 SHA-256：`a8faa3d5a9e11a07ab48b5ffba900569972e06c09ebea926842db20d256e1363`。
- 发布版本 SHA-256：`17a8435aad4a83ac73716cb12e2e77c8fd4876375c68f3a54baf06562162cc7b`。签认后唯一变化是第 3 行从“设计终审中”改为“设计审查通过”，并添加本审查记录链接；技术正文完全不变。

审查流程：初稿 → 两路独立审查 → 按问题逐项修订 → 主 agent 统一冻结 → 两路对同一 hash 终审。首轮并未通过；下列问题修正后才获得终审通过。

## 阻断项与关闭证据

| 编号 | 首轮问题 | 修订与关闭依据 | 状态 |
| --- | --- | --- | --- |
| SCI-STAT-01 | 六个手选问题族的 bootstrap 被用于支持优效/非劣推断，抽样目标不成立 | §3/§5 将 24 packet 限定为固定探索集；区间仅描述重采样敏感度；§6 将真正统计确认另立抽样、功效、方法和预算协议 | Closed |
| SCI-ENDPOINT-02 / ENG-01 | 实际墙钟与失败赋值 150 秒混为同一 latency 终点 | §5/§6 分开 observed wall time 与 deadline-penalized composite；只用后者作操作性筛查，并独立报告失败与真实耗时 | Closed |
| SCI-REPEAT-03 | 每案两次重复怎样进入估计量不明确 | §5 先在每 packet/arm 内平均两次重复，再算相对时间中位数与等 packet 权重的效用差；变体、重复、两臂关系在重采样中保留 | Closed |
| ENG-02 | 现有串行 84-turn 运行器不能执行新的持久/并行方案 | §6 明确新运行器/schema 尚未实现，旧运行器不可直接执行；SDK turns 与 provider 请求、重试、账单分开计数 | Closed |
| ENG-03 | 并发调用可能竞争进程全局配置环境的 set/restore | §8 指定隔离子进程环境与可信 parent 原子预算预留，必须通过重叠、取消和并发超发测试 | Closed |
| ENG-04 | 原地重写 JSON checkpoint 在崩溃时可能损坏证据 | §8 要求调用前 durable append journal、原子 checkpoint、文件及目录 fsync，并逐点崩溃恢复测试；未知请求不自动重跑 | Closed |
| ENG-05 | 四例开发集被用于功效估计，确认预算/抽样不充分 | §6 明确四例只检验运行管线，不估计功效；288 turns 是探索预算；未来确认须单独统计审查、固定 N 和批准 | Closed |
| ROOT-QUALITY | 只保留可评估成功答案会造成质量选择偏差，或把格式失败当科学错误 | §4/§5 定义全交付效用 U 与独立语义 Q：未有效交付 U=0、不可评估 Q=null；不可混写；任一操作失败使整体筛查不能通过 | Closed |
| ROOT-COUNT | 开发四例不能覆盖六族，额外变异版可能暗中翻倍调用预算 | §3 明确 6 族 × 2 pair × 2 变体 = 24 packet，已包含变异；§6 开发选四族各一例，预算分别 24/288 turns | Closed |
| ROOT-CLOCK | 两臂若共用物理 t0，后执行臂会错误计入另一臂的运行时间 | §5 每臂分别记录 packet 释放时间；排除其他臂排程等待、保留本臂 provider 排队；§6 完整配对预算预留 | Closed |
| ROOT-BASELINE | 胜过固定三轮自审不等于胜过更轻量的部署方案 | §7/§9 禁止据此宣称优于 single_once + 确定性工具/自适应审查；正式采用前另做同交付物强基线比较 | Closed |
| ROOT-ACCOUNTING | SDK 并发槽/请求预算可能被误称 provider 硬请求上限或实际账单 | §2/§6/§8 只声称 SDK dispatch 预算；内部请求、用量、计费未知为 null；中断保留预算占用但不编造收费 | Closed |

## 两路终审

科学/评测审查者对上述签认 hash 返回 `PASS_PLAN_ONLY`：有限集区间、重复聚合、惩罚终点和 U/Q 已明确；方案包效应不冒充角色身份效果、科学效用或最强单代理优势。剩余 P0/P1：0。

工程/安全审查者验证同一 hash 并返回 plan-only pass：五个 ENG P1 均关闭；新运行器非就绪、并发配置隔离、持久化恢复、外层启动超时、完整配对预留及禁止 science/SQLite/holdout 初始化均有验收要求。剩余 P0/P1：0。

## 不属于本次通过的事项

本次只新增文档，不更改实验引擎、运行器、评分代码或冻结科学数据；没有启动新的付费 benchmark、科学计算或 holdout，也没有生成新的性能结果。

以下仍未完成，**不能因设计通过而自动勾选**：24 个探索 packet/4 个开发 packet、逐字段 schema、盲评 rubric、持久单代理与独立并行运行器、故障注入测试、审批预算，以及未来统计确认的抽样/功效方案。历史 465-test 回归不是这些新功能的验收。

建议下一步：先零模型调用地实现 schema、评分样例、模拟执行器与故障反馈，通过实现审查后再申请 24-turn 开发预算。288-turn 探索预算不自动获批；方案也不承诺最终出现优势。
