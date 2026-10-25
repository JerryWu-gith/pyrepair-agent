# 容器执行层：协议与内部入口

日期：2026-10-20。当前完成的是实施计划任务 4 的代码与自编夹具测试，**不是 Docker 集成验证**。两道真实上游任务仍停留在 `assets_prepared`，没有执行上游 Python，没有模型调用。

## 1. 这一层解决什么

仅有 pytest 退出码不能证明一次验收可信：测试可能在准备阶段报错，文件可能在运行时被改动，也可能误读上一轮的结果。这一层同时检查身份、测试证据和实际执行副本。

```text
后续 Docker 调度器（任务 5–6，尚未接通）
    │ request：本次身份、测试路径、必需节点、输入/环境摘要
    │ inventory：逐文件摘要；repo：本阶段允许挂载的文件
    ▼
/input（未来只读挂载）
    │ 核对输入清单与摘要
    ▼
/work（未来容器内临时文件系统）
    │ 全量复制后再次核对
    │ 固定入口预加载可信 pytest 探针
    │ 执行指定测试
    │ 重新记录实际工作目录全部文件摘要
    ▼
/output（本次空目录，未来单独挂载）
    │ result.json + probe.json + integrity.json + pytest.log
    ▼
校验身份、输出类型/体积、证据一致性、文件变化、节点及阶段结果
    └─ passed / failed / patch_rejected / grader_error
```

目前内部入口在宿主的测试仅使用本项目手写的小夹具。**入口本身不提供网络或操作系统隔离，不能拿来直接运行上游仓库。** opensource 的现有 host/live 入口保护没有放开。

## 2. 输入各是什么

`/input` 约定保存 `request.json`、`inventory.json` 和 `repo/`；公开阶段不能包含私有测试、参考补丁或完整评测私有目录。挂载、环境锁实测和每阶段新容器由后续后端负责。

| 请求字段 | 具体作用 |
| --- | --- |
| `version` | 当前协议版本，整数 1，布尔值不能冒充整数 |
| `run_id` / `stage_id` | 关联本次运行与阶段，结果必须原样匹配；后续调度器负责生成每次唯一 ID |
| `input_hash` | `inventory.json` 按固定 JSON 编码得到的 SHA-256；不是仅对目录名做摘要 |
| `environment_hash` | 绑定后续环境锁的摘要；本层只检查格式和回传一致性，不证明镜像已验证 |
| `paths` | 本阶段明确执行的相对测试文件路径；禁止越界、绝对路径、命令选项及重复条目 |
| `required` | 必须出现的 pytest 节点，例如 `tests/test_x.py::test_owned`；必须属于 paths |
| `timeout` | 本阶段测试时限，正整数且不超过 120 秒 |

清单是“相对文件名 → SHA-256”的字典。上层负责构建干净 staging；本层**不再套用通用忽略规则**。因此，显式测试即使位于 `venv/` 之类的目录也会被核验，不会静默漏掉。

所有输入文件必须保持不变。正常字节码和 pytest 缓存写入通过 `-B` 与关闭 cacheprovider 禁止；内部输出位于单独输出目录，没有为业务文件新增宽泛忽略项。

## 3. 判定结果

| 情形 | 结果 |
| --- | --- |
| 所有实际节点通过、required 全出现、文件不变、输出完整且身份匹配 | `passed` |
| 正常执行但有调用阶段失败、跳过或 xfail | 不通过；不会把跳过算成功 |
| pytest 全绿，但工作目录文件新增、删除或改变 | `patch_rejected` |
| 收集/准备/收尾异常、缺必需节点、证据缺失、身份或退出码矛盾 | `grader_error` 或协议拒绝 |
| 超时、输入不匹配、启动/输出错误 | 内部入口退出 2，保留可写入的错误证据，不生成成功结论 |

入口进程退出码为 0 / 1 / 2：0 表示本阶段通过；1 表示正常完成但测试或完整性未通过；2 表示运行/验收错误。后续 Docker runner 还必须核对容器状态和入口退出码，不能只读输出中的 pytest 返回码。

新探针在有异常的阶段增加 `exception_type`。协议只把**正常完成 setup/teardown 的 call 阶段 `AssertionError`**列入 `assertion_failures`；`ModuleNotFoundError`、setup 断言、缺失异常类别均不算该证据。旧 probe 没有此字段仍可读取。任务 6–7 将据此校准真实任务的 F2P，并人工核对具体断言合同；此处尚未完成真实标签验证。

## 4. 输出与拒绝规则

正常输出固定为四个文件：

- `pytest.log`：原始测试日志。
- `probe.json`：收集节点、阶段结果、异常类别及 pytest 返回码。
- `integrity.json`：实际工作副本 before / after 摘要及 unchanged。
- `result.json`：本次身份、pytest 返回码及上述两份结构化证据。

失败时可新增 `error.json`。它与正常结果同时出现也不构成成功输出；入口保存原文件并返回失败，不覆盖已有错误证据。无法写错误文件时仍返回 2，后续监督器必须尊重该退出码。

文件名采用白名单，拒绝目录、链接、硬链接及未知文件。单文件最多 16 MiB，总量最多 64 MiB，文件数量不得超过 8；实际白名单只有五个名称。读取 JSON 还会限制体积并拒绝重复键。结果中的 probe / integrity 必须与各自独立文件一致。

执行入口轮询输出大小并处理超时；真正 Docker 的内存/CPU/PID 限额、容器停止和输出目录监督尚待任务 5。轮询不等于硬磁盘配额。

## 5. 代码与检查

| 文件 | 职责 |
| --- | --- |
| [container_protocol.py](../benchmarks/evaluation/container_protocol.py) | 独立标准库协议、文件摘要、身份/结果/输出校验 |
| [container_entry.py](../benchmarks/evaluation/container_entry.py) | 内部复制、执行、超时处理、前后完整性与产物 |
| [pytest_probe.py](../benchmarks/evaluation/pytest_probe.py) | 评测专用异常类别；没有改生产捕获插件 |
| [协议测试](../tests/test_container_protocol.py) | 身份、节点、阶段、完整性、输出及 JSON 边界 |
| [入口测试](../tests/test_container_entry.py) | 真实子进程跑自编样例，验证复制、凭据剔除、变更拒绝、超时和冲突输出 |
| [探针测试](../tests/test_evaluation_probe.py) | 区分 call 断言与 setup 导入错误，兼容旧记录 |

审查遵循用户选择的 Inline，不使用子代理。先观察缺失功能或错误行为导致的失败，再实现或修复。完整自有回归实际 **574 passed、1 deselected，333.26 秒**；随后只收紧测试断言，相关三个测试文件再次 **64 passed，5.58 秒**，均退出 0。具体发现及修复见[工程日志](evaluation-v2-engineering-log.md)步骤 36。这不是 Docker 或上游任务通过数。

可信边界不变：这些检查不能防止同一容器中的恶意 Python 篡改自身证据，也不能发现“改完再恢复”。本阶段只计划执行已审查的上游基线、参考补丁和人工反例，不执行模型补丁。Docker 安全参数必须通过真实探针后才能标 `environment_verified`。
