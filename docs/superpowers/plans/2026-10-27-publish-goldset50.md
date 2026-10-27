# 五十题结果发布实施计划

用户已批准直接发布main；简历最终只输出可粘贴文字，原文件不编辑。

- [ ] 从三个只读journal组装129+4+167=300唯一有序槽，对照既有summary，按字段白名单生成benchmarks/results/goldset50-20261027-summary.json与goldset50-20261027-runs.jsonl。无绝对路径、密钥或原始模型内容。
- [ ] 修改README当前评测节和底部链接，新增docs/goldset50-results.md；更新opensource-catalog30.md、opensource-task-calibration.md、opensource-reference-preparation.md的最新状态说明，保留历史阶段内容。文档任务可委托独立代理，父代理核对数据并处理发布。
- [ ] 首轮全量离线回归已实际执行：1339 passed/12failed/9deselected/2264.08秒。独立只读定位环境相关失败；将唯一已确认的开源fixture生成缓存可恢复地移至隔离目录，保持源码/历史包不变。以正常系统临时目录、必要命令权限重验全部失败项；README现有命令/安全标题检查由正当文档更新覆盖，不删除或跳过测试。
- [ ] 对本次发布差异作独立审查，运行静态检查、链接/白名单/计数/密钥扫描；仅显式暂存项目文件。保留原始失败和复验记录，不新增付费评测。
- [ ] 用户已选main直更：核对main为发布HEAD祖先、远程未前进；D主工作区保留未跟踪材料，git merge --ff-only <发布SHA>，git push origin main。不force、不创建无关PR、不删除托管工作区。
- [ ] 读取远程README/提交确认线上内容；最终提供GitHub链接及PyRepair简历替换文字，注明整工作流对照，不输出简历文件。
