# 共享公开文件修改范围 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 两方法和 Review 事先获得与评分器一致的文件修改范围，离线验证并生成独立新冻结包。

**Architecture:** 从既有允许路径和公开说明生成 TASK 前缀，沿现有 ContextBundle 链路发送。公开输入策略和事实策略升级，结构和评分器不变；冻结准备/核验把 TASK 和 evidence 绑定到评分清单。复用既有受验 Docker，仅用 FakeLLM 验证模型边界。

**Tech Stack:** Python >=3.11，pytest，dataclasses，SHA-256，现有 Docker 后端和 FakeLLM。

## Global Constraints

- 依据[批准设计](../specs/2026-10-24-public-edit-scope-design.md)，沿用 evaluation-v2 linked worktree；不在 main 实施。
- 不修改 src/pyrepair、评分器、80行门禁、隐藏/gold/wrong、任务 revision 或原资产。
- 不读.env，所有离线子进程清除 DEEPSEEK_API_KEY；不调用 API、使用剩余29/16次或启动正式120次方法运行。
- 不提交、合并、推送或PR；以本地摘要/检查点替代每任务 Git commit，保留所有旧实验。
- PublicTaskSpec.version=1/字段不变，input_policy=agent-public-r2，evidence_policy=exact-public-facts-r2。
- task_contract完整不超过4,000字符，上下文不超过16k字符/8片段，不截规则，不扩大预算。
- 用户此前已选择节约Token的Inline，继续使用executing-plans，不重新分派每个微任务。

## 文件职责与运行目录

| 文件 | 改动 |
| --- | --- |
| benchmarks/evaluation/agent_input.py | public_task_contract(case) → str；先验证/生成，再复制公共输入 |
| benchmarks/evaluation/comparison_pack.py | _verify_public_contract(case, repo, evidence) → None；两处调用；事实策略升级 |
| tests/test_public_edit_scope.py | 新增行为与边界反例，不引入生产测试钩子 |
| tests/test_agent_input.py / test_agent_test_runner.py / test_comparison_evidence.py | 更新显式r2夹具与旧“TASK等于原始说明”断言 |
| tests/test_comparison_methods.py / test_live_comparison_docker.py | 强化真实消息边界，包括Review与跨进程同材料 |
| docs/public-edit-scope-offline.md / README.md / 工程日志 / 检查表 | 实际证据与未完成事项，不填入预期成绩 |

工作目录：`C:/Users/Jerry/.codex/worktrees/evaluation-v2/PyRepair Agent`。
检查目录：`D:/Project/PyRepair Agent/tmp/scope-1024-66ec3736`。
新包：`D:/Project/PyRepair Agent/tmp/scopepack-1024-66ec3736`。
脚本模拟：`D:/Project/PyRepair Agent/tmp/scopesim-1024-66ec3736`。
Python：`D:/Project/PyRepair Agent/.venv/Scripts/python.exe`。

所有测试使用同一进程设置：

```powershell
$env:TEMP='D:/Project/PyRepair Agent/tmp/scope-1024-66ec3736'
$env:TMP=$env:TEMP
$env:PYTEST_DEBUG_TEMPROOT=$env:TEMP
$env:PYTEST_ADDOPTS='--rootdir=.'
$env:PYTHONPATH='C:/Users/Jerry/.codex/worktrees/evaluation-v2/PyRepair Agent/src;C:/Users/Jerry/.codex/worktrees/evaluation-v2/PyRepair Agent'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:RUFF_CACHE_DIR=Join-Path $env:TEMP 'ruff'
Remove-Item Env:/DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
```

### Task 1: 公开约束生成与前置验证

**Files:** agent_input.py；新增test_public_edit_scope.py；更新test_agent_input.py/test_agent_test_runner.py。

**Interfaces:** Consumes EvaluationCase.allowed_source_paths/buggy/description；produces public_task_contract(case: EvaluationCase) -> str，prepare_agent_input原签名不变。

- [x] 写反例：调用prepare_agent_input后，从TASK首个独立JSON数组解析路径，预期手写`["src/app.py"]`；多文件实际夹具为`["src/辅助 space.py", "src/app.py"]`，覆盖顺序、空格及Unicode；其它源码字节不变、private内容不进入展示。
- [x] 对空/空白/非法UTF-8/4k任务以及空/重复/大小写碰撞/越界/过滤/测试/缺失路径逐项参数化，断言ValueError且destination不存在。测试来自真实load_cases夹具后用dataclasses.replace制造无效输入，不改正常加载规则。
- [x] 保存首次red-public-scope.xml；修正FailureReport夹具必填字段后，再存red-scope-corrected-fixture.xml，确认21个失败均指向真实功能缺口而非构造错误。
- [x] 实现以下边界，组合文本采用批准设计中的固定前缀，JSON序列化路径：

```python
def public_task_contract(case: EvaluationCase) -> str:
    paths = case.allowed_source_paths
    if not isinstance(paths, tuple) or not paths:
        raise ValueError("public edit scope must not be empty")
    for name in paths:
        protocol.safe_path(name)
        path = contained(case.buggy, name)
        if (_excluded(name) or not path.is_file()
                or path.suffix not in {".py", ".pyi"}
                or _is_protected(PurePosixPath(name))):
            raise ValueError("invalid public edit source")
    if len({name.casefold() for name in paths}) != len(paths):
        raise ValueError("duplicate public edit source")
    with case.description.open("rb") as stream:
        raw = stream.read(protocol.MAX_INPUT_FILE + 1)
    if len(raw) > protocol.MAX_INPUT_FILE:
        raise ValueError("public task contract exceeds size limit")
    body = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    validate_task_contract(body, required=True)
    prefix = (
        "## 公开评测约束（agent-public-r2）\n"
        "允许修改的现有源码文件（相对仓库根目录，精确文件路径；不是目录或通配符）：\n"
        + json.dumps(list(paths), ensure_ascii=False)
        + "\n\n补丁只能修改以上文件，不得新增、删除或重命名文件。\n"
        "其他公开文件仅可通过原有工具权限读取，不得修改。\n"
        "不得修改测试、配置、依赖或环境。\n\n## 原始公开任务说明\n"
    )
    return validate_task_contract(prefix + body, required=True)
```

- [x] prepare_agent_input先调用生成函数，再stage_public_snapshot；写新TASK为UTF-8字节，继续inventory_hash；INPUT_POLICY升级r2。不更改复制其它文件的行为。
- [x] 更新旧描述夹具为r2；旧policy另设反例必须拒绝。旧TASK断言改为“包含完整原说明＋准确允许路径＋原资产不变”，不能删除测试。
- [x] 运行相关输入测试与新增文件，保存green-public-scope.xml，再进行Task2。

### Task 2: 冻结绑定、两方法及Review消息一致

**Files:** comparison_pack.py、test_public_edit_scope.py、test_comparison_methods.py、test_comparison_evidence.py、test_live_comparison_docker.py。

**Interfaces:** Consumes public_task_contract(case)、read_evidence；produces _verify_public_contract(case, repo, evidence) -> None，prepare_pack/verify_pack原签名不变。

- [x] 写篡改反例：公开TASK或evidence.task_contract/overview换成另一文件清单；重新计算公开spec/evidence/pack哈希后，verify_pack仍必须因合同与评分源不一致而拒绝。使用tests/test_comparison_pack.py的make_prepared，只替换外部Docker耗时边界，保持真实prepare/verify。
- [x] 加入共享消息反例：在已有完整FakeLLM修复中解析Repair首次用户消息，准确路径数组为`["src/app.py"]`；与single-shot实际首次用户消息逐值相同。Review最后请求的task_contract.content必须含同一说明，不含private/gold。不能只检查字符串scope存在。
- [x] 加入接近16k的ContextBundle反例：PublicContractContext须裁剪尾部代码片段，生成的完整TASK与路径数组仍在overview和task_contract，total_chars正确且<=16000。
- [x] 保存red-freeze-binding.xml；缺失消息的失败应因约束不在材料中，篡改反例应能通过旧verify，从而证明旧实现缺失语义绑定。
- [x] 实现明确文本绑定：

```python
def _verify_public_contract(case, repo, evidence):
    expected = public_task_contract(case)
    if (repo / "TASK.md").read_bytes() != expected.encode("utf-8"):
        raise ValueError("public task contract differs from grader edit scope")
    context = evidence["context"]
    if (context["task_contract"] != expected or not
            context["repo_overview"].startswith("Public task contract:\n" + expected + "\n")):
        raise ValueError("public evidence contract differs from grader edit scope")
```

- [x] 在prepare的capture_evidence后、写evidence前调用；verify的read_evidence后调用；config.evidence_policy升级r2。不修改生产Repair/Review或两方法专属提示词。
- [x] 写评分反例：自编夹具里，准确允许文件的正常diff仍被apply_patch_checked接受；未列出的现有__init__.py diff仍被原评分器拒绝，失败发生于应用前。不是重判旧模型候选。
- [x] 集中相关测试保存green-scope-binding.xml，Ruff check/format仅本轮Python文件，保留原无关排版。

### Task 3: 集中验证、全新离线冻结与交付

**Files:** docs/public-edit-scope-offline.md、README.md、工程日志、检查表、spec/本计划的状态；新tmp目录证据，不改旧结果。

**Interfaces:** 使用原run_comparison.py prepare/verify/simulate CLI，既有环境锁，不新增付费入口。

- [x] 完整非live/non-Docker回归一次：

```powershell
& 'D:/Project/PyRepair Agent/.venv/Scripts/python.exe' -m pytest tests -m 'not live and not docker' -p no:cacheprovider -o tmp_path_retention_count=1000 --junitxml 'D:/Project/PyRepair Agent/tmp/scope-1024-66ec3736/full-regression.xml' -q
```

- [x] 显式Docker选择现有跨进程双方法＋独立判分测试，强化其owned-requests断言：两方法首个用户消息相同，允许路径准确，Review收到同TASK。环境锁变量指向既有919fe7da锁；无宿主fallback。
- [x] 上一步和完整宿主回归不并行，避免上游时间测试抖动。再运行全20题prepare和verify：

```powershell
$env:PATH='C:/Users/Jerry/AppData/Local/Programs/DockerDesktop/resources/bin;' + $env:PATH
$env:PYREPAIR_DOCKER_ENVIRONMENT_LOCK='C:/Users/Jerry/.codex/worktrees/evaluation-v2/PyRepair Agent/benchmarks/results/opensource/environment-agent-v2-fixed-20261022-9e13c980/environment-lock.json'
& 'D:/Project/PyRepair Agent/.venv/Scripts/python.exe' benchmarks/run_comparison.py prepare --environment-lock $env:PYREPAIR_DOCKER_ENVIRONMENT_LOCK --model deepseek-flash --output 'D:/Project/PyRepair Agent/tmp/scopepack-1024-66ec3736'
& 'D:/Project/PyRepair Agent/.venv/Scripts/python.exe' benchmarks/run_comparison.py verify --pack 'D:/Project/PyRepair Agent/tmp/scopepack-1024-66ec3736'
```

- [x] 只在prepare/verify实际成功后运行simulate两次，第二次为本地恢复，不是补跑：

```powershell
& 'D:/Project/PyRepair Agent/.venv/Scripts/python.exe' benchmarks/run_comparison.py simulate --pack 'D:/Project/PyRepair Agent/tmp/scopepack-1024-66ec3736' --output 'D:/Project/PyRepair Agent/tmp/scopesim-1024-66ec3736'
& 'D:/Project/PyRepair Agent/.venv/Scripts/python.exe' benchmarks/run_comparison.py simulate --pack 'D:/Project/PyRepair Agent/tmp/scopepack-1024-66ec3736' --output 'D:/Project/PyRepair Agent/tmp/scopesim-1024-66ec3736'
```

- [x] 核对20题指纹/revision/评分范围未变、公开r2准确完整、运行摘要只变本轮两个文件、src/可信harness/环境锁/旧两次smoke四核心文件摘要不变；模拟120/120且real_model_trials=0、成绩null；Docker确切CID清理无残留。记录实际次数和错误，不把预期写成已发生。
- [x] 一次限定差异审查和验证，再更新README/工程日志/检查表/报告；文档明确“已告知文件修改范围”，旧结果只读保留、不混合统计。所有未执行步骤保持未完成。
- [x] 交付本地成果；下一次真实smoke需新的冻结身份与单独授权，不自动安排付费运行或Git发布。

## 自审与执行选择

范围、4k/16k、输入版本、单次/Agent/Review材料相同、失配早拒绝、评分不变、多文件、历史隔离分别由Task1–3覆盖。接口名称一致，不新增生产参数或后台任务。计划已自审；按用户既定Inline选择直接执行，不再次要求在两个执行方式之间重复选择。

执行完成（2026-10-24）：982项完整离线、1项真实Docker链路、20题新包校准/verify、120脚本槽位/恢复均通过；模型请求0，未Git发布。实际证据与限制见[离线记录](../../public-edit-scope-offline.md)，不把本计划中的预期当作模型成绩。
