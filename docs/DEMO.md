# NOVA-MAT 两分钟演示（fixture）

本演示标识为 **fixture**：固定 seed 和内存记录只验证编排、契约和“结果驱动下一轮”的路径；数字不是材料科学结果、基线或 JARVIS 结论。

1. **0:00–0:25（问题）**：说明目标是检查筛选规则敏感性，而不是宣称发现材料。指出当前是 fixture，未来 live 必须读取冻结数据快照。
2. **0:25–0:55（第一轮）**：运行 `python scripts/run_fixture_demo.py`，展示 `family_screen` 的两家族摘要和 delta。
3. **0:55–1:25（决策）**：解释第一轮结果触发 `threshold_sensitivity`；第二轮依次改变预注册 ehull 阈值，输出明确显示每个点。
4. **1:25–1:50（审计边界）**：强调 seed、mode、模板和结果可重复；fixture 不可冒充 live，未知值不被当成科学失败。
5. **1:50–2:00（接入）**：说明 runtime/contracts 就绪后，保留 `execute(spec)->Result` 适配层，替换数据和宿主审计，不改演示决策逻辑。

状态标签：`fixture` = 内存确定性演练；`live` = 真实冻结快照与受控工具（本仓库尚未提供）；`replay` = 对已存证据的只读回放。标签必须随结果保留。
