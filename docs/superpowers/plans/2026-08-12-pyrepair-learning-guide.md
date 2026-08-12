# PyRepair Agent Learning Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一份经过文字与逐页视觉验证的中文《PyRepair Agent 十天实战学习手册》PDF。

**Architecture:** 使用 Markdown 保存可维护正文，使用独立 ReportLab 脚本将正文转换为带封面、目录、页眉页脚、表格、代码框和提示框的 A4 PDF。生成后同时执行 pypdf/pdfplumber 结构检查和 Poppler 全页渲染检查。

**Tech Stack:** Markdown、Python 3.11+、ReportLab、pypdf、pdfplumber、Poppler、Windows CJK 字体。

## Global Constraints

- 最终文件固定为 `output/pdf/pyrepair-agent-10-day-learning-guide.pdf`。
- 中间文件只写入 `tmp/pdfs/`。
- 手册面向 Python 基础可用、HelloAgent 学到第 7 章、Git 不熟悉的学习者。
- 每天学习时间为 4-6 小时，共 10 天。
- 真实评测必须表述为端到端 13/15、成功率 86.7%，不能称为模型准确率。
- 所有项目路径、命令、模块名称必须与当前仓库一致。

---

### Task 1: 编写学习手册正文

**Files:**
- Create: `docs/pyrepair-learning-guide.md`

**Interfaces:**
- Consumes: 当前 `README.md`、`docs/architecture.md`、`docs/benchmark-results.md` 和 `src/pyrepair/` 模块结构。
- Produces: 具有稳定标题层级、代码块、表格和提示块标记的 UTF-8 Markdown 正文。

- [ ] **Step 1: 编写项目全景和学习方法**

写明项目目标、非目标、完整调用链、核心术语和源码阅读方法。

- [ ] **Step 2: 编写 10 天逐日计划**

每天必须包含：目标、时间块、阅读路径、命令解释、动手任务、自测题、完成标准和记录区。

- [ ] **Step 3: 编写专题与附录**

覆盖模块地图、Tool Calling、安全门、测试层次、Git、pytest 9 改进练习、调试、项目讲解、简历和面试题。

- [ ] **Step 4: 检查正文完整性**

Run: `rg -n "^#|^##|^###" docs/pyrepair-learning-guide.md`

Expected: 10 个每日章节和所有专题章节均存在，无 `TODO`、`TBD` 或占位文字。

### Task 2: 实现 PDF 构建器

**Files:**
- Create: `scripts/build_learning_pdf.py`

**Interfaces:**
- Consumes: `Path` 类型的 Markdown 输入路径和 PDF 输出路径。
- Produces: `build_pdf(source: Path, output: Path) -> None` 和命令行入口。

- [ ] **Step 1: 实现字体、颜色和页面模板**

注册 CJK 与等宽字体，创建 A4 页面、封面、页眉、页脚和页码。

- [ ] **Step 2: 实现 Markdown 子集解析**

支持一级至三级标题、段落、列表、代码块、简单表格、提示块和显式分页标记。

- [ ] **Step 3: 实现目录和 PDF 元数据**

使用 `multiBuild` 生成可点击书签和目录；标题设为“PyRepair Agent 十天实战学习手册”。

- [ ] **Step 4: 执行构建**

Run: `python scripts/build_learning_pdf.py docs/pyrepair-learning-guide.md output/pdf/pyrepair-agent-10-day-learning-guide.pdf`

Expected: exit 0，输出 PDF 存在且非空。

### Task 3: 自动结构与内容验证

**Files:**
- Create: `scripts/verify_learning_pdf.py`

**Interfaces:**
- Consumes: 最终 PDF 路径。
- Produces: 退出码 0/1，以及页数、页面尺寸、文字完整性和关键章节检查结果。

- [ ] **Step 1: 检查 PDF 结构**

使用 pypdf 确认 PDF 可重开、页数在 20-45 页、所有页面为 A4 附近尺寸。

- [ ] **Step 2: 检查关键文字**

使用 pdfplumber 提取全文，确认“第1天”至“第10天”、“86.7%”、“Policy”、“Review”、“Verifier”和“pytest 9”存在。

- [ ] **Step 3: 运行验证**

Run: `python scripts/verify_learning_pdf.py output/pdf/pyrepair-agent-10-day-learning-guide.pdf`

Expected: exit 0，并输出 `PDF verification passed`。

### Task 4: 渲染并逐页视觉检查

**Files:**
- Create: `tmp/pdfs/pyrepair-learning-guide-*.png`
- Final: `output/pdf/pyrepair-agent-10-day-learning-guide.pdf`

**Interfaces:**
- Consumes: Task 2 生成的最终 PDF。
- Produces: 仅用于 QA 的逐页 PNG 和经过修正的最终 PDF。

- [ ] **Step 1: 渲染全部页面**

Run: `pdftoppm -png -r 120 output/pdf/pyrepair-agent-10-day-learning-guide.pdf tmp/pdfs/pyrepair-learning-guide`

Expected: 每一页生成一张 PNG。

- [ ] **Step 2: 制作并检查联系表**

将所有页面缩略图排成联系表，检查页面密度、章节切换、空白和溢出；对代码与表格密集页单独查看原图。

- [ ] **Step 3: 修正并重新验证**

若发现重叠、裁切、乱码或不合理分页，修改正文或构建脚本，重新执行 Task 2-4，直到无视觉缺陷。

- [ ] **Step 4: 清理 QA 文件并核对 Git 状态**

删除 `tmp/pdfs/` 下本次 PNG，保留正文、构建器、验证器和最终 PDF，运行 `git status --short` 核对交付范围。
