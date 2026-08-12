# PyRepair Agent 2–3 分钟演示脚本

## 演示前准备

在项目根目录打开 PowerShell，安装开发依赖并设置只在当前终端有效的 API Key：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Set-Item -Path Env:DEEPSEEK_API_KEY -Value "你的 API Key"
```

不要录制或展示 API Key。开始录屏前清空终端，并确认 `examples/buggy_bank/bank.py` 仍包含故意的 `self.balance += amount`。

## 0:00–0:25：说明问题并展示失败

口述：

> 这是 PyRepair Agent。它不会直接修改项目，而是在临时副本中诊断一个 pytest 失败，生成候选补丁，再经过策略、独立审查和全量回归验证。

运行：

```powershell
python -m pytest examples/buggy_bank -q
```

指出 `test_withdraw_reduces_balance` 失败，而另外两个测试通过。

## 0:25–1:20：运行 PyRepair

```powershell
pyrepair fix --repo examples/buggy_bank --model deepseek-v4-flash
```

边等待边解释终端阶段：

- `baseline`：复现并解析 pytest 失败。
- `attempt:1`：Repair Agent 通过 5 个受限工具收集证据和修改临时副本。
- `policy`：确定性规则检查路径、补丁规模、测试绕过和断言弱化。
- `review`：全新上下文的只读 Agent 独立审查 Diff。
- `verify`：目标测试、全量测试和回归比较。

成功后终端会打印产物目录。选中最新一次运行：

```powershell
$runDir = Get-ChildItem examples/buggy_bank/.pyrepair/runs -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
$runDir.FullName
```

## 1:20–2:05：审计四类产物

查看候选补丁：

```powershell
Get-Content "$($runDir.FullName)/fix.patch"
```

指出补丁只把 `self.balance += amount` 改为 `self.balance -= amount`，没有修改测试。

查看结构化结果和模型轨迹：

```powershell
Get-Content "$($runDir.FullName)/report.json"
Get-Content "$($runDir.FullName)/trace.jsonl"
Get-Content "$($runDir.FullName)/pytest.log"
```

口述：

> `report.json` 记录每道安全门，`trace.jsonl` 记录角色、工具与 Token，`pytest.log` 保存真实测试证据。API Key 不会写入这些文件。

## 2:05–2:40：开发者手动应用并回归

先检查补丁是否能安全应用：

```powershell
git apply --check --directory=examples/buggy_bank "$($runDir.FullName)/fix.patch"
```

确认后由开发者手动应用：

```powershell
git apply --directory=examples/buggy_bank "$($runDir.FullName)/fix.patch"
python -m pytest examples/buggy_bank -q
```

展示 `3 passed`，并强调这是人工确认后的动作，PyRepair CLI 本身没有修改原仓库。

## 2:40–3:00：用实测数据收尾

口述：

> 我为项目建立了 15 个固定单 Bug benchmark。DeepSeek V4 Flash 的端到端成功率是 86.7%，首轮成功率 80%，没有新增回归或策略拒绝。两项失败来自 pytest 9 输出解析，失败也保留在原始 JSONL 中，没有为了凑分删除。

录屏结束后恢复故意 Bug，避免污染后续演示：

```powershell
git restore -- examples/buggy_bank/bank.py
Remove-Item Env:DEEPSEEK_API_KEY
```

## 面试追问的 20 秒回答

如果面试官问“和 Claude Code 这类通用 Agent 比有什么用”：

> Claude Code 是通用编程 Agent；PyRepair 刻意缩小到 pytest 自动修复，并把工具、路径、补丁大小、独立 Review 和全量回归做成可验证的安全边界。它的价值不是能力更广，而是结果可复现、失败可审计、适合接入本地 CLI 和手动 Actions。15 个固定任务的真实结果也让我能量化系统的有效范围和失败层级。

简历表述：

> 独立开发 PyRepair Agent：基于 DeepSeek V4 Tool Calling 构建 pytest 故障诊断与候选补丁闭环，通过临时工作区、确定性 Patch 策略、独立 Review 与全量回归限制高风险修改；建立 15 个真实 Bug 任务的可复现评测，Flash 端到端成功率 86.7%，首轮成功率 80%，0 新增回归。
