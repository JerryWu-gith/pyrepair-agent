# 合成修复评测：case_15 精度验收迁移

日期：2026-10-22。范围继承用户已确认的[收尾标准](../../evaluation-completion-checklist.md)第4项和本轮“请继续”，沿用已批准的[金额精度验收](2026-10-17-review-hard-candidates-design.md)，不重新设计金额契约或模型行为。

## 目标与边界

将已校准的6个金额×3种Decimal context精度检查迁入18题修复评测的新集合。原题合同没有金额长度上限，长金额属于既有契约；不新增负数、非法输入、超过两位小数或其他未定义行为。不更改公开源码、公开测试或任务说明。

旧manifest_v2.json、18题旧资产、Review集合和历史54/54全部保留。新增集合仍为synthetic/dev，不是holdout或真实缺陷。无API调用，不改src或评分器，不启用真实开源模型入口，不提交/合并/推送/PR。

## 最小方案

直接引用Review私有目录虽省三个文件，但使修复评测依赖Review题库路径；重写边界测试又会引入新差异。采用逐字节复制已校准私有资产到独立新revision，记录来源摘要。

- 新清单：`benchmarks/manifest_synthetic_v3.json`，仍使用现有schema version2，包含原18题；仅case_15变为revision2并指向新private目录，其余17题metadata原样复制。
- 新私有目录：`benchmarks/eval_private/synthetic_v3/case_15/`。gold.patch、wrong.patch、hidden_tests/test_acceptance.py从review_cases_hard_v1/private/case_15逐字节复制；provenance.json记录旧/新清单、来源路径/哈希和人工校准/历史候选身份。
- case_15的F2P/P2P列表复用manifest_review_hard_v1.json的已校准声明；仅复制这些列表，不把review_collection标记带入修复题目的origin。
- 原公开源码、TASK路径、visible_tests、allowed_source_paths、timeout、suite/split/source_kind保持不变。新origin明确这是既有公开契约的精度验收迁移。
- 旧默认CLI继续使用manifest_v2.json；新集合仅通过显式--manifest选用。新旧任务指纹不同，不能续跑或合并旧实验。

## 验收与错误处理

先用自有测试观察新集合缺失的RED，再追加资产。实际运行既有validate_case/grade_patch：buggy指定F2P失败，gold公开/隐藏全通过，wrong公开通过但隐藏精度断言失败。额外确认旧case_15 gold在新隐藏验收被拒，不能再把它当新协议正例。

随后使用现有CLI对新18题全部离线校准，输出新目录；不覆盖失败或历史结果。缺文件/哈希不符/已有新目标均停止，不自动回退旧清单。对照4,130旧保护摘要，最终集中跑一次完整离线回归和相关Ruff。报告只写验收结果，不写新模型成功率。

## 非本步范围

Agent容器适配、single-shot基线、付费重复运行和GitHub发布均不进入本步。迁移不改变Docker harness，因此不重建镜像或重跑开源容器校准。
