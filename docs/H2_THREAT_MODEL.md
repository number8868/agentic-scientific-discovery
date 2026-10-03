# H2 跨进程 fixture 威胁模型

## 信任边界

managed sandbox 只负责进程隔离和文件权限，不能单独证明 executor 的身份或科学语义。bridge 的可信边界是宿主注入的 `NOVA_RUN_DB`、`NOVA_RUN_ID` 与 SQLite 中的不可变注册记录；调用方只能传 `experiment_id`。因此环境变量必须由受控 launcher 设置，不能接受 agent 选择 module、callable 或数据库。

bridge 仅接受 fixture 事件、当前 run 的 `pi` selection 和该 selection 的 registered spec。live/replay 记录、另一 run 的 selection、缺失上下文都应 fail closed。失败不能回显凭证（例如 `DATABRICKS_TOKEN`），也不能将 fixture Result 标记为 live。

## 主要威胁与验收

- **工具逃逸**：通过反射确认公开 callable 只有 `experiment_id`；设置 `NOVA_EXECUTOR`/`NOVA_EXECUTOR_MODULE` 也不得改变执行路径。
- **跨 run 泄漏**：run A 注册的 experiment 不能由 run B 执行；selection 必须属于当前 `NOVA_RUN_ID`。
- **模式混淆**：任何 live/replay event 都拒绝；Result 保留 fixture 标志，重复调用返回相同持久结果。
- **上下文缺失**：缺少 `NOVA_RUN_DB` 或 `NOVA_RUN_ID` 必须立即失败；异常文本不得包含环境秘密。
- **SQLite 路径攻击**：bridge 当前要求数据库是常规文件。生产 launcher 仍需拒绝不可信 symlink，并在打开前后做 realpath/inode 检查，避免 symlink/TOCTOU；SQLite 文件写权限应仅授予受控宿主，agent 不应拥有替换数据库的权限。
- **事件篡改/重放**：生产版需让 storage 以原子事务写入 selection、running、result，并以 run/experiment 唯一约束防重复；当前 H2 验收只覆盖重复执行返回既有结果。
- **fixture 冒充科学结果**：fixture 数字只能用于联通和编排演示，不能进入 live baseline、scientific claim 或 H2 版本验证结论。

## 尚未完成的 A 端责任

A 端仍需提供真实受控 executor、真实数据快照审计、Result 数值校验及 holdout 语义。H2 fixture 成功不等于真实科学 workflow 成功；Omnigent YAML/provider/version 仍必须在目标 managed sandbox 中实际联通并保存证据。
