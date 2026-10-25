# Controlled Live Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 用户已选 Inline；实施不委派，仅在交付前做一次限定独立审查。

**Goal:** 为冻结的双方法评测建立独立受控执行入口，本轮只证明离线工程正确，不执行真实模型。

**Architecture:** 先验证冻结包和人类批准的执行清单，再由可信控制器逐槽位启动仅持有公开材料的worker。复用CallBudget、comparison_methods、run_slots及grade_layered；worker超时后只清理自身确切CID，技术异常停止后续调度。

**Tech Stack:** Python3.13、pytest、现有OpenAI兼容客户端、现有受验Docker后端；无新依赖。

## Global Constraints

- 实施工作区：C:/Users/Jerry/.codex/worktrees/evaluation-v2/PyRepair Agent；保留dirty改动、detached HEAD，不做Git写操作。
- 当前仅离线：不读取.env或真实DEEPSEEK_API_KEY、不发API、不创建真实授权或实际额度。测试用自编假凭据/模型/仓库。
- 不修改src/pyrepair、旧live安全门、Docker可信harness/profile、旧包及失败产物。
- model=deepseek-flash；endpoint=https://api.deepseek.com；thinking=enabled/high；默认temperature/seed/max_tokens仍未指定。
- single-shot限1次，full-agent Repair+Review合计限36次；provider_retries=0、sdk_retries=0、worker_timeout=1800；测试阶段≤120秒。
- 额度是ModelClient预留上限，不是现金上限或实测HTTP次数；没有usage保留unknown。
- smoke只选os_more_seekable_1269 r2、trial1的原顺序两个槽位；formal完整20题×3×2=120。smoke和formal输出/授权/预算独立。
- 模型进程不接收EvaluationCase、隐藏资产、gold/wrong、判分反馈；上游Python仅在Docker执行。
- 新源码需要新冻结包；旧lp-1023-74d56f08保留历史身份。

## File structure

- 新建benchmarks/evaluation/live_plan.py：无凭据副作用的计划构造、严格授权核对、公开job边界。
- 新建benchmarks/evaluation/comparison_worker.py：唯一可信模型worker；生产provider延迟装配，复用双方法。
- 新建benchmarks/evaluation/worker_supervisor.py：受控子进程、异常证据、确切容器身份与清理。
- 新建benchmarks/evaluation/live_comparison.py：控制器装配与分层评分；保留原journal恢复语义。
- 新建benchmarks/run_live_comparison.py：默认inspect，execute/resume必须显式授权。
- 修改benchmarks/evaluation/comparison_pack.py：将新增独立CLI加入运行源码身份。
- 对应新建tests/test_live_plan.py、test_comparison_worker.py、test_worker_supervisor.py、test_live_comparison.py、test_live_comparison_docker.py。
- docs/controlled-live-comparison-offline.md及工程日志：实际验证证据与剩余授权边界。

### Task 1: 计划、授权与公开输入边界

**Interfaces:** `describe_plan(pack_path, pack, output, mode, call_limit)->dict`只返回未批准计划；`validate_authorization(value, expected)->dict`严格核对；`public_job(pack_path, pack, slot, folder, quota, call_limit)->dict`仅构造公开job；`validate_job(job)->dict`不读凭据。

- [x] 写失败测试：精确计划绑定；model/endpoint/order/limit/output/runtime/env/pack篡改拒绝；bool不是额度；smoke错误修订拒绝；输出重叠拒绝；job不含私有内容。

```python
expected = describe_plan(pack_path, pack, output, "formal", 37)
approval = {"version": 1, "approved": True, "plan": expected,
            "plan_hash": digest(expected), "human_confirmation": "owned offline fixture"}
approval["plan"]["slots"].reverse()
with pytest.raises(ValueError):
    validate_authorization(approval, expected)
```

- [x] 运行test_live_plan.py，确认缺少模块/接口导致失败。
- [x] 实现严格白名单、规范摘要比较、路径隔离、逐槽位限额，真实计划必须deepseek-flash，授权文件不能自行授予用户许可。
- [x] 重跑新增测试与comparison_pack/evidence测试，记录测试证据。无需Git提交。

### Task 2: worker与超时/容器清理

**Interfaces:** `run_job(job, client_factory)->dict`通过工厂只建立零重试客户端；`run_worker(job_path, ..., timeout=1800)->dict`启动可信进程；`cleanup_owned(root, lock)->dict`只核对和清理该root记录的CID。

- [x] 写失败测试：两方法真实组件+FakeLLM；输入或环境失效先于工厂；API错误保留预留不写候选；共享Repair/Review用量；子进程超时/异常不重启；身份错误不触及容器。

```python
with pytest.raises(RuntimeError):
    run_job(valid_job, failing_client_factory)
assert read_usage(quota)["reserved_calls"] == 1
assert not (output / "candidate.json").exists()
```

- [x] 运行新增测试确认失败；只在外部进程/Docker/提供方边界使用fake。
- [x] 实现：worker只读公开job和锁；实际凭据仅显式live模式通过环境获取，不写命令/job/log。自编FakeLLM由测试进程入口装配，不能从不可信job动态导入任意工厂。
- [x] 实现：父进程终止自启动进程树后检查每个受信目录的cidfile/request；核对Name=pyrepair-<run_id>、image/profile/mount/环境hash再stop/inspect/rm；无法确认则技术暂停，不做全局扫描或prune。
- [x] 重跑测试；一份响应后崩溃可本地解析，full-agent无候选保持中断；不重发。无需Git提交。

### Task 3: 控制器与独立CLI

**Interfaces:** `inspect_execution(pack_path,cases,output,mode,call_limit)->dict`核对后返回未批准计划；`execute_comparison(..., authorization, resume=False)->dict`执行已绑定计划；CLI仅显式execute/resume可读取批准清单。

- [x] 写失败测试：inspect无凭据/额度/输出副作用；所有身份错误先于credential getter/provider；新建/恢复输出身份不同不能复用；普通候选失败继续，技术错误暂停；预算不足无请求。

```python
summary = execute_comparison(..., executor=owned_executor)
assert summary["planned"] == 2
assert summary["real_model_trials"] == 0  # 仅离线测试报告应明确标识
```

- [x] 运行新增测试确认失败；实现复用run_slots，并从冻结control/cNN/collection.json给grade_layered完整节点。
- [x] 执行清单固定slot子计划与独立run身份；检查真实key只允许env且缺失停机。主CLI没有生成approved清单命令。
- [x] 将CLI摘要纳入pack runtime；保持run_comparison原prepare/verify/simulate不变。
- [x] 跑聚焦测试；日志/输出不含测试假密钥。无需Git提交。

### Task 4: 集中离线验收与新冻结包

- [x] 新进程+实际Docker+自编FakeLLM两方法产生补丁、独立core/extension验收；禁止宿主pytest fallback；真实请求0。
- [x] 一次集中离线tests（排除live/docker），另跑实际Docker测试；Ruff check/format --check新改文件；保存JUnit。
- [x] 使用requesting-code-review做一次限定只读审查；修复有证据的缺陷并针对复验，重大修复后重做最终验证。
- [x] 代码稳定后以原两manifest、原lock新建完整20题包；prepare和verify；新120脚本槽位仅验证调度，恢复不重做。旧包不变。
- [x] 对比22生产源码及旧资产保护摘要，记录每项问题、原因、处理和证据，更新报告/清单/计划勾选。
- [x] 完成仅指离线入口工程验收，不指真实性能。下一步另询more r2双方法smoke最多37次预留的明确许可，不自动执行、发布或提交。

完成证据：930passed/9deselected；实际Docker/FakeLLM新进程2passed；13文件静态通过；当前20题包lc-1023-f39590ec已实际132容器校准/verify；lcs-1023-8fd52798完成120脚本槽位且恢复journal不变。详见docs/controlled-live-comparison-offline.md。未创建实际付费授权，默认inspect实际检查输出目录未创建；用户先前选择保留工作区、不发PR，继续遵守，不再重复询问Git集成菜单。

## Execution / verification commands

测试Python固定为D:/Project/PyRepair Agent/.venv/Scripts/python.exe。PYTHONPATH优先当前worktree/src及root；测试临时根使用D:/Project/PyRepair Agent/tmp/live-23c999c9；清除测试进程DEEPSEEK_API_KEY，不读原值。

```powershell
& 'D:/Project/PyRepair Agent/.venv/Scripts/python.exe' -m pytest tests/test_live_plan.py -p no:cacheprovider -o tmp_path_retention_count=1000
& 'D:/Project/PyRepair Agent/.venv/Scripts/python.exe' -m pytest tests -m 'not live and not docker' -p no:cacheprovider --junitxml='D:/Project/PyRepair Agent/tmp/live-23c999c9/full-regression-final.xml'
```

自审：全部设计范围对应Task1–4；没有真实执行授权、没有费用承诺、没有Git写步骤。实际Docker新进程集成和新20题校准必须真实运行，不能用旧证据替代。
