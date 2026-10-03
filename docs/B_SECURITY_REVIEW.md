# B 端安全审查（fixture MVP）

- 凭证不入日志、prompt、fixture 结果或仓库；模型宿主自行管理凭证。
- fixture 引擎无 shell、网络、任意路径读写或任意代码工具；仅消费受限 spec 字段和固定内存数据。
- actor 不能由 LLM 自报。live 接入时必须由可信宿主 wrapper 绑定 actor、run_id 和预算，并校验 schema。
- fixture 结果必须带 `mode=fixture`；不得拼接成 live manifest、科学 baseline 或结论。replay 也必须保持来源标签。
- 科学状态与执行状态分离；工具错误、超时和 schema 错误不能被映射成“假设反向”。
- Omnigent YAML 字段和版本在 H2 必须真实联通实测；未实测的版本号不得写成已验证事实。本 fixture 不能替代 H2 验证。
- runtime 接入前，必须再次检查模板白名单、阈值范围、数据快照 hash、实验预算和不可变结果写入；不能把 fixture 开关作为 live 绕过。
