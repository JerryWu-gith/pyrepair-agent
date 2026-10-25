# 真实开源缺陷试点 Implementation Plan

> **For agentic workers:** 用户曾选择Subagent-Driven，随后提出降低Token开销；本次收尾小修复改由主线程直接实施，仅一次限定差异的独立复审。不自动commit；容量/用量中断时按文件恢复交接。2026-10-22最新状态：任务0–7开源离线试点已完成；修复后本机Docker环境验收通过、两题最终校准2/2 valid、684项完整离线回归通过。没有真实模型运行或Git发布。Steps use checkbox syntax for tracking.

**Goal:** 为两道固定真实缺陷建立可核验任务包和 Docker 离线验收，原版失败、正确补丁通过、漏修被隐藏测试拒绝。
**Architecture:** 先建立不执行外部源码的来源读取与默认拒绝边界，再组装任务，最后通过固定容器入口复用现有 grader 语义。宿主只处理数据与受限补丁；模型路径本阶段拒绝真实任务。
**Tech Stack:** Python 标准库、pytest、现有 Git patch 校验、Docker Linux/amd64；不新增 Agent 框架。

## Global Constraints

- 设计：[2026-10-20 正式设计](../specs/2026-10-20-opensource-pilot-design.md)已获用户“请继续”确认。
- 不修改 src/pyrepair/；不调用真实模型、不使用已结束的 72 次授权。
- 用户后续已明确授权安装Docker及所需WSL前提；不自动重启，不修改无关系统设置/ACL，不提交/合并/推送/PR、不清理旧资产。
- 两题和提交 SHA 按设计第 2 节，不增加题目；opensource / capability / dev，不称未见集。
- Python 3.13.5 / pytest 9.1.1 是容器目标；实际镜像和依赖身份必须核验后锁定。
- 归档下载/解包各 20 MiB，单文件 8 MiB，成员 2000；禁止链接、子模块、设备、越界和冲突。
- Docker profile：2 CPU、2 GiB memory、2 GiB memory+swap、128 PID；/work 256 MiB、/tmp 64 MiB；测试 120 秒，启动/回收各 30 秒。
- 测试时禁外网、非 root、只读输入与根、无密钥、不隐式 pull/build、不退回宿主。
- 日志 16 MiB，probe/integrity 各 16 MiB；输出最多 8 文件、单文件 16 MiB、总量 64 MiB。
- 旧默认 synthetic 命令与旧报告保持兼容。旧源码指纹失效应新建准备包，不绕过、不覆盖。
- 每个任务完成后记录 RED/GREEN 和检查结果；默认技能中的 commit 步骤替换为检查点记录。

## 执行环境与任务边界

现有工作区：C:/Users/Jerry/.codex/worktrees/evaluation-v2/PyRepair Agent（托管 detached HEAD）。
解释器：D:/Project/PyRepair Agent/.venv/Scripts/python.exe。
所有项目测试使用当前 worktree 的 src/root 作为 PYTHONPATH；移除进程 DEEPSEEK_API_KEY，使用新建的 D: 临时目录。

PowerShell 测试模板（运行前在当前进程设置）：

```powershell
$offlineScratch = Join-Path 'D:\Project\PyRepair Agent\tmp' ('opensource-offline-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $offlineScratch | Out-Null
$env:TEMP = $offlineScratch
$env:TMP = $offlineScratch
$env:PYTEST_DEBUG_TEMPROOT = $offlineScratch
$env:PYTEST_ADDOPTS = '--rootdir=.'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = 'C:\Users\Jerry\.codex\worktrees\evaluation-v2\PyRepair Agent\src;C:\Users\Jerry\.codex\worktrees\evaluation-v2\PyRepair Agent'
Remove-Item Env:\DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
& 'D:\Project\PyRepair Agent\.venv\Scripts\python.exe' -m pytest tests/ -q -p no:cacheprovider -m 'not live'
```

以下简写 python/pytest 均指上述解释器及环境，不使用 PATH 中不确定的 Python。

第一检查点为任务 0–2（安全读取与默认拒绝）；第二检查点为任务 3（assets_prepared）；第三检查点为任务 4–7（真实容器验收）。Docker 未就绪不影响前两段，但不能据此宣布第三段完成。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| evaluation/opensource_archive.py | ZIP 作为数据读取，路径/类型/大小/摘要校验；不解压执行 |
| evaluation/opensource_assets.py | 固定来源下载、文件树校验、覆盖层组装、来源证据 |
| evaluation/opensource_overlays.py | 两题公开说明、公开复现与私有边界断言，仅保存文本，不导入上游 |
| evaluation/execution_policy.py | 本机与付费入口默认拒绝 opensource；后续仅接入受信任 Docker 后端 |
| evaluation/container_protocol.py | JSON 协议、环境锁、文件摘要及输出校验，无 Docker 进程副作用 |
| evaluation/container_entry.py | 容器内复制、pytest、完整性报告 |
| evaluation/docker_runner.py | 唯一容器启动/监督/回收及结果映射 |
| evaluation/grading.py | 全部阶段使用同一后端，保留已有判分语义 |
| evaluation/pytest_probe.py | 评测失败异常类别；生产插件不变 |
| prepare_opensource_cases.py / run_evaluation.py | 显式准备；validate/grade 后端选择和 live 拒绝 |
| benchmarks/docker/ | 专用构建上下文、锁定依赖和环境说明 |
| tests/test_opensource_*.py / test_container_*.py / test_docker_*.py | 自有安全单测与显式 Docker 集成测试 |

## Task 0：基线与旧证据保护

**Files:** 只读取现有 src、旧任务资产和结果；更新本计划与 docs/evaluation-v2-engineering-log.md。

- [x] 核对 Git dir/common dir、无 superproject，确认复用已隔离工作区。
- [x] 执行完整 non-live 基线并观察最终退出码；不能以 2026-10-19 的 388 项代替本次结果。
- [x] 保存本次受保护文件摘要：src、旧 manifest、旧 eval/review 资产及旧 results；不包含本次可修改的评测代码。
- [x] 记录现有 dirty 文件，不覆盖无关修改。基线失败时先诊断，不继续叠加实现。

## Task 1：安全归档读取

**Files:** Create benchmarks/evaluation/opensource_archive.py、tests/test_opensource_archive.py。
**Interfaces:**

```python
@dataclass(frozen=True)
class ArchiveLimits:
    archive_bytes: int = 20 * 1024 * 1024
    total_bytes: int = 20 * 1024 * 1024
    file_bytes: int = 8 * 1024 * 1024
    members: int = 2000

class ArchiveError(ValueError):
    pass

def read_source_zip(
    archive: Path, *, expected_sha256: str, root_prefix: str,
    limits: ArchiveLimits = ArchiveLimits(),
) -> dict[str, bytes]:
    """Return verified relative regular-file bytes; never import or extract code."""
```

- [x] RED：在测试中用 ZipFile/BytesIO 生成内存归档，写入 tmp_path；导入待实现模块放在测试函数内部，避免 collection error。首测试断言 payload __init__.py 含写 canary 的语句却没有执行，返回 bytes 与写入字节一致。
- [x] RED：参数化 ../、绝对路径、盘符、反斜杠、NUL/非法控制字符、设备名、尾点/空格、根错误、重复成员、大小写文件/目录冲突、文件与父目录冲突、Unix symlink/FIFO、损坏 ZIP、摘要错误。返回前遇任一无效项须整体拒绝。
- [x] RED：用小 limits 验证归档大小、实际解包总量、单文件与成员数边界；拒绝空文件集；保留零字节普通文件。不得为测试真的创建巨型 ZIP。
- [x] 运行 python -m pytest tests/test_opensource_archive.py -q -p no:cacheprovider；观察缺失功能失败。
- [x] GREEN：先限量读取归档并核对 SHA-256，遍历成员检查 prefix 和元数据，复用 safe_relative；按 casefold 维护所有显式及隐式目录/文件，检查冲突。只通过 ZipFile.open 限量读普通文件，不调用 extract/extractall；累计实际字节再次校验，不信任 header。
- [x] 同一命令通过后运行相关 cases/patching 测试与 Ruff；记录实际数量，不写预期数字为成绩。

关键测试形状：

```python
def test_archive_payload_is_data_only(tmp_path):
    from benchmarks.evaluation.opensource_archive import read_source_zip
    archive = tmp_path / "source.zip"
    code = b"raise RuntimeError('must never execute')\n"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("repo-abc/pkg/__init__.py", code)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert read_source_zip(
        archive, expected_sha256=digest, root_prefix="repo-abc"
    ) == {"pkg/__init__.py": code}
```

## Task 2：在真实资产进入前阻断宿主与付费入口

**Files:** Create evaluation/execution_policy.py、tests/test_opensource_execution_policy.py；
Modify evaluation/grading.py、experiment.py、agent_worker.py、benchmarks/run_evaluation.py。

**Interfaces:** require_host_case(case: EvaluationCase) -> None；require_live_cases(cases: Iterable[EvaluationCase]) -> None。只放行 synthetic，未知来源也拒绝。此任务尚不提供 Docker 放行；Task 6 在已验证的后端上接通，不使用任意布尔标志豁免。

- [x] RED：复用 tests.evaluation_helpers.make_case 构造自有题，再 replace(source_kind="opensource")；对 validate_case、grade_patch 断言 ValueError，输出目录不得创建，测试 subprocess 不得被调用。
- [x] RED：create_experiment、run_experiment、run_agent 在碰到 opensource 时必须早于身份构建、读凭据/配置、spawn。用 forbidden 边界替身抛 AssertionError；断言实际返回的是政策错误而不是替身异常。
- [x] RED：真实子进程执行 run_evaluation 的 validate/grade/run，加载 source_kind=opensource 的自有 manifest；必须 exit 2，stderr 明确指向不支持路径，不能产生输出或要求先设置 API Key。
- [x] 运行 python -m pytest tests/test_opensource_execution_policy.py -q -p no:cacheprovider，观察现有代码允许宿主路径/先读凭据等失败。
- [x] GREEN：政策检查位于 public 函数最前面、输出目录创建和外部操作之前；CLI 在确定 cases 后处理 run 拒绝。host 检查放在 grade_patch 和 validate_case，不能只拦 CLI。
- [x] 运行新增测试 + test_evaluation_cli.py、test_evaluation_grading.py、test_evaluation_experiment.py。Review 的 synthetic wrapper 保持兼容。

关键测试：

```python
def test_host_preflight_refuses_opensource_before_subprocess(tmp_path, monkeypatch):
    from dataclasses import replace
    from benchmarks.evaluation import grading
    from benchmarks.evaluation.cases import load_cases
    case = replace(load_cases(make_case(tmp_path / "bank"))[0], source_kind="opensource")
    def forbidden(*args, **kwargs):
        raise AssertionError("host execution must not start")
    monkeypatch.setattr(grading, "run_tests", forbidden)
    with pytest.raises(ValueError, match="opensource"):
        grading.validate_case(case, tmp_path / "validation")
    assert not (tmp_path / "validation").exists()
```

## Task 3：固定来源、组装公开/私有任务包

**Files:** Create evaluation/opensource_assets.py、benchmarks/opensource_sources.json、
evaluation/opensource_overlays.py、prepare_opensource_cases.py、tests/test_opensource_assets.py、
tests/test_opensource_assembly.py、tests/test_opensource_prepare_cli.py、tests/test_opensource_dataset.py；
Add manifest_opensource_v1.json、eval_cases/opensource_v1/、eval_private/opensource_v1/；
Modify .gitignore。

**Interfaces:**

```python
def verify_source_files(files: dict[str, bytes], git_tree: dict) -> dict:
    """Validate every regular blob's Git SHA-1 (blob header + bytes), path and mode."""
def prepare_source(case_id: str, output: Path) -> dict:
    """Fetch only fixed registered GitHub commits and verify source without execution."""
def assemble_case(case_id: str, source: Path, fixed: Path, destination: Path) -> Path:
    """Build a new immutable draft task manifest; never run validation here."""
```

`destination` 是可已存在的 benchmarks 根目录；只允许创建此前不存在的新 case 目录和清单，不覆盖旧任务。独立清单与统一清单都只声明准备完成。

- [x] RED：用本地小仓库字节表及手工 Git blob header 摘要校验正常文件、丢失、增加、错误 blob、symlink mode、截断 tree、错误 commit。HTTP 替身仅替换网络边界，真实路径/摘要逻辑仍执行。
- [x] GREEN：固定注册两题、repo、buggy/fixed SHA 和允许生产文件；构造 api.github.com / codeload.github.com URL，不采用响应中的任意外链。拒绝非白名单重定向，下载流限量，明确超时，不自动换源。
- [x] RED：source/private/description 不得相互覆盖；已存在目标拒绝；私有测试和来源元数据不得复制进 buggy；许可字节保留。普通 pytest collect 不得发现外部资产节点。
- [x] GREEN：下载缓存先加入 Git ignore，原样保存源树，记录排除文件；为每题增添公开复现和私有隐藏测试。只用 difflib 生成现有白名单生产文件的 plain unified diff。
- [x] more-itertools wrong：上游恢复 peeked 的语句仅在其为真时执行，修改 anchor 必须唯一；boltons wrong：只保留 dictutils 生产 hunk。将 artificial_mutant 来源写入元数据。
- [x] 每个测试直接调用公开 API：more 用 seekable([10,20,30],maxlen=0)；隐藏参数 [0,False,None,""] 及空/交错；boltons 用 OMD 与 QueryParamDict 的 getlist/get/keys/items/to_text；不按补丁字符串判正确。已编写，尚未执行。
- [x] 用 ast.parse 做语法及节点名预检查，不 import 上游。manifest F2P/P2P 先声明已编写测试节点，实际冻结标记留在 Task 7 容器校准完成时。
- [x] 自有单测通过后，显式调用 prepare CLI 获取这两个已批准公共来源；打印仅 source_verified/assets_prepared，不打印 offline_validated。没有 Docker 时到此仍可交付任务包。

生产摘要计算核心：

```python
header = b"blob " + str(len(content)).encode("ascii") + b"\0"
blob_id = hashlib.sha1(header + content).hexdigest()
if blob_id != expected_blob_id:
    raise ValueError("upstream blob mismatch")
```

隐藏测试示例（完整测试覆盖设计第 5 节）：

```python
@pytest.mark.parametrize("head", [0, False, None, ""])
def test_zero_cache_peek_preserves_falsey_value(head):
    stream = seekable([head, "tail"], maxlen=0)
    assert stream.peek() == head
    assert bool(stream) is True
    assert list(stream) == [head, "tail"]
    assert list(stream.elements()) == []
```

## Task 4：容器协议和实际副本完整性

**Files:** Create evaluation/container_protocol.py、container_entry.py、
tests/test_container_protocol.py、tests/test_container_entry.py；
Modify evaluation/pytest_probe.py，新增 tests/test_evaluation_probe.py。

**Interfaces:**

```python
def input_inventory(root: Path, explicit_paths: tuple[str, ...]) -> dict[str, str]: ...
def validate_stage_result(result: dict, expected: dict) -> dict: ...
def run_stage(request: dict, input_root: Path, work_root: Path, output_root: Path) -> int: ...
```

上述签名描述接口，不在实现中保留省略体。协议字段固定为 version/run_id/stage_id/input_hash/environment_hash/paths/required/timeout；输出含 pytest_returncode、probe、integrity。拒绝未知路径和重复 ID，显式路径单独摘要，即使在通用忽略目录下。

- [x] RED：完整性检查必须捕获输入缺失、内容改变、链接替换、新增业务文件、显式 hidden_tests/venv 文件变动；过去通用忽略规则不能吞掉显式测试。
- [x] GREEN：先校验复制后的输入清单，再运行自有测试子进程，前后摘要对比；只允许声明的缓存/内部输出，输出独立到 output_root。实现采用 -B/no:cacheprovider，不忽略工作副本中的任何文件变化。
- [x] RED：旧 probe 无异常类型仍可读取；新 opensource F2P 要求 call 阶段 AssertionError。对自有 assert False 与 import 不存在模块的测试保存不同异常类。已输出 assertion_failures；真实任务与该证据的绑定仍由任务 6–7 完成。
- [x] GREEN：用 pytest_runtest_makereport hook 获取异常类型，仅增加可选字段；生产捕获插件不改。JSON 数据类型、节点、退出码、ID/摘要和 integrity 缺失均 fail closed。
- [x] RED/GREEN：结果文件路径、普通文件类型、单文件/总量上限；无价值哨兵环境变量不传入；仓库同名 probe 不能遮蔽镜像内探针。
- [x] 只在自有小夹具上执行入口单测，绝不在宿主 import 真正上游。python -m pytest tests/test_container_protocol.py tests/test_container_entry.py tests/test_evaluation_probe.py -q。

任务 4 的数据布局、字段、退出码和可信边界见[容器协议说明](../../opensource-container-protocol.md)。输入/环境摘要只在本层绑定，不冒充 Docker 环境已核验；后续监督器必须同时验证容器状态、入口退出码和完整输出包。

## Task 5：Docker 后端及环境准备

**Files:** Create evaluation/docker_runner.py、evaluation/docker_environment.py、
benchmarks/docker/environment_probe.py、benchmarks/docker/Dockerfile、
benchmarks/docker/README.md、benchmarks/docker/requirements.lock、
tests/test_docker_runner.py、tests/test_docker_integration.py；
Modify pyproject.toml 仅添加显式 docker 标记和默认排除。

**Interfaces:**

```python
class DockerTestRunner:
    def __init__(self, environment_lock: Path): ...
    def __call__(self, repo: Path, paths: tuple[str, ...], output: Path,
                 timeout: int, required: tuple[str, ...] = ()) -> dict: ...
def prepare_environment(output: Path) -> dict: ...
def check_environment(lock: Path, output: Path) -> dict: ...
```

2026-10-21 实施组织细化：生命周期与锁检查保留在 docker_runner.py，prepare/check 实现放入 docker_environment.py，自有环境探针放入 benchmarks/docker/environment_probe.py；runner 保留上述公开接口。两个新增文件须纳入对应测试及可信文件清单，避免把生命周期、构建与探针堆入一个大模块；功能和权限边界不变。

- [x] RED：假外部进程边界验证实际生成的参数数组包含 design profile，且输入 staging 为 readonly、输出为空专属目录；禁止 shell=True、--privileged、host network/PID、socket 挂载和宽目录挂载。图像必须使用锁定完整 image ID，不是 latest。
- [x] GREEN：Docker run/create 使用受控参数数组，环境白名单；同一唯一容器 ID 完成 inspect/start/wait/stop/remove，任何一步失败不得改为 host 或重试外部测试。
- [x] RED：模拟 timeout/KeyboardInterrupt、daemon 失败、OOM、输出超限；必须中止已记录容器，不做 prune；验证没有存在任何 started 容器却被遗漏的错误分支。首轮独立审查发现回收预算遗漏，已补指定ID删除预算及反例并复审；任意调度超时仍有现实限制，见日志。
- [x] GREEN：每秒检查输出8文件/64MiB总限，日志16MiB；等待最多阶段timeout，回收限30秒；停止后验证普通输出文件与完整协议再映射 run_tests 语义。
- [x] 依赖锁通过官方元数据核对版本与 wheel SHA-256 后生成；Dockerfile 仅复制可信入口/探针/锁文件。不把整个项目设为 context，不执行上游 setup/build。
- [x] Docker Desktop/WSL安装、人工重启后验证本地Linux/amd64引擎；固定官方基础digest并显式构建，保存image ID、versions、harness hash与profile。子测试修复后新建镜像/锁，不修改旧锁。
- [x] 自有真实容器探针验证只读、非 root、无哨兵凭据、禁外网/仅loopback、Seccomp2、资源 inspect、已启动容器超时停止/移除；全部满足后写 environment_verified。
- [x] docker_runner定向最终83项通过；修复后真实镜像显式Docker集成1passed（3.30秒），未把deselected算成功。

## Task 6：贯穿 grader 的 Docker 后端与 CLI

**Files:** Modify grading.py、execution_policy.py、run_evaluation.py；
Add tests/test_opensource_grading.py，扩展 tests/test_opensource_execution_policy.py。

**Interfaces:** validate_case(case, output, *, test_runner=run_tests) -> dict；grade_patch 保留现有接口。execution_policy 对 opensource 只接受验证完成的 DockerTestRunner 实例，不能用 is_sandbox 字段伪造。synthetic 的旧任意自有 test_runner wrapper 继续允许。

- [x] RED：将自有 synthetic case 传入记录调用参数的受控 runner，要求 baseline/reference/mutant 全部使用同一 runner。这个替身只替换外部进程，实际复制/补丁/判分均保留。
- [x] GREEN：validate_case 将 runner 传入基线和两个 grade_patch；Docker 结果需要有效 integrity，后端报告环境失败不能被压成普通 hidden_failed。
- [x] RED：opensource 无后端、伪布尔后端、缺锁、锁与镜像不同全部拒绝；已核验 Docker 后端允许 validate/grade。create/run/resume 继续拒绝 opensource，不读取 API Key。
- [x] RED/GREEN：CLI validate/grade 的 --backend docker、--environment-lock 显式组合校验；默认 synthetic 不变，混合集合拒绝。validate/grade exit 0/1/2 分别对应成功/正常未通过/系统错误，混合优先2。
- [x] Docker 成功路径的离线边界夹具仅使用自有代码；旧 Review 自有 wrappers、旧报告重建和参数缺省都回归通过。真实Docker探针仍由任务5/7实际验收。
- [x] 覆盖套件包含在最终完整离线回归中：665passed、2deselected、exit0；定向RED/GREEN与独立复审见工程日志步骤39。

## Task 7：两题真实离线校准与交付

**Files:** 新 results/opensource/<unique-id>/；docs/opensource-pilot-offline.md、工程日志、本计划；README 只在事实成立后追加链接。

- [x] 来源/环境锁核验及实际上游导入范围静态预检已完成；网络问题与boltons反例问题保留原证据。
- [x] 在固定快照上实际执行两题baseline/gold/wrong；F2P/P2P节点与任务指纹、环境锁绑定，结果新目录保存。more保留r1；boltons仅追加r2，原v1失败不覆盖。
- [x] 两题最终均valid：baseline指定4个AssertionError，gold公开/隐藏全过，wrong公开过但隐藏业务断言失败。初次环境/反例错误不计模型成绩。
- [x] 10阶段/10不同容器；4公开阶段无hidden_tests输入目录；全部实际副本完整性与回收正常。
- [x] 最终684passed、2deselected、exit0；显式Docker1passed另列。Ruff检查25文件通过，相关9文件格式通过；2历史未改文件的格式差异保留说明。4,130保护摘要0差异，旧报告副本重建summary/Markdown逐字节一致。
- [x] 校准报告明确未覆盖load_tests注入的全部doctest、boltons非全仓回归；已读dev小补丁不是泛化证据。
- [x] 工程日志保存每步问题与修复；限定差异收尾独立复审无Critical/Important/Minor发现。没有新Repair/Review请求、仓库Git写入或发布。
- [x] 两题本次离线校准通过；不可变资产元数据仍保留原assets_prepared历史标记，最新offline_validated事实与运行指纹在报告/结果中另记。整个合理评测的后续工作仍见收尾检查表。

## 计划自查映射

| 设计要求 | 任务 |
| --- | --- |
| 固定来源、许可、归档限制、overlay、dev 标签 | 1、3 |
| 两题合同、公开/隐藏、gold/wrong、断言与回归范围 | 3、4、7 |
| Docker权限、网络、资源、输出与终止、镜像锁 | 4、5 |
| 三种验收后端一致、宿主和付费防绕过、默认兼容 | 2、6 |
| 输出证据、错误分类、旧资产不覆盖 | 0、4、6、7 |
| 无外部代码的自有测试与真实环境验证分开 | 全部 |

计划状态（2026-10-22最新）：开源离线试点任务0–7完成。修复后本机environment_verified、两题2/2 valid、684项离线回归和显式Docker集成通过；旧资产/失败/成绩保留，未启动真实模型或Git发布。详见[实际校准报告](../../opensource-pilot-offline.md)、工程日志步骤41和[整个评测的剩余工作](../../evaluation-completion-checklist.md)。本计划完成不等于Agent运行时容器适配或正式性能实验完成。
