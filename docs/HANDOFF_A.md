# A 端交接：证据导出与最小联调

A 端只需提供一个受控 executor：`execute(spec) -> Result`。executor 接收已冻结的 ExperimentSpec，不接收 shell、路径、凭证或任意运行上下文；宿主负责绑定 `run_id`、actor、预算和 mode。

真实 `Result` 至少应包含：`result_id`、`experiment_id`、`spec_sha256`、`dataset_sha256`、`execution_status`、`scientific_status`、`started_at`、`finished_at`、`elapsed_seconds`、`groups_summary`、`delta`、`resampling_interval`、`missingness_interval`、`quality_flags`、`artifact_ids`、`error`。fixture/live/replay 必须在关联事件中保留 mode。

失败语义：超时、权限、下载、schema 或工具异常属于执行失败；`scientific_status` 必须为 null，不能写成 reversed/inconclusive，也不能制造数字占位结果。成功但证据不足才使用 data_limited/inconclusive 等科学状态。

最小联调 fixture：注册一个 `mode=fixture` 的 spec（例如 experiment_id `E1`），写入同一 run 的事件并以 payload_ref 引用 `E1`，保存一个 result 和可选 review，然后运行：

```text
python scripts/export_run.py run.sqlite RUN-F ./evidence
```

导出器只从该 run 的事件引用追踪实体，避免跨 run 泄漏；若事件没有引用，实体不会被猜测导出。`./evidence` 必须是新建或空目录。A 端不需要实现导出器，也不应把 fixture 数字描述为科学结果。
