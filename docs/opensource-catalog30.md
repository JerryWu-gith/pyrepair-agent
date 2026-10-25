# 三十道开源缺陷来源目录

来源登记日期：2026-10-25。本文件与机器目录只负责来源身份，不是可执行任务清单。后续更新：2026-10-26 三十题已完成 Docker 离线校准，见[任务验收记录](opensource-task-calibration.md)；尚未运行新一轮 DeepSeek 评测。

三十份生产参考补丁和五十五个去重源码版本的独立复核见[源码与参考准备记录](opensource-reference-preparation.md)。文档链接经用户批准单独留证，不创建或跟随。来源校验、任务校准、模型性能是三个不同阶段，不能相互替代。

依据 [统一五十题设计](superpowers/specs/2026-10-25-unified-goldset50-design.md) 与 [本阶段实施计划](superpowers/plans/2026-10-25-unified-goldset-sources.md)。机器可读来源见 [opensource_catalog30.json](../benchmarks/opensource_catalog30.json)，检查入口见 [inspect_source_catalog.py](../benchmarks/inspect_source_catalog.py)。它不是旧运行器可直接执行的任务manifest。

## 1. 数量和用途

| 仓库 | 来源数 |
| --- | ---: |
| [mahmoud/boltons](https://github.com/mahmoud/boltons) | 1 |
| [more-itertools/more-itertools](https://github.com/more-itertools/more-itertools) | 3 |
| [pallets/click](https://github.com/pallets/click) | 8 |
| [pypa/packaging](https://github.com/pypa/packaging) | 12 |
| [theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) | 6 |
| 合计 | 30 |

已有两道开发题保持dev。新增二十八道暂列holdout候选；如果用于Agent提示词或策略调优就必须改标。这个标签不保证基础模型训练时没见过这些公开缺陷。

## 2. 候选目录

下表编号表示不同的修复任务，不是断言数、API请求数或重复评测数。真实来源不等于高难度：本批以纯Python、小到中等范围缺陷为主。部分任务属于同一仓库或同类故障，不能据此声称三十个统计独立的工程环境。

| ID | 真实来源 | 缺陷概述 | 用途 |
| --- | --- | --- | --- |
| `os_more_seekable_1269` | [more-itertools/more-itertools #1269](https://github.com/more-itertools/more-itertools/pull/1269) | 零缓存 seekable 的 peek/bool 吞掉元素 | 已有开发题 |
| `os_boltons_addlist_458` | [mahmoud/boltons #458](https://github.com/mahmoud/boltons/pull/458) | 一次性迭代器被重复消费，容器与URL查询参数记录不一致 | 已有开发题 |
| `os_packaging_hash_1232` | [pypa/packaging #1232](https://github.com/pypa/packaging/pull/1232) | 相等的版本约束对象哈希不同，集合或字典去重异常 | 新增验收候选 |
| `os_packaging_quotes_1213` | [pypa/packaging #1213](https://github.com/pypa/packaging/pull/1213) | marker 引号序列化改变原有条件语义 | 新增验收候选 |
| `os_packaging_empty_tags_1234` | [pypa/packaging #1234](https://github.com/pypa/packaging/pull/1234) | wheel文件名及tag接受空组件，形成无效标签 | 新增验收候选 |
| `os_packaging_tag_fields_1238` | [pypa/packaging #1238](https://github.com/pypa/packaging/pull/1238) | tag字段数量不合法时泄漏底层异常 | 新增验收候选 |
| `os_packaging_file_scheme_1240` | [pypa/packaging #1240](https://github.com/pypa/packaging/pull/1240) | file URL协议名大小写处理不一致 | 新增验收候选 |
| `os_packaging_bool_int_1244` | [pypa/packaging #1244](https://github.com/pypa/packaging/pull/1244) | 锁文件将布尔值误当作整数接收 | 新增验收候选 |
| `os_packaging_nested_extra_1246` | [pypa/packaging #1246](https://github.com/pypa/packaging/pull/1246) | 括号中的extra条件未按相同规则归一化 | 新增验收候选 |
| `os_packaging_literal_errors_1249` | [pypa/packaging #1249](https://github.com/pypa/packaging/pull/1249) | 畸形引号字面量泄漏内部解析异常 | 新增验收候选 |
| `os_packaging_license_with_1266` | [pypa/packaging #1266](https://github.com/pypa/packaging/pull/1266) | 许可证表达式错误接受不合法WITH组合 | 新增验收候选 |
| `os_packaging_missing_env_1276` | [pypa/packaging #1276](https://github.com/pypa/packaging/pull/1276) | 环境变量缺失时的公开异常合同不一致 | 新增验收候选 |
| `os_packaging_nested_group_1316` | [pypa/packaging #1316](https://github.com/pypa/packaging/pull/1316) | 序列化丢失嵌套括号，改变and/or分组语义 | 新增验收候选 |
| `os_packaging_invalid_spec_1332` | [pypa/packaging #1332](https://github.com/pypa/packaging/pull/1332) | 畸形版本约束未转换成公开Requirement异常 | 新增验收候选 |
| `os_click_flags_2930` | [pallets/click #2930](https://github.com/pallets/click/pull/2930) | 指定类型后，命令行开关值处理错误 | 新增验收候选 |
| `os_click_enum_default_3004` | [pallets/click #3004](https://github.com/pallets/click/pull/3004) | Enum选项的默认值在帮助文本中显示错误 | 新增验收候选 |
| `os_click_env_hint_2972` | [pallets/click #2972](https://github.com/pallets/click/pull/2972) | 未配置环境变量时错误信息仍加入envvar提示 | 新增验收候选 |
| `os_click_resource_exit_3058` | [pallets/click #3058](https://github.com/pallets/click/pull/3058) | 注册资源未收到Context退出时的异常信息 | 新增验收候选 |
| `os_click_eof_2940` | [pallets/click #2940](https://github.com/pallets/click/pull/2940) | CliRunner对输入结束的处理出现回归 | 新增验收候选 |
| `os_click_zsh_colon_2846` | [pallets/click #2846](https://github.com/pallets/click/pull/2846) | Zsh补全项含冒号时的转义不正确 | 新增验收候选 |
| `os_click_progress_final_3769` | [pallets/click #3769](https://github.com/pallets/click/pull/3769) | 进度更新间隔不能整除总量时未落到最终位置 | 新增验收候选 |
| `os_click_callable_flag_3225` | [pallets/click #3225](https://github.com/pallets/click/pull/3225) | 作为默认值的可调用flag_value被错误实例化 | 新增验收候选 |
| `os_dotenv_bom_640` | [theskumar/python-dotenv #640](https://github.com/theskumar/python-dotenv/pull/640) | UTF-8 BOM污染第一个变量名 | 新增验收候选 |
| `os_dotenv_backslash_680` | [theskumar/python-dotenv #680](https://github.com/theskumar/python-dotenv/pull/680) | 含反斜杠值不能读写往返，尾反斜杠可吞掉后续行 | 新增验收候选 |
| `os_dotenv_override_698` | [theskumar/python-dotenv #698](https://github.com/theskumar/python-dotenv/pull/698) | no-override下变量展开使用了错误优先级 | 新增验收候选 |
| `os_dotenv_empty_get_700` | [theskumar/python-dotenv #700](https://github.com/theskumar/python-dotenv/pull/700) | CLI将空字符串值误判为不存在 | 新增验收候选 |
| `os_dotenv_missing_command_606` | [theskumar/python-dotenv #606](https://github.com/theskumar/python-dotenv/pull/606) | run缺少或找不到命令时错误处理不友好 | 新增验收候选 |
| `os_dotenv_empty_cache_638` | [theskumar/python-dotenv #638](https://github.com/theskumar/python-dotenv/pull/638) | 空文件的解析结果未缓存，重复读取 | 新增验收候选 |
| `os_more_bucket_validator_1309` | [more-itertools/more-itertools #1309](https://github.com/more-itertools/more-itertools/pull/1309) | 具有假布尔值的validator被错误忽略 | 新增验收候选 |
| `os_more_ichunked_sizes_1305` | [more-itertools/more-itertools #1305](https://github.com/more-itertools/more-itertools/pull/1305) | ichunked的零或负尺寸行为与chunked不一致 | 新增验收候选 |

## 3. 固定版本索引

缺陷基线取修复提交第一父版本；不采用PR页面可变化的base字段。完整SHA也保存在机器清单。参考修改文件只用于审计和制作参考补丁，不能当作Agent的精确定位答案或公开编辑白名单。

| ID | 缺陷版本 | 上游参考修复 |
| --- | --- | --- |
| `os_more_seekable_1269` | [1da45ae4b61a](https://github.com/more-itertools/more-itertools/commit/1da45ae4b61a832ed080f08a8833784aad0a9534) | [b5e3886a3720](https://github.com/more-itertools/more-itertools/commit/b5e3886a37209bb880f17d82fbf4ba00ece0e41e) |
| `os_boltons_addlist_458` | [d45cc414e33a](https://github.com/mahmoud/boltons/commit/d45cc414e33aa4e08a73e0993574df4397e2e9db) | [a1ea1030ed85](https://github.com/mahmoud/boltons/commit/a1ea1030ed85137e999c0bd9b11d16368d3ab241) |
| `os_packaging_hash_1232` | [664f049980f1](https://github.com/pypa/packaging/commit/664f049980f1873c458de72a449003b83173f445) | [d8e08df11bfa](https://github.com/pypa/packaging/commit/d8e08df11bfa50e987375546eda1f0ee3f27bd41) |
| `os_packaging_quotes_1213` | [2497782b2bb0](https://github.com/pypa/packaging/commit/2497782b2bb03812d2a12ae882a4390c61ec5061) | [5b583e309996](https://github.com/pypa/packaging/commit/5b583e309996a085ad3b5b045f3bf50a09c11b58) |
| `os_packaging_empty_tags_1234` | [ffb76f30eb15](https://github.com/pypa/packaging/commit/ffb76f30eb15753142d6c4b95c693f3e909cf135) | [c5b253b24ba5](https://github.com/pypa/packaging/commit/c5b253b24ba5d4c242a73ff19b02ef0833ba5859) |
| `os_packaging_tag_fields_1238` | [a33b2941bf33](https://github.com/pypa/packaging/commit/a33b2941bf334823ab48b059611158d37da5846e) | [f0620a997147](https://github.com/pypa/packaging/commit/f0620a997147fefd6844af9745c7bf28b43cce29) |
| `os_packaging_file_scheme_1240` | [0d799f1ae4ae](https://github.com/pypa/packaging/commit/0d799f1ae4ae15be8636ffb514dc014aa81c0b8e) | [e80f70f8b164](https://github.com/pypa/packaging/commit/e80f70f8b164ee4b0ef7634aafe8c6cc4ce00ca3) |
| `os_packaging_bool_int_1244` | [c34f81d244cb](https://github.com/pypa/packaging/commit/c34f81d244cbbc679d2b5a238f485afa214385ae) | [9a11fba3d532](https://github.com/pypa/packaging/commit/9a11fba3d53215dc2ff08d8e9d0d5780c08fbe8f) |
| `os_packaging_nested_extra_1246` | [349abfad0688](https://github.com/pypa/packaging/commit/349abfad0688f42eb835ed8a10380d6cbf6940e7) | [07265129295b](https://github.com/pypa/packaging/commit/07265129295b4b95b9143b50e3ce4709f31a8c49) |
| `os_packaging_literal_errors_1249` | [adc6f2119943](https://github.com/pypa/packaging/commit/adc6f21199435de1903585f98c0277af66ec02f0) | [6115033aa646](https://github.com/pypa/packaging/commit/6115033aa6469c0d0f78e53be5cc47b1fbd4b3e7) |
| `os_packaging_license_with_1266` | [b19df947aa03](https://github.com/pypa/packaging/commit/b19df947aa03658c776e44c3005b9c860d5b5c8d) | [0cc1cc8eea11](https://github.com/pypa/packaging/commit/0cc1cc8eea11da73a3ae540b92c51255d7d1d690) |
| `os_packaging_missing_env_1276` | [d406cb4dd392](https://github.com/pypa/packaging/commit/d406cb4dd392d883beb8f25f83dd8f7179b6d504) | [b19df947aa03](https://github.com/pypa/packaging/commit/b19df947aa03658c776e44c3005b9c860d5b5c8d) |
| `os_packaging_nested_group_1316` | [c4fb81ff6eba](https://github.com/pypa/packaging/commit/c4fb81ff6eba16fdd24d50e9d9d002fdbece6dd4) | [0a85b41e24c9](https://github.com/pypa/packaging/commit/0a85b41e24c9b55b83f05ae696d73e8294a5b094) |
| `os_packaging_invalid_spec_1332` | [9c652e4b4ced](https://github.com/pypa/packaging/commit/9c652e4b4ced3c94f133a1b91c726023f0950b4f) | [fe18f139c5b3](https://github.com/pypa/packaging/commit/fe18f139c5b3d73cd9fdd9b25f1eda1b6fd7ba15) |
| `os_click_flags_2930` | [011b9f9d190c](https://github.com/pallets/click/commit/011b9f9d190c71310264e6c54bae6259f5e38a9f) | [884af5c20fdc](https://github.com/pallets/click/commit/884af5c20fdc95c9c7352df35c37273391464fb9) |
| `os_click_enum_default_3004` | [a1235aacb1be](https://github.com/pallets/click/commit/a1235aacb1be55dc66ddcfefbf64dec44b6ab54d) | [eaf33a957975](https://github.com/pallets/click/commit/eaf33a957975e7d0943fad8d2b4b905b6bd98cb9) |
| `os_click_env_hint_2972` | [c88f333de440](https://github.com/pallets/click/commit/c88f333de440c5066ff563f784a6561f4713cf78) | [0be2bd385064](https://github.com/pallets/click/commit/0be2bd385064053bb75f92db317de128db729d52) |
| `os_click_resource_exit_3058` | [16fe802a3f96](https://github.com/pallets/click/commit/16fe802a3f96c4c8fa3cd382f1a7577fda0c5321) | [36deba8a95a2](https://github.com/pallets/click/commit/36deba8a95a2585de1a2aa4475b7f054f52830ac) |
| `os_click_eof_2940` | [36deba8a95a2](https://github.com/pallets/click/commit/36deba8a95a2585de1a2aa4475b7f054f52830ac) | [2a0e3ba90792](https://github.com/pallets/click/commit/2a0e3ba907927ade6951d5732b775f11b54cb766) |
| `os_click_zsh_colon_2846` | [565f36d5bc4a](https://github.com/pallets/click/commit/565f36d5bc4a15d304337b749e113fb4477b1843) | [a1235aacb1be](https://github.com/pallets/click/commit/a1235aacb1be55dc66ddcfefbf64dec44b6ab54d) |
| `os_click_progress_final_3769` | [8b44edfff7d9](https://github.com/pallets/click/commit/8b44edfff7d9a6c895fa804148c16b3a0bc9efb5) | [150d1071d69c](https://github.com/pallets/click/commit/150d1071d69c5cdad7de78590013ffe56cf9e3bb) |
| `os_click_callable_flag_3225` | [ae46cfd6bc99](https://github.com/pallets/click/commit/ae46cfd6bc997804893adc799589248eadcdbc29) | [5850ef97230f](https://github.com/pallets/click/commit/5850ef97230f84c74d0234ab0f30f23b398a6eee) |
| `os_dotenv_bom_640` | [68ea2d10dd8e](https://github.com/theskumar/python-dotenv/commit/68ea2d10dd8e97e6dea67c32742085f27729e3fe) | [bca6644d9aed](https://github.com/theskumar/python-dotenv/commit/bca6644d9aedbe287b792b756b3ae3d650cd0d3a) |
| `os_dotenv_backslash_680` | [751f8c148222](https://github.com/theskumar/python-dotenv/commit/751f8c148222e58aa173c83c4e5e6cfccb2cc124) | [f7b18d9c72d1](https://github.com/theskumar/python-dotenv/commit/f7b18d9c72d1abcc2ad4023424b84f5bee30d266) |
| `os_dotenv_override_698` | [a00cb2eed070](https://github.com/theskumar/python-dotenv/commit/a00cb2eed0704cd6d2071b2004c37e95ccc86ee5) | [e0310e5bb3f2](https://github.com/theskumar/python-dotenv/commit/e0310e5bb3f2b701b11bbc007ca0c82c1bd56f38) |
| `os_dotenv_empty_get_700` | [58f2d7c11223](https://github.com/theskumar/python-dotenv/commit/58f2d7c112235b347040bb5cb579d4ebc0a0ad91) | [f215c0274dc4](https://github.com/theskumar/python-dotenv/commit/f215c0274dc4c310e5ca5feb4c6bddade25ece21) |
| `os_dotenv_missing_command_606` | [dc71adbd8105](https://github.com/theskumar/python-dotenv/commit/dc71adbd8105188602907f6653d3c58d113de554) | [da0c82054f1e](https://github.com/theskumar/python-dotenv/commit/da0c82054f1ec1e03d57356d49b0b9ad09eb4209) |
| `os_dotenv_empty_cache_638` | [bca6644d9aed](https://github.com/theskumar/python-dotenv/commit/bca6644d9aedbe287b792b756b3ae3d650cd0d3a) | [3f0e3e0b461c](https://github.com/theskumar/python-dotenv/commit/3f0e3e0b461cf7127e2753efbdf896bdff31db2e) |
| `os_more_bucket_validator_1309` | [1ea82a711c69](https://github.com/more-itertools/more-itertools/commit/1ea82a711c69f590054987b5cb194157f8ce8ac4) | [67fcf640477c](https://github.com/more-itertools/more-itertools/commit/67fcf640477c78605580f5ee703a54c73c1e7a8a) |
| `os_more_ichunked_sizes_1305` | [790bb0bb2c03](https://github.com/more-itertools/more-itertools/commit/790bb0bb2c03e7a07282e5f16f4b1fde35b8fcf5) | [1ea82a711c69](https://github.com/more-itertools/more-itertools/commit/1ea82a711c69f590054987b5cb194157f8ce8ac4) |

## 4. 已排除的来源

排除发生在模型评测前，原因记录在JSON，不是按Agent能否通过挑题。

| 来源 | 原因 |
| --- | --- |
| Click #3201 | 未直接合并；与已选、已合并的#3225关联同一问题，不能重复计数。 |
| Click #2991 | 虽已合并，但上游明确表示并发复现不稳定，不适合作为本批确定性验收。 |
| python-dotenv #663、Click #2907 | 日志引用不代表PR直接合并，API核对后未纳入。 |
| Click #2897 | 是被#2930引用的问题编号，不是另一份独立修复PR。 |

## 5. 还没有完成的内容

每个新增来源仍须完成：固定源码归档和逐文件Git blob核验；固定版本许可证及分发说明；不泄漏参考答案的公开任务和复现；隐藏边界、原有行为回归和不完整补丁；容器环境和模块来源验证；缺陷/参考/不完整三类补丁的校准。

源码、许可和任务质量问题均可能导致候选在模型运行前被替换，替换必须记录理由。正式题集冻结前，这三十条只是来源候选，不承诺都已具备可靠验收。尤其Zsh补全任务须明确是检查脚本输出还是执行真实shell；CLI任务须检查容器子进程依赖；空文件缓存题须使用行为证据而非仅比较实现文本。不能因这些任务来自已合并PR就跳过质量核验。

已有两题保留其原资产；是否复用旧离线校准取决于本批的任务、协议和环境身份是否完全一致。历史模型通过记录不能替代校准。

## 6. 只读检查

在当前worktree根目录执行：

```powershell
& 'D:/Project/PyRepair Agent/.venv/Scripts/python.exe' benchmarks/inspect_source_catalog.py
```

它只读取来源JSON并输出计数、仓库分布、用途标签与`ready_for_model_evaluation: false`，不会请求模型、拉镜像、写任务资产或改动输入。拒绝`--execute`、`--model`和`--prepare`等参数。对缺失文件、重复JSON键、非法字段或解析资源上限错误返回受控失败，不将错误伪装成已验收状态。

接下来先准备这三十题的源码、许可和离线评分资产，再补两道自建题；五十题全部验收与冻结后才启动新的统一DeepSeek评测。旧59/60与36/60不拼入新批次。

## 7. AI辅助来源披露

上游PR中的AI使用披露按实际已读信息保存在`upstream_ai_assistance`；未建立结论不等于未使用AI。有些PR只把描述标为AI文本，不能因此断言整份代码由AI编写；这些上游修复也不包装成本项目独立发现或创作。
