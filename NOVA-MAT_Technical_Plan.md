# NOVA MAT 双人开发技术方案

版本 1.2 · 2026 年 10 月 3 日 · 24 小时竞赛执行文档

本文供两名开发者直接分工实施。目标是在已有材料数据上构建一个真实由 Omnigent 编排的科学工作流：提出可检验假设，比较可选实验，执行计算，审查结果，再改变下一项实验。交付包括可复现仓库、agent 配置和 policies、实验记录、实测效率及两分钟展示。[1]

本方案限定为候选筛选规则的稳健性研究。24 小时内不承诺发现新材料、证明器件性能或获得特定名次。预计前 20 小时完成实现与验证，最后 4 小时留给故障恢复及提交。实际可行性由 H2 的联通检查决定。

## 1 项目定位与评分策略

科学问题：在一个固定的 JARVIS 数据快照中，按相同计算方法和预先定义的约束筛选时，氧化物与硫化物或硒化物家族的候选组成通过率有何差异？该排序是否对能量阈值、带隙方法和缺失数据敏感？

成果是一个能够根据证据选择下一项验证的研究系统，以及一个有适用范围的筛选决策。创新重点是可审计的实验选择与反证过程，不是 agent 数量或数据库查询本身。材料候选只能称为计算筛选候选。

| 评分维度 | 权重 | 要呈现的证据 |
|---|---:|---|
| Omnigent 编排 | 30% | 实际子 agent 调用、工具结果、结构化交接与结果后改计划 |
| 突破潜力 | 25% | 具体科学问题、对不可靠筛选规则的诊断、可接续的材料验证路径 |
| 加速与学习 | 20% | 相同任务的效率测量、失败情况、下一实验为何改变 |
| 科学严谨 | 15% | 冻结判据、数据来源、留出验证、方法差异和不确定性 |
| 创意与责任 | 10% | 独立质疑、权限约束、明确尚未完成的实际验证 |

该评分映射来自 challenge，不是得分预测。[1] 展示应回答三个问题：最初相信什么，实验改变了什么，现在为什么选择这个测试。

## 2 交付范围

必须完成：四个 agent 角色、至少两个可选测试、一次真实选择、两个有依赖关系的实验、一次冻结后的留出验证、完整证据记录、三次端到端工程演练、一次基线测量及提交材料。三次演练用于可靠性检查，不代表三个独立科学样本。

四个角色为 Scientist PI、Planner、Runner、Skeptic。Scientist 与 PI 合并以降低集成和调用开销。Runner 是 agent 调用受控实验工具，数值计算由确定性 Python 完成。

只有核心闭环稳定后才考虑增加一个探索性混合阴离子分析。DFT 重算、CHGNet、生成新材料、模型训练、任意代码执行、复杂知识图谱与定制 React 前端均不进入 24 小时范围。

最低可提交版本允许使用 Omnigent 自带界面和实验图表，取消自建展示 UI。任何降级都必须保留真实 Omnigent 编排与真实实验；录制回放不能替代 live workflow。

## 3 两人分工和协作规则

成员 A 负责数据与实验，成员 B 负责编排与展示。按技能分配角色即可，不默认任何一人必须承担某项工作。两人各约 18 至 20 小时有效工作，预留休息与 4 小时公共缓冲；并行时间不能简单当作 48 小时连续生产力。

| 工作模块 | 主负责人 | 交付物 | 对方接入时间 |
|---|---|---|---|
| 共用契约 | A 与 B 共定，B 维护 | Pydantic schema、枚举、最小 fixture | H0 至 H1 |
| 数据下载和审计 | A | 快照、manifest、覆盖率、划分清单 | H2 |
| 实验引擎与结果 | A | 受控模板、数值结果、图表、测试 | H6 |
| Omnigent 联通 | B | 真实子 agent 到函数工具的 run record | H2 |
| Registry 和事件存储 | B | SQLite 存储入口、原子结果写入、恢复 | H4 |
| Agent 配置和闭环 | B | YAML、prompt、policy、交接记录 | H8 至 H10 |
| 展示 UI | B | Streamlit 只读时间线和证据视图 | H14 |
| 科学解释与基线 | A 主，B 配合 | 验证结果、配对计时、结论边界 | H16 |
| 集成验收 | 两人 | 三次工程演练、故障检查 | H18 |
| 提交和展示 | B 打包，A 核查科学内容 | README、配置、结果、视频及讲稿 | H20 |

B 首先创建 contracts.py，A 审核后冻结 v1。A 不修改 B 的 agents、storage、ui；B 不修改 A 的 data、experiments、statistics。共用契约发生变更时，先提交示例 JSON，再让对方更新调用方，禁止静默改字段。

建议分支 science-engine 与 orchestration-ui。小批量提交到 main，每两小时合并一次。共用 schema、依赖文件与 README 同一时段只有一名写入者。交接不仅交代码，还交一个可调用函数、输入示例、输出示例和已知失败条件。

第一小时共定四项：目标范围、ExperimentSpec、Result、Event。H2 联通时可以用明确标记的 synthetic fixture，但 H6 之后闭环演示必须读真实数据。fixture 数值不得混入科学结果或基线测量。

## 4 数据契约与科学约束

### 4.1 数据快照

采用 JARVIS 工具获取 dft_3d，下载一次后冻结。官方列有结构、带隙、ehull 等字段，但文档列字段不等于每条记录都有有效值。[2] 实际记录数以下载文件为准，不把旧文档中的数量写进 pitch。

manifest 必须包含 dataset 名称、下载来源、下载 UTC 时间、原文件 SHA256、原始记录数、jarvis-tools 版本、Omnigent 版本或 commit、Python 版本、依赖锁、清洗脚本 SHA256、排除规则、代表结构规则与 split seed。下载失败先重试一次，再由队友转移同源数据快照；保留来源和校验值。不以合成数据替代科学数据。

归一化字段为 jid、reduced_formula、elements、family、opt_gap_ev、mbj_gap_ev、ehull_ev_atom、excluded、split。保留原始数值和缺失标记。None、na、空串、NaN、Inf 统一为缺失；字符串数字可转为有限数值；单位必须确认。带隙零值有效，不能当缺失。ehull 在负 0.000001 至零之间视为舍入误差并记录后置零；更负的值标记无效并审计，不取绝对值。

### 4.2 家族和排除规则

排除含 Pb、Cd、Hg、As、Tl 的组成，并排除元素数少于二的记录，均保留排除计数。这是本研究的元素设计约束，不是毒性鉴定。避免使用 low toxicity 或 environmentally safe 作为已验证结论。

以集合 O、S、Se、N、F、Cl、Br、I 定义本研究的阴离子标签。oxide 需含 O 且不含此集合中的其他元素；chalcogenide 需含 S 或 Se，且不含 O、N、F、Cl、Br、I。其余为 other，首轮不比较。该规则是计算分组约定，不能宣称完整化学分类；含氮或卤素的氧化物等被明确排除。

同一 reduced_formula 下有多个晶体记录时，仅选最低有效 ehull 的记录作为代表，平局按 jid 字典序选。该规则在查看带隙前冻结；代表记录缺带隙时保留为缺失，不换一个带隙更合适的结构。若所有 ehull 无效，按 jid 选一条保留为不可评价组成。其余结构保留在审计文件。

因此估计对象是数据库中每个组成最低计算 ehull 的已记录结构，不是所有晶体的平均，不是组成在任何结构下可通过的概率，也不是自然界材料总体。组成等权，避免多晶型数量让某些组成重复计票。最低 ehull 代表规则仍受每组成收录结构数量和完整性影响，不证明真实基态已经收录；其局限在结论中说明。

### 4.3 筛选端点

首轮统一使用 OPT 带隙。操作窗口为 1.1 至 1.8 eV，ehull 不高于 0.05 eV/atom。两个阈值均是本原型预设的筛选约定，不是高性能器件或可合成性的充要条件。负形成能不能替代 ehull；ehull 本身也只是计算热力学指标，不能证明耐湿、长期稳定或可制造。[4]

OPT 与 MBJ 带隙不能逐行补齐成一个变量。二者是不同计算方法，已有 JARVIS 研究专门比较它们。[3] MBJ 只能在相同 jid 的配对记录上独立做敏感性分析，不把 MBJ 当真实实验值。缺少 MBJ 不能算候选失败。

每家族同时报告总组成数、可评价数、缺失率、通过数、已观测通过率和缺失最坏情况范围。可评价要求代表记录有有限 OPT 带隙和有效 ehull。已观测通过率等于通过数除以可评价数。

缺失范围用全部组成作分母。下界等于通过数除以全部组成数；上界等于通过数加不可评价数组成，再除以全部组成数。两个家族差值的范围为 chalcogenide 下界减 oxide 上界，至 chalcogenide 上界减 oxide 下界。该范围无需填补数值，防止把 unknown 当 false。

### 4.4 数据划分和进入门槛

按 reduced_formula 在每家族内用固定 seed 1729 做 70% discovery 与 30% holdout 划分。同组成的全部结构只能在同一 split。快照、代表规则与划分在任何结果计算前保存 hash；清洗可做字段合法性和覆盖审计，不能先看家族通过率再选问题。

元数据审计可看各 split 样本量与字段覆盖率，不能看 holdout 带隙分布、通过率或排序。每家族 discovery 至少 40 个可评价组成，holdout 至少 20 个；主方法覆盖率至少 80%。这些是原型质量门槛，不是统计功效证明。holdout 不满足门槛时不给验证成立的结论。

覆盖不足时先进入 data_limited 分支，进行缺失分析并缩小研究主张。ehull 不可用时不能改用 formation energy 宣称稳定；允许单独注册带隙方法稳健性问题，保留旧问题失败记录。若无法保留任何有意义的真实实验，应明确无法完成原科学目标。

## 5 假设和实验设计

### 5.1 预先冻结的假设

主效应 delta 定义为 chalcogenide 已观测候选组成通过率减 oxide 已观测通过率。

H1 为在固定协议下 delta 大于零；竞争命题 H2 为 delta 不大于零。它们共享同一端点和人群。Scientist PI 依据已引用背景提出命题，但必须在结果前保存方向、方法、阈值、估计对象、判据与协议 SHA。不得在看到结果后再编写最初假设。

使用按家族、以组成为单位的 bootstrap，重复 2000 次，固定 seed；报告 delta 及 95% percentile 重采样区间。由于数据库不是总体的随机样本，该区间仅说明对当前记录重采样的稳定性，不是针对所有真实材料的总体置信保证。

| 科学状态 | 判据和允许的解释 |
|---|---|
| supported_in_snapshot | 区间下界大于零、覆盖门槛通过、非退化；快照内支持 H1 |
| reversed_in_snapshot | 区间上界小于零、覆盖门槛通过、非退化；快照内方向相反 |
| inconclusive | 区间含零，或某家族端点完全相同导致 bootstrap 退化 |
| data_limited | 样本量或覆盖率门槛不满足；不能做方向结论 |

若区间含零，不写 H1 被推翻或 H2 已证明。若缺失范围跨零，即使已观测区间不跨零，也只保留 complete-case 的条件结论，并触发缺失审查。边界区间、零通过数和单一样本必须有测试用例。

### 5.2 受控实验目录

| 模板 | 输入与产出 | 学习目的 | 使用范围 |
|---|---|---|---|
| family_screen | 固定阈值、两家族通过率与重采样区间 | 判定主效应方向 | 初始选择 |
| threshold_sensitivity | ehull 为 0.025、0.05、0.10；带隙窗口固定 | 检查排序是否由阈值制造 | 初始或后续选择 |
| method_sensitivity | 同 jid 的 OPT 与 MBJ 配对；同样阈值 | 区分方法变化与子样本选择 | 后续选择 |
| gap_window_sensitivity | 窗口为 0.9 至 1.6、1.1 至 1.8、1.3 至 2.0 eV；ehull 固定 | 检查方向是否取决于带隙窗口边界 | 后续选择 |
| coverage_stratified | 二元与三元及以上组成分层；每层计数、覆盖率、通过率 | 区分组成复杂度相关的覆盖与筛选差异 | 后续选择 |
| holdout_validation | 冻结主协议及唯一选定后续模板 | 检查 discovery 结论能否在留出集重现 | 最后执行一次 |

family_screen 与 threshold_sensitivity 都需向 Planner 提供。它依据当前科学问题、覆盖率、预算和预期可区分的解释选择一项。不得默认宣称哪项 information gain 最高；没有概率模型时，learning_score 仅是显式启发式评价。[1]

初始若先运行 threshold_sensitivity，三个点均产出，其中 0.05 的点按主协议解释，其他点只作敏感性分析。不从三个点选最显著者当主结果。

method_sensitivity 必须同时产出 OPT 全部可评价子样本、配对子样本中的 OPT、以及相同配对子样本中的 MBJ。前两者的差异反映样本选择，后两者才是方法差异。若任一家族配对 discovery 不足 20 个或 holdout 不足 10 个组成，则返回 data_limited，不硬做方法排序。该阈值仍是工程门槛。

缺失最坏情况范围是每次实验的质量审计，已在 Result 中计算，不能再运行相同公式充当第二科学实验。coverage_stratified 新增预注册的组成复杂度分层：二元为元素数等于二，复杂为元素数大于等于三。每层的分母与未知端点处理仍按 4.3。每层 discovery 两家族均至少 20 个可评价组成、覆盖率均至少 80% 且端点非退化时，才给该层方向判断；holdout 每家族最低 10 个，其余门槛相同。低于门槛可展示计数和描述性通过率，但无方向背书。

如两层均达门槛，可以用固定各 0.5 权重报告 complete-case 标准化 delta，重采样在家族及层内进行，并沿用退化检查。0.5 与 0.5 是人为设定的比较目标分布，不表示原数据库总体率；任何一层不足时不重新归一权重以制造总体结论。该分析能揭示分组相关性，不能消除非随机缺失或证明组成复杂度导致家族差异。带隙窗口敏感性只是既定边界扰动，不从网格挑最显著结果。

### 5.3 真正结果驱动的第二实验

Skeptic 读数值和审计记录，指出一个可以通过实验区分的薄弱假设；PI 结合剩余预算和 Planner 提案选择后续模板。

| 实际发现 | 建议后续测试 | 下一步要区分的解释 |
|---|---|---|
| 已观测方向明确，但缺失范围跨零 | coverage_stratified | 差异是否集中在低覆盖的复杂组成层 |
| 排序随能量阈值变号 | method_sensitivity；不可行则 gap_window_sensitivity | 方法变化或窗口边界是否进一步改变决策 |
| 主效应支持或反向，且缺失范围稳定 | method_sensitivity；不可行则尚未执行的 threshold_sensitivity 或 gap_window_sensitivity | 家族差异是否依赖计算方法或预定阈值 |
| 主效应 inconclusive | 尚未执行的 threshold_sensitivity，否则 gap_window_sensitivity | 不确定性是否来自不同的筛选边界 |
| 主字段覆盖不足 | coverage_stratified | 哪些预定组成层缺乏足够证据 |

此表是允许的决策空间，不是预排一段必定失败的故事。Skeptic 的 concern、所依据 result_id 和 next_template 必须写入证据记录。Planner 先排除已执行模板，再检查覆盖、成本和预算；初始 family_screen 与 threshold_sensitivity 之后均有不同参数轴的备选。相同模板与参数的重复执行只算工程演练，不计新的实验。若无可行的新测试，则有理由停止并承认两轮科学目标未完成，不能硬凑第二轮。

### 5.4 留出验证和停止

discovery 上完成主结果和一个后续实验后，冻结唯一最终协议与结论，再由受控工具读取 holdout 执行主协议及选定后续测试。agent 在冻结前没有读取 holdout 结果的工具。最终同时展示两组结果。

最终验证状态枚举为 replicated_in_snapshot、direction_consistent_inconclusive、inconclusive、contradicted、data_limited、not_tested。仅当 discovery 与 holdout 的 scientific_status 均为 supported_in_snapshot 或均为 reversed_in_snapshot，且各自全部质量门槛通过时，主效应才写 replicated_in_snapshot。两边质量合格但 supported 与 reversed 互换才写 contradicted。一侧或两侧 inconclusive 时，相同非零点估计方向可写 direction_consistent_inconclusive，其余写 inconclusive；质量门槛不足写 data_limited；没有执行写 not_tested。严格复用 5.1 的端点退化保护，不绕过状态判据。

所有验证标签均有 scope，默认为 observed representatives only。缺失最坏情况差值范围跨零时，即使 complete-case 结果复现，也不能写全部组成排序已复现。若 discovery 原本 inconclusive，不得把一次 holdout 同号写成原假设已复现。

最终协议同时冻结后续模板、全部网格或亚组定义、对应估计量与允许解释。亚组只在自身达到门槛时解释；某个敏感性点不得替代主端点。每项发现分别报告其留出验证状态，主效应的 replicated 标签不能替后续发现背书。不得到 holdout 重选亚组、窗口或最佳网格点。后续任何分析注明探索性，不称独立验证。

最多两个 discovery 实验加一次 holdout 调用。每项工具默认 120 秒超时，所有实验硬上限 360 秒；整条含模型调用的 run 默认 12 分钟。先实测后更新下一项成本预测，旧计划保留。达到预算、无法区分或数据不足时输出有理由的停止决策。

## 6 技术架构与 Omnigent 接入

默认技术栈为 Python 3.12、Pydantic 2、pandas、NumPy、jarvis-tools、SQLite、Streamlit、pytest、Omnigent 开源版。科学计算只依赖 CPU，不把 GPU 当运行前提。依赖版本以 H2 真正安装成功的版本锁定，不在文档里虚构已验证版本号。

Omnigent 的官方配置支持 YAML agent、Python 函数工具、子 agent 和 policies。[5][6] 使用其真实 CLI 和 YAML 启动工作流，不假设不存在的 Python SDK 或事件 API。B 必须在 H2 保存一次 supervisor 调用子 agent、子 agent 调函数、结果回到 supervisor 的记录。

建议通过能使用受控函数工具的 SDK harness 接入，例如已配置模型凭证的 openai-agents；实际 provider、model 和所需 extras 由安装时验证。若该 harness 不通，可改用实际验证能调用相同工具的另一 harness。任何变更都写入 manifest。不给 agent 通用 shell 或任意文件写权限。

系统分为四层：Omnigent 做角色协调；Python 工具做真实实验和参数验证；存储模块保存不可变协议和结果；UI 只读展示事实。UI 的按钮可通过可信宿主进程启动 CLI，不能另起一套假 agent 流程。

状态顺序为 objective_registered、hypothesis_frozen、options_registered、experiment_selected、experiment_running、result_ready、review_ready、next_spec_frozen、second_experiment_running、second_result_ready、second_review_ready、final_protocol_frozen、holdout_running、holdout_ready、completed。下一轮提案注册只写事件，不把状态退回初始 options_registered。失败状态为 tool_failed、schema_failed、budget_exhausted、cancelled。状态转换由工具检查前置记录；LLM 文本不能直接把状态改成 completed。

科学状态与执行状态分别存储。timeout、403、下载错误、JSON 校验失败属于执行失败，绝不映射为假设反向或不支持。条件允许并行做来源整理与元数据审计；有因果依赖的实验和决定必须顺序执行。

### 6.1 Agent 权限和交接

| 角色 | 输入 | 决定或输出 | 可用工具 |
|---|---|---|---|
| Scientist PI | objective、引用证据、审计、已有 review | 冻结假设、批准初始及后续协议和停止 | register_hypothesis、commit_initial_spec、commit_next_spec、freeze_final、只读记录及三个子 agent |
| Planner | 冻结假设、模板目录、元数据、剩余预算 | 至少两项提案、排序及选择理由 | read_metadata、register_plan |
| Runner | 已注册 experiment_id | Python 的真实 Result 与 artifact ID | execute_registered_experiment |
| Skeptic | Result、Spec、源证据和质量标记 | concern、证据引用、建议下一模板 | 只读记录、submit_review |

submit_review 仅允许写审查记录，不能改数值、删除实验或执行工具。Scientist PI 也不能直接调用任意实验代码；只能把已冻结 experiment_id 交给 Runner。工具身份由 YAML 绑定的宿主 wrapper 确定，actor 字段不能由 LLM 自报。

宿主负责提供返回 JSON 的注册工具。子 agent 的自由文本仅用于解释；可执行 handoff 来自通过 schema 校验的 registry 记录。一次无效 JSON 允许一次修复请求，仍失败则终止该步骤；修复不得变更已冻结科学判据。

### 6.2 配置实现规则

agents/lab.yaml 中根 agent 声明三个 type 为 agent 的子工具。子 agent 的实验工具采用 type 为 function、callable 指向安装后的 nova.tools.execute_registered_experiment、parameters 只允许 experiment_id。这些是官方文档已核对的配置字段，完整执行配置须在 H2 根据实际 harness 验证。[5]

policies 必须配置工具调用上限，并在工具内部二次校验实验目录、预算、状态和数据范围。[6] 所有 agent 使用独立的允许工具列表；禁止继承 root 的写权限。凭证只由模型运行宿主使用，不进入日志、prompt 或仓库。

科学目标、数据约束及预算由人先批准；批准后，允许范围内的离线分析无需每步确认。付费计算、实际合成、外部提交等不暴露工具。若未来接入 consequential action，须通过真实 policy 或受控工具要求批准，不能只在 prompt 写 ask approval。

## 7 共用接口和记录格式

所有接口 schema_version 固定为 1，Pydantic 使用 extra 为 forbid；枚举、数值单位、列表上限与缺失允许项写成类型约束。文档例子仅为接口例子，不含真实实验结果。

### 7.1 ExperimentSpec

```json
{
  "schema_version": 1,
  "experiment_id": "EXP-001",
  "hypothesis_id": "H-001",
  "dataset_sha256": "<真实快照SHA256>",
  "split": "discovery",
  "template": "family_screen",
  "groups": ["oxide", "chalcogenide"],
  "bandgap_method": "opt",
  "gap_window_ev": [1.1, 1.8],
  "ehull_max_ev_atom": 0.05,
  "bootstrap_repeats": 2000,
  "seed": 1729,
  "timeout_seconds": 120,
  "parent_result_id": null,
  "review_id": null
}
```

预算、registered_at、spec_sha256、actor 和 attempt 由宿主加入，不接受模型声明。各模板的参数使用 discriminated union，不能把不相关参数塞进任意字典。holdout 模板须带 frozen_protocol_id，复制已冻结参数，禁止提交新窗口。所有 ID 在同一个 run 内解析，跨 run 引用必须拒绝。

可信 runtime 每次创建唯一 run_id 并启动独立进程，把 run 上下文绑定给该进程的 wrapper。execute_registered_experiment 只接收 experiment_id，使用宿主注入的 run_id、数据库位置、权限身份与预算，不从模型参数接收它们。第一轮联通检查必须验证此上下文在根和子 agent 的真实工具调用中保持一致。宿主可采用 NOVA_RUN_ID 等不含凭证的进程环境或已验证的注入机制，实际机制在 H2 锁定；不能凭文档假设跨 harness 自动传递。

### 7.2 Result

Result 包含 result_id、experiment_id、spec_sha256、dataset_sha256、execution_status、scientific_status、started_at、finished_at、elapsed_seconds、groups_summary、delta、resampling_interval、missingness_interval、quality_flags、artifact_ids、error。

groups_summary 对每家族存 n_total、n_observed、n_pass、coverage、observed_rate、missing_lower、missing_upper。所有比例限制在零到一；delta 在负一到一；各 count 必须有逻辑约束。零分母时比例为 null，不能写零。失败时科学状态为 null，error 给类型和简短说明，不能生成数字占位结果。

method_sensitivity 输出三个具名视图和 paired_jids_hash；两种敏感性模板输出所有预定网格点；coverage_stratified 输出固定两层及可评价时的标准化估计。结果图表由同一 Result 对象生成，UI 不重算另一套数值。工具返回摘要和 artifact ID，大表写 CSV，防止把数万条数据塞进模型上下文。

### 7.3 Planner 和 Skeptic

PlanPacket 含 hypothesis_id、candidate_tests、chosen_proposal_id、selection_reason。每项 candidate 存 proposal_id、完整 draft_spec、feasibility、estimated_seconds、learning_score、score_reason；剩余预算由宿主补入。estimated_seconds 来自工具试跑或注明未校准估计；learning_score 是 1 至 5 的启发式等级，不是假概率或信息熵。选择必须可行且在剩余预算内。

register_plan 一次注册至少两个完整提案和选择建议，返回 plan_id 与 proposal_ids。在初始 hypothesis_frozen 时转换为 options_registered；在 review_ready 时仅登记 next_options_registered 事件，run 状态仍为 review_ready。计划轮次由宿主依据前置状态绑定。PI 调用 commit_initial_spec(plan_id, chosen_proposal_id)，宿主复核冻结假设和范围后，在同一事务注册不可变初始 Spec、状态 experiment_selected 和事件，并返回 chosen_experiment_id。Runner 只使用该 ID。

后续由 commit_next_spec(plan_id, chosen_proposal_id, result_id, review_id) 注册第二 Spec，要求 run 当前为 review_ready、计划属第二轮、首轮结果成功、review 已存在且目的不同；同事务转换 next_spec_frozen。初始和后续 Spec 的唯一批准 owner 都是 Scientist PI。draft_spec 不含已注册的 experiment_id 与宿主字段；这些在 commit 时生成。模型选择现存 proposal_id，不能自行创造已注册 ID。

freeze_final 要求第二实验成功、第二 review 已提交、主协议和后续解释不再变更。在同一事务保存 final_protocol、其 hash、派生不可变 holdout Spec 和 final_protocol_frozen 事件，并返回 frozen_protocol_id 与 holdout_experiment_id。派生 Spec 指向已冻结主协议及后续参数，不接受新的阈值。PI 将这个 ID 交 Runner，holdout 执行入口核对冻结状态再允许读取数据。ValidationResult 包含 main_result、followup_result 和逐项 validation_status；任何单项失败都保留，不能写整体已复现。

ReviewPacket 含 experiment_id、result_id、concerns、recommended_template、reason、claim_refs。每项 concern 包括 concern_type、severity、evidence_refs。仅允许已注册的 result、字段、文献或图表 ID；所有引用由宿主检查存在。Skeptic 不允许编造材料数据、修改原判据或用文献观点覆盖实际数值。

### 7.4 Event 和 Evidence Ledger

Event 存 run_id、seq、event_id、event_type、actor、timestamp_utc、attempt、mode、payload_ref。mode 只能为 live、fixture、replay。actor 和时间由宿主生成。UI 依据这些事件展示操作，不根据 LLM 自称我已执行补动画。

Evidence Ledger 的 Claim 存 claim_id、claim_type、text、source_refs、hypothesis_id、experiment_id、scope、uncertainty。claim_type 区分 literature、hypothesis、computed、decision。computed 必须指向成功 Result 的字段或图表；hypothesis 只能写待检验；文学性总结不能变成事实证据。

建议 SQLite WAL，busy_timeout 为 5 秒，短事务插入 registry 与 event，单一存储模块负责写入。一个实验的状态更新和相应事件在同一事务；多进程不得直接 append 同一 JSONL。可在结束后导出 events.jsonl 与 ledger.json，作为提交快照。

结果文件先写临时文件、校验后原子 rename，再登记 result；命名由宿主生成，禁止工具参数提供任意路径。run_id、experiment_id、spec_sha256 为执行幂等键，已完成的相同请求返回旧结果。running 使用独占 lease 和唯一 attempt token；worker 先写 attempt 的临时目录，只有宿主可正式提交，提交需 compare and swap 校验 token。崩溃后先确认旧 worker 已终止才回收 lease，保留旧 attempt 错误；旧 token 迟到结果拒绝提交。不能确认旧进程退出时，run 保持 failed 待恢复，不重复运行。不同 spec 不能覆盖同一个 experiment_id。

## 8 文件组织和实现顺序

建议仓库目录如下。目录是待实现设计，不代表已经存在的代码。

```text
agents/             lab.yaml 与角色 prompt
nova/contracts.py   共用 Pydantic 类型
nova/data/          下载 清洗 代表结构 划分 审计
nova/experiments/   五种实验及一次验证入口
nova/statistics.py  通过率 重采样 缺失范围
nova/tools.py       agent 可调用的受控 wrapper
nova/storage.py     registry event ledger
nova/runtime.py     CLI 启动 预算 取消 恢复
ui/app.py           Streamlit 只读展示
tests/              科学边界 权限 故障 集成检查
data/manifest.json  来源 hash 覆盖率 划分规则
runs/               每次运行的结果和日志
docs/               方法 局限 审查 展示讲稿
README.md           一次运行与复现步骤
```

### 8.1 A 的实现流程

1. 下载并冻结快照，确认许可、单位和字段含义；记录错误，不把无效记录静默丢弃。
2. 生成 reduced_formula 和互斥 family，按预定规则选代表；保留 full audit CSV。
3. 冻结组成分组的 split，产出仅含样本量和缺失率的审计。提供给 B 一个 read_metadata 函数。
4. 实现 run_experiment(spec) 返回 Result 和文件引用。只允许固定模板，执行和数值结果不依赖 LLM 生成代码。
5. 实现 family_screen、threshold_sensitivity、gap_window_sensitivity；三个共享筛选和网格逻辑。再实现 method_sensitivity、coverage_stratified，以及冻结协议的 holdout 调用。缺失范围作为通用审计，不单列科学实验。
6. 交给 B 一个真实 discovery run fixture，明确标成 live recorded；它用于界面开发，但不能当新的现场运行。
7. 做统计边界检查、结果解释和基线配对计时，核查 README 中每个事实数字。

### 8.2 B 的实现流程

1. 验证 provider 登录和 Omnigent 安装，运行根 agent 到子 agent 到受控函数的联通实验。保存 CLI 命令、版本、退出码和工具记录；不要只看自然语言回答。
2. 与 A 冻结 contracts；建立 registry 和 schema fixture，让编排在 A 实验完成前可以开发。
3. 实现四个角色与权限，所有机器交接先校验再注册。首轮两个实验提案均必须可见。
4. 接 A 的 execute_registered_experiment，不接自由 Python。保存每次实际 tool call 与成功结果的关联。
5. 接入 review、后续 Spec 和冻结后的 holdout；预算和无效状态由工具强制拦截。
6. UI 只读 SQLite，最多一条 live run；可信启动器用文件锁或数据库互斥拒绝重复点击。展示 question、选择理由、结果图、concern、改变的参数或模板、证据来源和预算。
7. 加取消、错误提示和只读 replay。live 显示当前运行，replay 显示记录时间与 run_id，两者显著标识。
8. 完成 README、配置打包与两分钟展示；让 A 复核科学内容。

## 9 24 小时并行里程碑

时间均从比赛允许开工的 H0 算起，不假定当前已有完整 24 小时。如果已开始，按实际剩余时间缩减 UI 和探索功能。数据预取与外部代码使用须遵守比赛规则。

| 时间 | A | B | 共同验收或降级 |
|---|---|---|---|
| H0 至 H1 | 定义端点与数据契约 | 建 contracts 和 Omnigent 环境 | schema v1 与两份 JSON 示例 |
| H1 至 H2 | 数据下载和覆盖审计 | 真实子 agent 调函数 | 数据可用且模型与工具联通 |
| H2 至 H4 | 清洗 代表选择 split | 存储权限 角色配置 | manifest 冻结；UI 可读 fixture |
| H4 至 H6 | family 与阈值工具 | Planner 与 Runner 接入 | 一个真实实验到结构化结果 |
| H6 至 H8 | 方法与缺失工具 | Skeptic 与 PI 决策 | 可因实际结果注册下一测试 |
| H8 至 H10 | holdout 工具与边界测试 | 两轮闭环及预算 | 首次真实完整闭环 |
| H10 至 H12 | 修统计与覆盖问题 | 修交接与错误恢复 | 闭环未稳则砍自建 UI |
| H12 至 H16 | 留出验证 基线测量 | UI 和证据追踪 | 科学结果冻结及配对计时 |
| H16 至 H18 | 复现与科学审核 | 三次工程演练 | 三次执行成功 无伪造节点 |
| H18 至 H20 | 审稿和局限 | 视频 README 打包 | 可提交压缩包与本地备份 |
| H20 至 H24 | 两人共同修阻塞 | 两人共同展示与提交 | 不再增加功能 |

H2 若 Omnigent 不通，由 B 优先换可验证的 harness 或比赛提供的 managed 路线，A 继续实验工具。H4 仍不通须承认该必要要求有风险，不用自行 Python 编排冒充 Omnigent。H10 若两轮闭环未通，取消自建 UI、方法敏感性之外的扩展及所有额外角色。H16 冻结功能，不再改变数据规则或端点。

关键路径为平台联通、真实实验工具、结果到下一实验、验证和展示。来源整理、图表、UI 可并行；冻结 schema、选择实验、读取结果、再规划不能并行跳步。

## 10 效率测量与对照

主测量针对证据到可执行下一实验这一瓶颈，不把数据库筛选速度叫科学发现速度。人工基线和系统都从同一个已完成的真实 discovery 结果包开始，输出同一种有效 ExperimentSpec，使用相同模板、证据、预算和判据。

开始时间为完整结果包可读；结束时间为下一 Spec 通过 schema、引用、模板、范围和预算校验并完成注册。计时包含阅读、审查和修复，不包含初次下载。另报实际第二实验执行时间及人工主动操作时间，不混在一个倍数里。

准备六个固定任务上下文，采用同一快照的 discovery 结果，改变明确注册的预算或可用测试条件，不使用 holdout 结果出题。若另建 benchmark run，先将结果包按 hash 校验导入为只读 benchmark evidence，分配本 run 的本地引用，同时保存原 live run 来源链接；不直接用跨 run result_id 注册 Spec。两名队员各做三个不重复上下文的人工选择；相同上下文分别由系统执行，形成六对。上下文顺序随机，两名参与者均为熟悉项目的开发者，存在学习偏差，结果只能作为探索性流程测量。

比较对象必须满足同一验收标准：选择合法、证据可追溯、理由对应可检验 concern、预算满足。任一方失败则该对标记 failure，不把失败记为零秒。报告全部原始时间、成功率、修复次数、参与者与顺序；成功配对的时间比中位数注明 valid pairs 的数量。若有效配对少于三对，只报原始结果，不突出速度倍数。

不要把单次最快系统结果除以最慢人工结果，也不要把缓存命中与人工重新下载相比。若系统没有更快，照实报告；可以展示更少手工步骤或更高协议合规率，但不能改写为未测量的 10 倍。

该对照不是与材料科学家或研究团队的普遍比较，不能外推到完整科研周期。若 H16 来不及完成六对，至少三对并标小样本，保留失败记录和限制。

## 11 验收与故障处理

| 检查 | 验收标准 | 负责人 |
|---|---|---|
| 合成边界案例 | 0 带隙有效；无效 ehull 不通过；零分母 null；公式不重复 | A |
| 配对方法 | OPT 和 MBJ 相同 jid 与相同组成代表，不逐行 coalesce | A |
| 划分防泄漏 | 任一组成只在一个 split；冻结前读取 holdout 被拒 | A 与 B |
| 判据冻结 | 改已注册 Spec 被拒；CI 含零不写反向 | A 与 B |
| 工具输入 | 未知模板、任意代码、任意路径、跨 run ID 被拒 | B |
| 权限 | Skeptic 不能运行实验或改 Result；PI 不能直接算数值 | B |
| 故障 | timeout 与 schema error 保留执行失败，不产生科学结论 | B |
| 幂等恢复 | 重复请求返回同 Result；中断重启不覆盖历史 | B |
| 真实编排 | 子 agent 到函数到根 agent 证据链可查 | B |
| 端到端 | 三次 live 工程演练，至少一次不同合法预算输入 | 两人 |
| 展示真实性 | live replay fixture 显著区分，数字与 Result 完全一致 | 两人 |
| 可复现 | 新终端按 README 用缓存快照重跑实验，得到相同数值 | A |

测试应保护科学结论与真实集成，不给颜色、标题等低风险 UI 细节堆测试。固定计算 seed 可复现数值；LLM 的解释和实验选择可能变化，保留模型、prompt hash、调用记录与每次实际选择，不宣称所有输出逐字确定。

run 的子 agent dispatch 暂定总上限 16 次，最多一次 schema 修复，重试也计入上限。Planner 和 Skeptic 的短 dispatch 默认 60 秒；Runner dispatch 默认 150 秒，包含最长 120 秒实验和返回提交余量。Scientist PI 根 session 只受整条 run 的 12 分钟墙钟上限，不套 60 秒 dispatch 限制。所有步骤均受剩余 run 时间约束，不能因局部 timeout 更长而越过全局 deadline。

dispatch 与 provider 内部模型请求不是同一计数；只在实际能观测 provider 请求时才记录请求数，并在可监控时设置单请求 60 秒超时，不把工具调用限制当请求硬上限。H2 必须验证能否监控和取消 dispatch；若不可逐项强制，则注明 dispatch 预算为软限制，12 分钟的 run 墙钟上限仍由外部可信启动器强制终止整个进程组，并记录 cancelled。根及子 session 的工具限制之外，宿主还维护共享墙钟和实验预算。预算 deadline 在 run 创建时持久化，重启不重置预算。

实验在独立 worker 进程中执行，120 秒到时终止并等待 worker 回收，再写 tool_failed；不能只设置 future 等待超时而任由计算继续。整条 run 到时同时取消模型 session 与 worker。工程验收必须包含超时后没有孤立 worker 和旧结果提交。价格可被 provider 记录时保存实际用量；没有可靠用量时写 unavailable，不用 token 猜造费用。超预算的计划直接拒绝。

现场网络失败使用已缓存数据重跑确定性实验。若模型不可用，可展示已保存的 live run 回放并说明网络故障，提交保留真实历史；不能宣称回放正在重新自主运行。磁盘写入失败停止实验并保留 error，不以聊天输出顶替结果记录。

## 12 两分钟展示和提交清单

| 时间 | 内容 | 画面证据 |
|---|---|---|
| 0 至 15 秒 | 科学问题与原假设 | 问题、固定协议、数据快照 |
| 15 至 35 秒 | 两个测试中选择一个 | Omnigent 调用和 Planner 理由 |
| 35 至 60 秒 | 真实 Python 结果 | 分母、差值、重采样区间、数据质量 |
| 60 至 90 秒 | Skeptic 质疑，改变下一实验 | concern 引用、下一 Spec、真实执行 |
| 90 至 110 秒 | 留出结果与实测流程效率 | 条件结论、计时、失败数 |
| 110 至 120 秒 | 下一验证与限制 | 方法依赖、计算候选、实际验证待做 |

两分钟展示不保证整个 live run 在两分钟内完成。可在台上启动短工具步骤，或用清晰标注的真实运行录像展示完整过程；仓库仍必须能重跑真实闭环。不要预设 H1 必须失败，证据不足或方法敏感同样能构成合理的下一步。

下一科学步骤应按结果具体选择：独立数据快照验证、补充更高精度电子结构和光学吸收评估、或实际实验。带隙与 ehull 不能单独预测器件效率，元素排除也不能证明毒理安全。

提交清单包括仓库和依赖锁、安装及复现命令、agent specs 与 policies、来源与数据许可、manifest 和 split hashes、冻结假设及全部 Specs、实验代码、原始数值和图表、Ledger 与事件导出、基线原始计时、下一实验说明、两分钟 demo、局限和人工批准边界。若原数据不允许再分发，只提交下载步骤、快照标识与校验值，不把数据许可视为默认开放。

## 13 对抗性审查和尚待实测项

本文件经两名独立子 agent 分别进行工程与科学对抗性审查并多轮修订。已发现的严重问题包括把同一缺失审计重复计算当第二实验、初始和留出 Spec 缺少注册接缝、第二轮状态回退，以及 agent 超时短于合法工具运行时间。修订后已逐项复核。静态审查不能保证安装、网络、数据覆盖或实际运行无故障。

| 审查发现 | 修订后的处理 |
|---|---|
| 缺失审计重复，第二轮没有新证据 | 缺失范围随 Result 记录；第二轮做不同的分层或参数轴实验 |
| 初始和验证 experiment_id 无注册来源 | PI 事务注册初始 Spec；freeze_final 派生 holdout Spec |
| 第二轮计划将状态退回第一轮 | 下一提案仅追加事件，commit 检查 review_ready |
| 模型调用和 dispatch 混淆 | 分开统计，硬预算用可信宿主墙钟限制 |
| 60 秒 agent timeout 杀死 120 秒实验 | 短角色 60 秒，Runner 150 秒，根使用全局 12 分钟 |
| 验证标签绕过质量门槛 | 复用 scientific_status，保留 complete-case 与缺失限定 |
| 旧 worker 可迟到覆盖恢复结果 | 独占 lease、attempt token 与 compare and swap |

上线前必须实测的项目为 Omnigent 版本与模型接入、子 agent 工具权限、实际字段覆盖、实验时长、预算 hook 和恢复行为。未执行这些检查前，不将设计说成已实现。不把无误理解为获得科研或竞赛结果保证。

## 14 参考资料

[1] 用户提供的 challenge brief，7th Global AI Hackathon，Agentic Scientific Discovery，第 2 至 4 页。时间、评分、Omnigent 必须参与、实验改变下一决策和提交要求均来自此文件。

[2] JARVIS 官方数据下载说明。用于确认可用字段，实际覆盖率仍按快照审计。https://jarvis-materials-design.github.io/dbdocs/thedownloads/

[3] Choudhary 等，Computational screening of high-performance optoelectronic materials using OptB88vdW and TB-mBJ formalisms，2018。用于支持分开分析带隙计算方法。https://arxiv.org/abs/1804.01032

[4] Materials Project 官方 Glossary of Terms 中 Energy above hull。用于说明该指标的计算热力学含义与局限，不将 MP 数值阈值直接移植为 JARVIS 实验事实。https://docs.materialsproject.org/frequently-asked-questions/glossary-of-terms

[5] Omnigent 官方 Agent YAML spec。用于确认配置能力；集成须根据实际安装版本检查。https://github.com/omnigent-ai/omnigent/blob/main/docs/AGENT_YAML_SPEC.md

[6] Omnigent 官方 Policies 文档。https://github.com/omnigent-ai/omnigent/blob/main/docs/POLICIES.md

[7] Omnigent 官方 README 安装说明。https://github.com/omnigent-ai/omnigent/blob/main/README.md

以上公开资料检索日期为 2026 年 10 月 3 日。阈值、预算、分工、接口与实验目录为本项目设计选择，未伪装成资料中的验证结论。
