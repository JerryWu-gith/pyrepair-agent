# 50 题评测：STAGED 整体修复工作流对照

发布日期：2026-10-27。模型：`deepseek-flash`。本报告依据保存的最终汇总与逐任务记录整理，不是本次发布时重新发起模型请求所得。

50 题包含 20 个自建开发任务、30 个来自五个仓库的真实开源缺陷；双方法每题各三次独立重复，共 300 次方法运行，已全部完成。所有重复等权计入分母，**不取 best-of-three**。

| 核心验收范围 | 完整 Agent 工作流 | 单次生成补丁 |
| --- | ---: | ---: |
| 全部 50 题 × 3 | 135/150（90.0%） | 53/150（35.3%） |
| 自建 20 题 × 3 | 59/60（98.3%） | 44/60（73.3%） |
| 开源 30 题 × 3 | 76/90（84.4%） | 9/90（10.0%） |
| 其中：28 个开源 holdout × 3 | 71/84（84.5%） | 8/84（9.5%） |
| 其中：2 个已知开源开发题 × 3 | 5/6（83.3%） | 1/6（16.7%） |

| 三次全部通过的任务 | 完整 Agent 工作流 | 单次生成补丁 |
| --- | ---: | ---: |
| 全部 | 39/50 | 11/50 |
| 自建开发题 | 19/20 | 10/20 |
| 开源全部 | 20/30 | 1/30 |
| 开源 holdout | 19/28 | 1/28 |
| 开源已知开发题 | 1/2 | 0/2 |

这是 **STAGED（分阶段完成）的整工作流比较**：完整 Agent 使用更多调用、反馈、Review 与验证预算，不能据此归因于模型能力的单一因素，也不是等算力消融实验或 SWE-bench 成绩。

## 协议与评分范围

两方法使用相同初始公开材料、允许修改文件范围及独立评分合同；每次独立运行从干净副本开始。完整工作流包括多轮工具反馈、外层重试、补丁规则、独立 Review、测试验证；单次方法生成一次候选，再交给独立评分器。Agent 内部报告成功不直接等于最终接受。

“核心验收通过”表示候选通过选定的公开与隐藏合同测试，**不是通过全部上游测试**。公开复现进入修复侧；隐藏验收和参考补丁不进入修复角色的工作副本或模型输入，由独立评测侧使用。分数只覆盖该合同声明的行为，不能推广为任意业务条件下正确。

任务资产校准先检查缺陷基线复现、参考生产补丁通过，以及针对性不完整补丁被隐藏边界拒绝。开源资产的来源、准备和校准历史分别见[来源目录](opensource-catalog30.md)、[准备记录](opensource-reference-preparation.md)、[离线校准](opensource-task-calibration.md)。这些阶段检查不是模型性能结果。

20 个自建题及 2 个开源题是开发任务；28 个开源 holdout 未用于本项目 Agent 提示词或策略调优。holdout 标签不保证基础模型预训练没有见过公开源码、缺陷或补丁。五个仓库中包含同类问题，30 个开源题不等于 30 个统计独立工程环境。

## 分阶段执行与恢复边界

| 阶段 | 最终正常方法运行 | 模型角色调用 |
| --- | ---: | ---: |
| 原执行阶段 | 129 | 492 |
| 恢复阶段 | 4 | 14 |
| 后续新增执行阶段 | 167 | 1121 |
| 合计 | 300 | 1627 |

原始执行曾出现 Docker 环境超时，以及在零模型调用时暴露的 hash 基线错误；两类原始技术事件均保留，未将其描述为模型修复失败，也未抹去其发生事实。最终汇总的技术错误槽位为 0，不代表执行过程从未发生技术错误。

恢复包含对同一候选进行 **0 LLM 调用重验**，以及仅在比较副本进行 hash／有佐证对象地址归一化；原模型输入、任务及评分合同保持不变。已有 28 份公开观测重新核验，没有重复生成旧请求。因此结果保留 STAGED 标签，不声称来自一次完全无中断、同环境原子执行。

## 分仓库核心验收

每个分母为任务数 × 3；与自建题一起计入总分，不把扩展回归节点数当作任务数。

| 开源仓库 | 任务数 | 完整 Agent 工作流 | 单次生成补丁 |
| --- | ---: | ---: | ---: |
| mahmoud/boltons | 1 | 3/3（100.0%） | 1/3（33.3%） |
| more-itertools/more-itertools | 3 | 8/9（88.9%） | 2/9（22.2%） |
| pallets/click | 8 | 18/24（75.0%） | 1/24（4.2%） |
| pypa/packaging | 12 | 31/36（86.1%） | 0/36（0.0%） |
| theskumar/python-dotenv | 6 | 16/18（88.9%） | 5/18（27.8%） |
| 合计 | 30 | 76/90（84.4%） | 9/90（10.0%） |

## 逐题结果

下表为独立核心验收通过次数／计划三次，不是三次中取最好一次；`dev` 为已知开发题，`holdout` 的含义与上文一致。

| 任务 ID | 来源/划分 | 完整 Agent 工作流 | 单次生成补丁 |
| --- | --- | ---: | ---: |
| `case_01` | synthetic/dev | 3/3 | 3/3 |
| `case_02` | synthetic/dev | 3/3 | 3/3 |
| `case_03` | synthetic/dev | 3/3 | 3/3 |
| `case_04` | synthetic/dev | 3/3 | 2/3 |
| `case_05` | synthetic/dev | 3/3 | 3/3 |
| `case_06` | synthetic/dev | 3/3 | 2/3 |
| `case_07` | synthetic/dev | 3/3 | 2/3 |
| `case_08` | synthetic/dev | 3/3 | 0/3 |
| `case_09` | synthetic/dev | 3/3 | 3/3 |
| `case_10` | synthetic/dev | 3/3 | 3/3 |
| `case_11` | synthetic/dev | 3/3 | 3/3 |
| `case_12` | synthetic/dev | 3/3 | 3/3 |
| `case_13` | synthetic/dev | 3/3 | 3/3 |
| `case_14` | synthetic/dev | 3/3 | 1/3 |
| `case_15` | synthetic/dev | 2/3 | 2/3 |
| `config_merge` | synthetic/dev | 3/3 | 2/3 |
| `multi_inventory` | synthetic/dev | 3/3 | 2/3 |
| `multi_orders` | synthetic/dev | 3/3 | 3/3 |
| `multi_time` | synthetic/dev | 3/3 | 0/3 |
| `multi_transfer` | synthetic/dev | 3/3 | 1/3 |
| `os_boltons_addlist_458` | opensource/dev | 3/3 | 1/3 |
| `os_click_callable_flag_3225` | opensource/holdout | 2/3 | 0/3 |
| `os_click_enum_default_3004` | opensource/holdout | 2/3 | 0/3 |
| `os_click_env_hint_2972` | opensource/holdout | 3/3 | 0/3 |
| `os_click_eof_2940` | opensource/holdout | 1/3 | 0/3 |
| `os_click_flags_2930` | opensource/holdout | 2/3 | 1/3 |
| `os_click_progress_final_3769` | opensource/holdout | 3/3 | 0/3 |
| `os_click_resource_exit_3058` | opensource/holdout | 2/3 | 0/3 |
| `os_click_zsh_colon_2846` | opensource/holdout | 3/3 | 0/3 |
| `os_dotenv_backslash_680` | opensource/holdout | 3/3 | 1/3 |
| `os_dotenv_bom_640` | opensource/holdout | 3/3 | 1/3 |
| `os_dotenv_empty_cache_638` | opensource/holdout | 3/3 | 0/3 |
| `os_dotenv_empty_get_700` | opensource/holdout | 3/3 | 3/3 |
| `os_dotenv_missing_command_606` | opensource/holdout | 3/3 | 0/3 |
| `os_dotenv_override_698` | opensource/holdout | 1/3 | 0/3 |
| `os_more_bucket_validator_1309` | opensource/holdout | 3/3 | 1/3 |
| `os_more_ichunked_sizes_1305` | opensource/holdout | 3/3 | 1/3 |
| `os_more_seekable_1269` | opensource/dev | 2/3 | 0/3 |
| `os_packaging_bool_int_1244` | opensource/holdout | 3/3 | 0/3 |
| `os_packaging_empty_tags_1234` | opensource/holdout | 1/3 | 0/3 |
| `os_packaging_file_scheme_1240` | opensource/holdout | 3/3 | 0/3 |
| `os_packaging_hash_1232` | opensource/holdout | 1/3 | 0/3 |
| `os_packaging_invalid_spec_1332` | opensource/holdout | 3/3 | 0/3 |
| `os_packaging_license_with_1266` | opensource/holdout | 3/3 | 0/3 |
| `os_packaging_literal_errors_1249` | opensource/holdout | 3/3 | 0/3 |
| `os_packaging_missing_env_1276` | opensource/holdout | 2/3 | 0/3 |
| `os_packaging_nested_extra_1246` | opensource/holdout | 3/3 | 0/3 |
| `os_packaging_nested_group_1316` | opensource/holdout | 3/3 | 0/3 |
| `os_packaging_quotes_1213` | opensource/holdout | 3/3 | 0/3 |
| `os_packaging_tag_fields_1238` | opensource/holdout | 3/3 | 0/3 |

## 调用与用量

| 模型角色 | 调用 | Prompt tokens | Completion tokens |
| --- | ---: | ---: | ---: |
| Repair | 1325 | 11,644,670 | 648,728 |
| Review | 152 | 139,594 | 962,308 |
| Single-shot | 150 | 516,576 | 1,834,685 |
| 合计 | 1627 | 12,300,840 | 3,445,721 |

已记录 1627 次角色调用预留、1627 份响应，记录的 API 错误为 0。这是模型客户端角色调用口径，不把未知的底层传输请求数当作已知。人民币费用未知，不依据 tokens 虚构结算金额；调用与 token 差异也说明本实验不等预算。

## 数据与复现入口

公开数据：[汇总 JSON](../benchmarks/results/goldset50-20261027-summary.json)、[300 次运行 JSONL](../benchmarks/results/goldset50-20261027-runs.jsonl)。逐题表与这些公开数据应按相同的任务和方法口径读取。原始提示词、响应及本机私有运行目录不在本报告中发布。

正式运行入口为 [run_goldset50.py](../benchmarks/run_goldset50.py)。先查看帮助，不调用模型：

```powershell
python benchmarks/run_goldset50.py --help
python benchmarks/run_goldset50.py prepare --help
python benchmarks/run_goldset50.py execute --help
```

按源码及上述准备、校准文档构建数据和环境，再依次使用 `assemble`、`calibrate-synthetic`、`prepare`；`prepare` 需要已校准记录和环境锁，开源题的离线校准另见校准文档。`verify --dataset <dataset> --pack <pack>` 用于身份验证，`inspect --dataset <dataset> --pack <pack> --output <new-output>` 检查计划。这里的占位符须替换为实际准备产物，不是下载后即可一键复现成绩的命令。

`execute`/`resume` 另要求 `--authorization`，并在有效身份校验后读取凭据；正式 API 运行需要独立授权且会产生费用。本报告不授权新请求，也不承诺未来同模型名服务返回相同补丁。普通 CLI 本地执行 pytest，仅适用于可信仓库；Docker 隔离属于评测层，不是 Agent 默认的操作系统沙箱。

## 解释限制

- 每题只有三次重复，任务规模小、仓库和故障类型相关；这是描述性结果，不据此宣称广泛泛化或统计独立性。
- 完整工作流与单次补丁的调用、token、验证和重试预算不同，不能将差异归因于某个组件或基础模型能力。
- 选定 core 合同测试不是所有上游测试，也不是业务正确性的完整证明；隐藏验收不等于模型训练未见。
- STAGED 恢复保留原技术事件及候选；最终技术槽位为零和 API 错误为零是不同口径，均不表示执行过程从未发生故障。
- [旧 20 题报告](controlled-comparison-r2-results.md)属于历史开发集结果，其题目、环境和执行阶段不与本轮直接合并。
