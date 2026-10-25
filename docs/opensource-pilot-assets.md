# 真实开源缺陷试点：任务包准备记录

本页保留 2026-10-20 的 **assets_prepared（任务包准备）** 检查点，不是最新执行结果。

2026-10-22 更新：more-itertools r1 与追加的 boltons r2 已通过实际 Docker 离线校准；r1 失败与旧资产保留。最新环境、验收矩阵、工程回归与局限见 [离线校准报告](opensource-pilot-offline.md)。以下“未运行/未安装”等描述仅指当日准备检查点，不代表当前状态。

本页当日不是 Agent 性能报告，也不是两题已复现的证明。当时没有执行上游 Python、启动 Docker 或调用模型；公开复现与隐藏测试只经过语法和静态节点检查。

## 1. 现在多了什么

原有 18 道自建任务和旧成绩保持独立。本轮新增两道固定上游提交的任务，完整保存缺陷版本的原仓库文件，并额外添加公开复现。参考补丁、人工漏修补丁和隐藏测试放在独立评测目录，不混入公开源码。

| 任务 | 固定缺陷版本文件数 | 补丁范围 | 新编写测试节点 | 当前能确认的事实 |
| --- | ---: | --- | --- | --- |
| more-itertools / seekable | 39 | `more_itertools/more.py` | 4 个声明 F2P、3 个声明 P2P | 文件逐个匹配固定 Git blob；两份补丁能应用 |
| boltons / addlist | 112 | `boltons/dictutils.py`、`boltons/urlutils.py` | 4 个声明 F2P、2 个声明 P2P | 文件逐个匹配固定 Git blob；参考补丁改两文件，漏修反例只改一文件 |

文件数不含额外公开复现，因此公开 buggy 目录分别为 40 和 113 个文件。参考修复版本也分别有 39 和 112 个文件，保存在本地来源缓存中；两种版本都保留原始 LICENSE 字节。

F2P 表示“预期原版失败、修复后通过”；P2P 表示“预期修复前后都通过”。上表数字是编写并静态核对的节点数，不是运行通过数，也不包括原有上游回归测试。节点状态仍为 `declared_not_collected`，实际收集和断言验证要在容器内完成。

## 2. 从来源到任务的证据链

```text
注册表中的固定仓库 / buggy SHA / fixed SHA
  → 核对提交身份、修复提交第一父提交和 Git tree
  → 限量下载 ZIP，核对安全路径与完整文件集合
  → 每个文件匹配 Git blob，保存 SHA-256、大小和原许可
  → 完整 buggy 快照 + 公开说明 / 公开复现
  → 独立隐藏测试 + 上游生产参考补丁 + 人工漏修反例
  → 结构检查、AST 检查、临时副本中的补丁应用检查
  → assets_prepared
```

网络来源限于 GitHub API 与 codeload 的 HTTPS 地址，记录固定提交与归档摘要。这是依据受信任 HTTPS 来源建立的可追溯性，不是签名证明；没有声称抵抗被攻陷的 GitHub 服务。

参考补丁只提取上游生产文件的修改，不夹带上游测试改动。more-itertools 的反例只对真值元素恢复 peek 缓存；boltons 的反例只修 dictutils，留下 urlutils。反例来源明确为人工构造，并非模型生成结果。它们能否“公开通过、隐藏失败”，尚待实际校准。

## 3. 文件在哪里

以下链接相对于当前独立工作区，不代表已经上传 GitHub。

| 文件 / 目录 | 用途 |
| --- | --- |
| [固定来源注册表](../benchmarks/opensource_sources.json) | 仓库、固定提交、许可、生产文件白名单及原测试范围 |
| [两题统一清单](../benchmarks/manifest_opensource_v1.json) | `opensource / capability / dev`，公开与私有路径、声明节点 |
| [more-itertools 公开任务](../benchmarks/eval_cases/opensource_v1/os_more_seekable_1269/TASK.md) | 正常行为要求，旁边的 buggy 是完整缺陷快照及公开复现 |
| [boltons 公开任务](../benchmarks/eval_cases/opensource_v1/os_boltons_addlist_458/TASK.md) | 容器及 URL 参数接口的一致性要求 |
| [more-itertools 来源与覆盖层证据](../benchmarks/eval_private/opensource_v1/os_more_seekable_1269/source-verification.json) | 原文件和 overlay 摘要，旁边保存隐藏测试及 gold/wrong 补丁 |
| [boltons 来源与覆盖层证据](../benchmarks/eval_private/opensource_v1/os_boltons_addlist_458/source-verification.json) | 两文件来源及测试层证据 |
| [准备入口](../benchmarks/prepare_opensource_cases.py) | 仅下载、核验、组装；不会跑上游测试或模型 |
| [静态数据集测试](../tests/test_opensource_dataset.py) | 核对实际资产、许可、节点和补丁应用，不导入上游 |

每题还生成独立的 `manifest_os_more_seekable_1269.json` / `manifest_os_boltons_addlist_458.json`。统一清单合并相同任务记录，不代表额外题目。

本地原始证据在 `benchmarks/results/opensource/`，已加入 Git 忽略：

- `source-pilot-20261020-01/`：more-itertools 核验成功；boltons 下载读取超时，整体为 `preparation_error`。失败保留。
- `source-pilot-20261020-02/`：复用并重新核验首轮 more-itertools 缓存，在新目录重新获取 boltons；两题组装成功，整体为 `assets_prepared`。

准备入口拒绝覆盖已有任务目录、清单与准备摘要。不要在旧结果路径重复运行命令来“续跑”；需要新缓存、输出位置和明确记录。`--assemble-only` 只跳过网络，仍重新核验缓存内容。

## 4. 已验证与尚未验证

| 层次 | 当前状态 |
| --- | --- |
| 固定来源、完整文件集合、内容摘要、许可 | 已验证 |
| 公开 / 隐藏 / gold / wrong 目录分离 | 已验证 |
| 补丁在临时副本可应用，gold 生产字节与上游固定版本一致 | 已验证；没有执行这些源码 |
| 普通项目测试排除外部资产 | 用自编哨兵文件验证；完整回归只收集项目 `tests/` |
| 宿主 / 付费入口遇到 opensource 默认拒绝 | 自有测试已验证；不是全系统安全沙盒 |
| Docker 镜像、资源 / 网络 / 权限隔离 | 尚未实现并实测；本机未检测到 Docker 命令和常见安装路径 |
| baseline 业务断言失败、gold 全通过、wrong 隐藏失败 | 未运行 |
| 新任务的模型修复率、耗时、成本、重复表现 | 未测量；本轮模型请求为 0 |

任务包准备检查点的来源读取与组装等相关自有检查共 122 项，包含在当时完整回归的 **510 passed、1 deselected（289.39 秒，退出 0）** 中；详见[步骤 35](evaluation-v2-engineering-log.md#35固定来源任务包组装与静态验收)。后续容器协议阶段的最新工程回归为 574 passed、1 deselected，见步骤 36。工程测试数量不计为模型答题成绩，未执行上游测试。

## 5. 下一道验收关卡

容器协议与内部入口已完成自编夹具验证，见[协议说明](opensource-container-protocol.md)；尚未接通 Docker 执行适配和 grader。在可用 Docker 环境下，先用自编小探针验证隔离与退出回收，再运行两题的原版、参考修复和人工漏修版本。禁止因为 Docker 不可用而退回宿主执行上游 Python。

验收需要同时满足：

1. 原版的指定 F2P 节点确实因业务断言失败，而非收集错误、缺依赖或超时。
2. gold 在指定公开、隐藏和回归范围全部通过。
3. wrong 通过公开测试，但被隐藏业务断言拒绝。
4. 测试前后实际运行副本、节点及输出身份完整，环境证据可核验。

more-itertools 计划执行 `tests/test_more.py`、`tests/test_recipes.py` 和新增复现；不宣称包括 unittest `load_tests` 注入的全部 doctest。boltons 只执行 dictutils/urlutils 相关回归，不称全仓回归。

两题已被开发者阅读，是 dev 试点；真实来源不等于大型复杂任务，也不等于未见留出集。当前不修改主 Agent 源码，不提交、合并、推送或创建 PR。Docker/WSL 安装与后续付费运行均不在本轮操作范围内。
