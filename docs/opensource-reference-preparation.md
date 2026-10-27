# 三十题固定源码与参考补丁准备记录

> 2026-10-27 最新状态：统一 50 题、双方法各三次的 300 次运行已完成，见[正式结果与限制](goldset50-results.md)。以下保留 2026-10-25 的历史准备记录；“尚未校准”“尚未评测”及当时的 readiness 字段不是当前进度。

日期：2026-10-25。**30道来源的源码与参考补丁已准备，尚未完成任务行为校准，不是模型成绩报告。**

依据 [统一五十题设计](superpowers/specs/2026-10-25-unified-goldset50-design.md) 和 [本单元计划](superpowers/plans/2026-10-25-catalog-reference-assets.md)。来源仍为 [同一三十题目录](opensource-catalog30.md)，没有因模型表现更换题目。

## 1. 当前完成情况

| 项目 | 实际结果 |
| --- | --- |
| 固定来源及参考补丁 | 30/30 |
| 去重后的仓库/提交版本 | 55 |
| 普通文件快照 | 跨55个版本共6044个文件，55,400,734字节；不是独立代码文件数或性能指标 |
| 文档链接元数据 | 跨版本44条；实际source中不创建这些链接 |
| 原许可字节 | 7份不同内容，随各自固定版本保存并核验摘要 |
| 独立离线重验 | 30份参考记录、55份来源版本通过，未联网补下载 |
| Git补丁应用预检 | 30/30通过`git apply --check --no-index`；不改源码、不执行代码 |
| 自有工具定向测试 | 226 passed，0 failed，0 errors |
| 新模型调用 / 上游代码执行 | 0 / 0 |

三十题包括已有两道dev和二十八个新增候选。许可文件存在及字节相符不等于分发义务已经审查通过；此阶段没有发布这些源码。参考补丁可以应用，也不等于测试会通过。

## 2. 哪些工作还没做

新增任务的公开复现、隐藏边界、原有行为回归范围和人工不完整补丁尚未全部编写；三十题尚未在Docker中逐题完成缺陷/参考/不完整补丁校准。本单元没有新运行上游测试、安装上游依赖、构建容器或请求DeepSeek。

`references_prepared`只表示来源与生产参考补丁准备完成。输出仍明确：

```json
{
  "reference_count": 30,
  "unique_version_count": 55,
  "calibration_status": "not_run",
  "ready_for_model_evaluation": false,
  "model_calls": 0,
  "upstream_code_executed": false
}
```

## 3. 本地证据在哪里

根目录：`D:/Project/PyRepair Agent/tmp/catalog30-reference-20261025-2c26859/`。这些是本地临时证据，不是GitHub下载链接，不自动随工具提交。

| 相对路径 | 内容 |
| --- | --- |
| `metadata/<owner>/<repo>/commits/<sha>.json` | 固定提交及父版本元数据；通过已连接GitHub只读接口获取，不含认证信息 |
| `metadata/<owner>/<repo>/trees/<sha>.json` | 完整Git tree元数据 |
| `output/catalog.json` | 本批固定目录，规范JSON身份摘要为`124ea139447523fe1b4836bde9c3a82f176a4db11ef3ada93b29e0bfb56ae3e4` |
| `output/versions/<owner>/<repo>/<commit>/` | 原始ZIP、commit/tree、普通文件source及最后写入的version.json完整性标记 |
| `output/cases/<case-id>/gold.patch` | 仅含生产Python文件的参考补丁，不包含上游测试变更 |
| `output/cases/<case-id>/reference.json` | 来源绑定、参考补丁摘要、许可摘要及未校准状态 |
| `output/runs/<run-id>/report.json` | 首轮失败及继续准备的独立记录；不覆盖旧报告 |
| `preparation-source-hashes.json` / `resume-receipt.json` | 初轮和继续准备使用的工具摘要及旧失败报告摘要 |

首次准备在22题后被文档链接安全规则拒绝；用户批准受限处理后，继续时先离线重验并复用完整缓存，再准备其余题目。原失败报告SHA仍是`0c325128403482635f7eb99d8c02059a3bf4524a7405dd04ba03e49ec5f9e600`，没有删除或改写。控制目录现在有两份run报告。首轮失败的暂存ZIP未另存为永久归档，不声称已保留该ZIP；固定树信息、错误和工具摘要仍在。

## 4. 文档链接的受限处理

2026-10-25用户明确批准保留python-dotenv六题，只把文档链接作为元数据核验，不创建或跟随链接。实际出现四种路径：`docs/changelog.md`、`docs/contributing.md`、`docs/index.md`、`docs/license.md`，分别指向仓库根的CHANGELOG、CONTRIBUTING、README和LICENSE。

新适配器仅允许`docs/`中的md/rst/txt链接，目标必须解析到仓库内部的普通文档；生产目录、测试目录、绝对路径、越界目标、缺失目标、链接链和非法目标编码均拒绝。归档S_IFLNK与Git的120000模式交叉核验，原目标字节参与Git blob和SHA-256检查；链接元数据记录原mode、目标、摘要和`materialized=false`。

原始ZIP和原Git tree保留。为复用原安全检查，只在内存中将已批准的文档链接视作普通元数据条目，仍执行原路径、冲突、文件类型和资源上限检查。随后这些链接不进入实际source。新的只读离线复核不写暂存目录。旧`opensource_archive.py`及旧两题入口仍按原规则拒绝链接，没有被放宽。

这不是完整文件系统镜像：所有普通文件字节被核验，文档链接单独留证、明确排除，不能称为运行副本保留了上游全部文件系统语义。后续任务覆盖层须继承这份排除记录。

## 5. Windows发布与补丁格式边界

Windows目录重命名出现间歇性WinError 5；同一问题在不同权限和较短路径下均出现，具体锁定进程未确认，未归因于某个安全软件。改为新目录独占创建，内容验证后最后写完成标记。没有标记或证据不符的目录不作为完整缓存复用；不自动删除不完整目录，也不自动更改ACL或所有者。

只读审查发现旧参考Diff辅助函数可能漏掉源文件末尾缺换行标记。新准备入口补齐标准EOF标记，并有具体反例回归；旧辅助函数未改。已经准备的实际22题未发现该输入，最终30份补丁全部通过独立Git应用预检。

## 6. 复核命令与下一步

在当前worktree执行：

```powershell
& 'D:/Project/PyRepair Agent/.venv/Scripts/python.exe' benchmarks/prepare_catalog_references.py `
  --output 'D:/Project/PyRepair Agent/tmp/catalog30-reference-20261025-2c26859/output' `
  --verify-only
```

只读复核无模型、网络和准备写入。新准备或显式继续分别使用`--metadata`及`--resume`；没有`--model`或运行上游代码的参数。

下一步基于真实源码编写公开任务、公开复现、隐藏验收和不完整补丁，再接入src布局与固定Docker环境逐题校准。三十道开源题完成后补两道自建题，五十题全部验收与冻结后才做统一DeepSeek评测。Agent、pyproject、旧任务和历史成绩仍不改。

2026-10-26 后续进展：上述三十题资产及离线校准已完成，见[任务验收记录](opensource-task-calibration.md)。本文件保留来源准备阶段的原始证据口径，未将来源准备追改为模型性能结论。
