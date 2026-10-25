# 合成修复评测精度升级：离线校准

日期：2026-10-22。新集合`benchmarks/manifest_synthetic_v3.json`的18题已全部实际离线校准，18/18 valid，CLI退出0。**这是题包和评分器验收，不是新模型修复率；本轮API请求为0。**

## 改了什么

仍为原18道synthetic/dev任务，不新增任务，不改公开源码、公开测试或公开合同。其余17题metadata与任务指纹均保持相同；只有case_15升级为revision2，私有材料独立存放于`benchmarks/eval_private/synthetic_v3/case_15/`。

新隐藏验收逐字节复用已校准Review hard集合的六个金额×三种Decimal context精度（2/28/64），保留原契约与零值检查；新gold使用人工校准的`Decimal.as_integer_ratio`与整数运算，wrong沿用历史Decimal乘法候选。三份复制文件的来源/角色/SHA-256以及旧参考补丁身份记在`provenance.json`；不能把人工参考记作模型修复成果。

长金额本来就属于“非负、最多两位小数、精确转换为整数分”的公开契约；本次补齐验收，不增加非法输入、负数或额外未定义行为。

## case_15 实际校准矩阵

| 候选 | 公开测试 | 隐藏测试 | 结论 |
| --- | --- | --- | --- |
| 缺陷原版`int(float(value)) * 100` | 原金额小数断言失败 | 长金额及已有契约失败 | 22个节点中17失败、5通过；指定F2P/P2P符合声明 |
| 新人工校准gold | 2/2通过 | 20/20通过 | passed |
| Decimal乘法wrong | 2/2通过 | 6项精度断言失败、14通过 | hidden_failed |
| 旧版case_15 gold（额外诊断） | 2/2通过 | 同样6项精度断言失败 | hidden_failed；旧文件与旧成绩保留 |

例如金额`12345678901234567890123456789.01`应精确返回`1234567890123456789012345678901`分；受限Decimal context中的乘100并不保证精确。新验收会拒绝这类“公开示例通过、契约边界仍错”的候选。它提高验收区分力，不意味着Agent本身已经改善，也不保证覆盖契约的所有可能反例。

## 证据与版本

- 全18题校准目录：`benchmarks/results/v2/validate-synthetic-v3-20261022-7026d80d/`，包含汇总和逐题baseline/reference/mutant结果；全部`system_error=false`。
- 旧gold独立诊断目录：`benchmarks/results/v2/grade-synthetic-v3-legacy-gold-20261022-595839aa/`。CLI退出1表示正常未通过，不是系统错误。
- 新清单SHA-256：`ddfbfe10649ee74cb3cb12d058ec5e7c16d2fbff6bfdf78f53270b8ee802d008`。
- 新case_15任务指纹：`696a026ee635495e5ed4a1b05ffb94ffb30e75433c14cb64674021568b725e6b`。
- gold SHA-256：`776b27d788e838d0f2335166660f427b22bfd8945b76ddb915eb46dae911b623`。
- wrong SHA-256：`5e00f862c7b557d39096db4317d0dd97c61328313f7c1f7bdb2052dda51f664b`。
- hidden SHA-256：`26768ba7177453d8fd16f3935273a4c928eccb92688f1cb7df0496c5e66da470`。

原始运行目录按规则忽略，仅在本地；不提供虚构的GitHub下载链接。新集合名v3是集合版本，manifest schema仍为version2；旧默认入口仍使用`manifest_v2.json`。

## 如何显式使用新版

```powershell
# 不调用模型，重新校准全部18题；输出目录必须不存在
python benchmarks/run_evaluation.py validate --manifest benchmarks/manifest_synthetic_v3.json --output benchmarks/results/v2/my-new-precision-validation

# 不调用模型，用新精度协议验收一份候选补丁；输出目录也必须不存在
python benchmarks/run_evaluation.py grade --manifest benchmarks/manifest_synthetic_v3.json --case case_15 --patch path/to/fix.patch --output benchmarks/results/v2/my-new-precision-grade
```

不要使用`run`来做上述离线检查；真实模型实验与预算另确认。旧54/54仍属于旧资产/协议的历史成绩，新集合不能续跑旧实验或直接沿用该分数；未来成绩下降也可能只是验收更严格。

## 工程与隔离边界

三个新增自有测试先观察RED（新集合缺失），再实际验证：17题/公开输入不变且无私有材料泄漏；新版baseline/gold/wrong校准成立；旧gold被新隐藏验收拒绝。与加载/判分/CLI相关检查共48项通过，新增测试Ruff检查/格式通过。最终完整离线回归687 passed、2 deselected（264.45秒，exit0），XML为687 tests/0 failures/0 errors。两个显式项未运行不算API或Docker通过。

4,130受保护旧文件摘要无变化，三份私有复制文件的源/目标哈希一致。完整回归XML保留在`D:/Project/PyRepair Agent/tmp/synthetic-v3-final-8ca801dc20e34ec584b7dc43a80682a6/full-regression.xml`。问题处理见[工程日志步骤42](evaluation-v2-engineering-log.md)。

本步未改Agent、评分器、模型配置、默认CLI或Docker harness，没有重建镜像、运行上游项目、提交/推送/PR。下一步是先设计Agent自身baseline/工具测试/最终验证的容器适配，确认后再实施；独立评分器已容器化不等于整个Agent已隔离。之后还有公平基线、预算确认后的重复实验与性能/成本报告，见[收尾检查表](evaluation-completion-checklist.md)。
