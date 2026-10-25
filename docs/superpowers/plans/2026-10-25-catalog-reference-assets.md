# 三十题固定源码和参考补丁 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 在已有 managed worktree 内直接执行；不启动模型，不再询问是否沿用已批准设计。

**Goal:** 为来源目录中的三十个候选保存按提交去重的、逐文件核验的源码与许可文件，并生成独立的生产参考补丁及可离线复核的证据。

**Architecture:** 来源缓存按 repository/commit 编址，复用现有安全 ZIP reader 和 Git blob 校验。每题只绑定原始 buggy/fixed 快照和仅含生产 Python 文件的参考补丁，仍不是公开/隐藏测试均已准备的 EvaluationCase。批次支持显式断点继续，只重用经重新校验的完整快照，失败记录保留。

**Tech Stack:** Python >=3.11、标准库、现有 `read_source_zip`/`verify_source_files`/`_source_patch`/安全路径检查；GitHub 受信HTTPS数据和 codeload 归档。

## Global Constraints

- 依据 [统一五十题方案](../specs/2026-10-25-unified-goldset50-design.md)，先建题后统一评测。
- 本单元不导入或执行上游源码，不运行上游测试、不启动Docker、不请求DeepSeek、不读取API Key。
- 生产Agent、pyproject、旧来源白名单、旧资产和旧成绩不修改。
- 固定来源必须来自 `opensource_catalog30.json`，修复提交完整父列表与第一父基线必须匹配；归档完整文件集须匹配Git tree与逐文件blob。
- 保留现有20MiB归档/展开总量、8MiB单文件、2000成员限制；不因某题不合格静默放宽。
- 目录无实际系统链接、拒绝覆写；暂存只创建在本批输出内，校验成功后发布新目录并最后写入完整性标记。失败保留本次run报告，不自动技术重试。
- 不把许可文件存在等同于分发合规已审查，不把参考补丁能生成等同于测试已经通过。
- 相同repo/commit只保存一次；新增版本不改旧目录，resume先重新检查已有内容，不靠source_verified字符串相信缓存。
- 用户于2026-10-25明确批准：仅内部文档链接作为元数据核验，不进入source，不跟随链接；旧严格读取器不改。新增`catalog_document_links.py`，文档归一化仅内存执行，生产/测试链接仍拒绝。

## Task 1: 固定提交源码缓存

**Files:** Create `benchmarks/evaluation/catalog_source_cache.py`; Test `tests/test_catalog_source_cache.py`.

**Interfaces:**

- `prepare_version(entry: dict, label: str, versions: Path, *, fetch=fetch_bytes) -> dict`：label只允许buggy/fixed；按受控来源条目得到repo和提交，创建经完整验证的缓存。返回 `{path, repository, commit, tree_sha, archive_sha256, files, licenses, status}`，path为版本目录。
- `verify_version(entry: dict, label: str, versions: Path) -> dict`：纯离线重验缓存元数据、ZIP摘要、源码Git blob与许可文件；任何不一致拒绝。
- `metadata_fetcher(root: Path) -> Callable[[str], bytes]`：仅将固定GitHub commit/tree GET映射为本地JSON镜像；归档仍由受限HTTPS fetch_bytes读取。镜像缺失时拒绝，不悄悄读凭据或回退到另一个认证方式。

- [x] **Step 1: 写源码永不执行、缺失实现的失败测试并观察RED。**

```python
def test_verified_archive_is_data_not_imported(tmp_path):
    assert importlib.util.find_spec("benchmarks.evaluation.catalog_source_cache") is not None
    from benchmarks.evaluation.catalog_source_cache import prepare_version
    entry, fetch = owned_source_fixture()
    result = prepare_version(entry, "buggy", tmp_path / "versions", fetch=fetch)
    assert result["status"] == "source_verified"
    assert (Path(result["path"]) / "source/src/demo/__init__.py").read_bytes().startswith(
        b"raise RuntimeError('must never import')"
    )
    assert not list(tmp_path.rglob("*.pyc"))
```

`owned_source_fixture()` 在测试文件定义：repo为owner/demo，buggy/fixed为40位a/b，按实际Git blob公式生成带LICENSE和sentinel源码的ZIP及commit/tree JSON；只替换外部网络返回字节，不替换真实ZIP和逐文件验证逻辑。

- [x] **Step 2: 加入定向反例。** 改提交SHA、tree SHA、源文件字节、第一父、许可文件、非法路径和未完成缓存；检查拒绝及无最终source目录发布。改已缓存源码、归档或commit元数据再离线复核，必须拒绝。镜像用真实小JSON文件，测试只读和缺文件拒绝。
- [x] **Step 3: 实现最小数据流程。**

```python
metadata = read_json_bytes(fetch(commit_url))
assert metadata["sha"] == pinned_commit
tree = read_json_bytes(fetch(tree_url))
payload = fetch(archive_url)
# 暂存目录只在受控versions父目录下新建，归档按现有限制读取。
files = read_source_zip(archive, expected_sha256=sha256(payload), root_prefix=expected_root)
evidence = verify_source_files(files, tree)
# 先检查许可与提交身份，再写源码；记录归档和元数据摘要。
```

代码中不用assert做输入验证，使用明确异常。根层LICENSE/COPYING文件保留原始字节并记录摘要；没有许可文件时失败而不是假定MIT。所有缓存重用均调用verify_version；不导入下载的模块。Windows目录rename间歇失败已用回归复现，实际发布采用校验后写完成标记，不依赖目录重命名；不完整目录仍拒绝复用。

- [x] **Step 4: 同一组测试GREEN，运行旧归档/来源验证回归。**
- [x] **Step 5: 与Task2/3组成自洽交付保存；不发布中间可误执行状态。**

## Task 2: 三十题参考补丁和批次恢复

**Files:** Create `benchmarks/evaluation/catalog_references.py`; Test `tests/test_catalog_references.py`.

**Interfaces:**

- `prepare_references(catalog: dict, output: Path, *, fetch=fetch_bytes, resume=False) -> dict`：校验来源目录，拒绝覆盖新批次；resume必须匹配原始catalog摘要并先验证旧版本/题目。生成每题`cases/<id>/gold.patch`和`reference.json`，最后给出source/reference状态，不授予模型执行权限。
- `verify_references(catalog: dict, output: Path) -> dict`：不联网，重新校验去重缓存和每题参考补丁，返回计数；缺失或篡改必须失败。

- [x] **Step 1: 写失败测试。**

```python
def test_reference_preparation_still_requires_calibration(tmp_path):
    from benchmarks.evaluation.catalog_references import prepare_references
    catalog, fetch = owned_catalog_fixture()
    result = prepare_references(catalog, tmp_path / "batch", fetch=fetch)
    assert result["reference_count"] == 1
    assert result["ready_for_model_evaluation"] is False
    assert result["calibration_status"] == "not_run"
```

先以缺模块断言确认RED。owned_catalog_fixture按已实现source_catalog契约构造一个实际受控repo条目，并复用源码网络字节fixture。

- [x] **Step 2: 测试参考补丁只改声明的生产文件。** 独立比较buggy/fixed快照的包内Python差异与reference_source_paths，不将上游tests/CHANGES改动带入gold.patch。新增/删除生产文件或参考路径遗漏时拒绝，而不是静默丢失部分修复。
- [x] **Step 3: 实现新批次/显式resume/离线verify。** 批次identity绑定规范JSON摘要；写入记录用独占创建或唯一run目录，旧失败report不覆盖。启动前取得本批writer锁，结束只删除自己创建的锁。身份变化、损坏缓存或状态不明锁拒绝；正常resume只准备不存在的版本/题目，不重发已成功下载。
- [x] **Step 4: 观察GREEN并测试源错误后恢复、catalog变化拒绝、旧补丁篡改拒绝。** 不通过删除旧失败或改参考路径来使测试通过。
- [x] **Step 5: 完成本单元的静态参考补丁证据，校准状态仍明确not_run。**

## Task 3: 源码准备CLI、真实来源与记录

**Files:** Create `benchmarks/prepare_catalog_references.py`, `docs/opensource-reference-preparation.md`; extend工程日志。

**Interface:** CLI接受`--catalog`、必需的`--output`、可选`--metadata`、`--resume`和`--verify-only`，无模型参数、无宿主执行命令入口。成功退出0；错误退出2并保留run evidence。verify-only不联网也不写准备记录。

- [x] **Step 1: CLI测试RED后实现main。** 复用旧脚本的本worktree import bootstrap，不依赖宿主已安装同名上游库；输入错误在key访问前失败（本CLI完全不读key）。
- [x] **Step 2: 用已连接GitHub只读接口准备固定commit/tree JSON镜像。** 镜像只作数据，完整源文件集在ZIP对Git tree时再核验；将JSON内容由apply_patch保存，不写认证信息。API元数据与codeload归档的来源URL留证；不将连接器访问当成签名证明。
- [x] **Step 3: 执行真实三十题源码与参考补丁准备。** 输出到项目tmp内全新、明确命名的目录；同repo/commit去重。网络技术错误停止，已准备数据和失败报告保留；不调用模型，不在宿主或Docker运行上游代码。
- [x] **Step 4: 运行独立离线verify与定向测试、Ruff、生产源码冻结检查，记录实际完成数和遗留。**

```powershell
python -m pytest tests/test_catalog_source_cache.py tests/test_catalog_references.py tests/test_source_catalog.py tests/test_opensource_archive.py tests/test_opensource_assets.py -q -p no:cacheprovider --maxfail=1
python -m ruff check --no-cache benchmarks/evaluation/catalog_source_cache.py benchmarks/evaluation/catalog_references.py benchmarks/prepare_catalog_references.py tests/test_catalog_source_cache.py tests/test_catalog_references.py
git diff 7c9508e63ff3a133e7599b3a2ca439e935f10295 -- src/pyrepair pyproject.toml
```

测试子进程移除DEEPSEEK_API_KEY，使用项目tmp下独立PYTEST_DEBUG_TEMPROOT；不改ACL。源码缓存和原始run evidence保留本地，不默认提交仓库；只提交工具、测试、计划和可追溯汇总。

## 自查及后续

本单元不准备公开复现、隐藏测试或不完整补丁，也不证明参考修复通过测试；这些是下一实施单元。先拿到真实源码和差异证据，再按每题行为确定覆盖层，避免在未读代码时编造验收。三个组件接口已定义；失败和resume不会覆盖旧报告；没有改变已批准的先建全集后评测顺序。

实施结果：三十份参考/五十五个源码版本准备完成；独立离线复核及三十份Git应用预检通过。首轮文档链接失败报告保留，批准后继续；226项定向测试通过。详见 [准备记录](../../opensource-reference-preparation.md)。代码/测试新增和用户批准的文档链接政策作为同一自洽单元提交。
