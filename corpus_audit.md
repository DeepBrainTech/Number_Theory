# PDF 资料审计与入库建议

审计日期：2026-08-05

## 结论

审计时 `pdf/` 中共有 27 份 PDF、约 8,452 页。没有 SHA-256 完全相同的文件，但存在同一系列的不同卷、同一手稿的不同影印版，以及大量主题重叠。审计后，C 类的 9 份文件已于 2026-08-05 按用户要求删除；当前保留 18 份 PDF。

不建议全部入库。为了先跑通系统，第一本样书建议使用：

> `1017984325-Introduction-to-Number-Theory-2026 (1).pdf`

理由：它是 Richard Michael Hill 的完整入门教材，正文文本层质量好，章节结构清晰，覆盖欧几里得算法、同余、素数、多项式环、二次互反、密码学等内容，不需要先解决 OCR，最适合验证端到端流程。

## 审计方法

- 计算文件 SHA-256，排查字节级重复；
- 读取 PDF 元数据、页数和全文文本层；
- 检查目录、前言、正文和公式样本；
- 对无文本或稀疏文本 PDF 渲染封面、目录及多处正文页面进行视觉抽查；
- 比较书目关系、卷次、底层手稿和主题覆盖；
- 以“回答正确性、教材权威性、公式可提取性、与已有资料的互补性”为筛选依据。

本报告判断的是是否适合进入当前数论 Agent 的知识库，不评价书籍本身的学术价值。

## A：建议进入核心库

| 文件 | 内容定位 | 文档质量 | 建议 |
|---|---|---|---|
| `1017984325-Introduction-to-Number-Theory-2026 (1).pdf` | Richard Michael Hill，基础数论与代数方法 | 262 页，文本层好 | **第一本入库** |
| `421432598-METHODS-OF-SOLVING-NUMBER-THEORIES.pdf` | Ellina Grigorieva，初等数论解题方法 | 404 页，文本层好，例题丰富 | 第二批；适合教学和解题 |
| `437419531-Number-theory-and-geometry.pdf` | Álvaro Lozano-Robledo，数论与算术几何导论 | 506 页，原生 LaTeX 文本质量好 | 第二批；补充丢番图方程、曲线和算术几何 |
| `953736487-经典数论的现代导引-蔡天新-著-Z-Library.pdf` | 蔡天新，中文经典数论教材 | 293 页，有文本层但存在 OCR/空格噪声 | 第二批；中文问答的重要来源，公式需对照页面 |
| `TomIntroduction to Analytic Number Theory.pdf` | Tom M. Apostol，本科解析数论经典教材 | 350 页，OCR 文本可用但有符号识别错误 | 第二批；需公式质量检查 |
| `489076707-Introduction-to-Analytic-and-Probabilistic-Number-Theory.pdf` | Gérald Tenenbaum，解析与概率数论 | 466 页，OCR 文本可用但已有可见错字 | 高阶扩展；不能直接信任公式 OCR |
| `vdoc.pub_multiplicative-number-theory-i-classical-theory.pdf` | Montgomery–Vaughan，乘法数论 I：经典理论 | 571 页，文本层好 | 高阶核心；与第二卷互补，不是重复 |
| `montgomery-vaughanIIMultiplicative number theory.pdf` | Montgomery–Vaughan，乘法数论 II：素数与筛法 | 472 页，原生 LaTeX 文本质量好 | 高阶核心；从第 16 章继续第一卷 |
| `037_解析数论基础.pdf` | 潘承洞、潘承彪，《解析数论基础》 | 933 页，扫描清晰但完全没有文本层 | 中文高阶核心；系统跑通后再做 OCR，不作为第一本 |

## B：有价值，但只在相应模式中按需入库

| 文件 | 内容定位 | 风险或重叠 | 建议 |
|---|---|---|---|
| `406208375-A-panorama-in-number-theory-G-Wustholz-pdf.pdf` | Baker 方法、超越数论、丢番图逼近等研究综述合集 | 不是连贯教材，各章作者和前提不同 | 研究模式后续加入 |
| `790211459-哥德巴赫猜想.pdf` | 哥德巴赫猜想、筛法等专题专著 | 332 页低质量扫描，无文本层；与《解析数论基础》的筛法/哥德巴赫部分有主题重叠 | 暂缓；只有做哥德巴赫专题研究时再 OCR |
| `burde_81_annt_courseAnalytic Number Theory.pdf` | Dietrich Burde，2025 解析数论讲义 | 118 页，文本很好，但内容较短且与 Apostol/Montgomery–Vaughan 重叠 | 可作简明补充，不必首批加入 |
| `230677144-Ramanujan-s-Notebooks-Part-2-of-5.pdf` | Bruce C. Berndt，《Ramanujan's Notebooks Part II》 | 372 页扫描版，无文本层，但页面清晰且包含证明 | Ramanujan 专题时 OCR 后加入 |
| `RamanujanNotebooksPart3Berndt.pdf` | Berndt，《Ramanujan's Notebooks Part III》 | 521 页，文本可提取 | Ramanujan 专题加入；与 Part II/IV 是连续卷，不重复 |
| `Ramanujan Notebooks4Berndt.pdf` | Berndt，《Ramanujan's Notebooks Part IV》 | 231 页，文本可提取，含原命题的证明和出处 | Ramanujan 专题优先于原始手稿加入 |
| `Multiplicative number theory.pdf` | Andrew Granville、K. Soundararajan，pretentious number theory 早期草稿 | 文件明确写着 “early draft” 和 “Please do not circulate”，且可能过时 | 不进入默认正确性知识库；研究模式中谨慎参考 |
| `RamanujanKSRchap3.pdf` | Ramanujan 手稿、Berndt 编辑工作与 lost notebook 的历史综述 | 仅 20 页，主要是历史和书目说明 | 可作为研究导航，不作为定理来源 |
| `数论-陈景润.pdf` | 实际书名为陈景润《数论概貌》 | 50 页清晰扫描但无文本层；内容是概览，深度有限 | 可选，不值得首批 OCR |

## C：不建议进入数学知识库（已删除）

以下 9 份文件已于 2026-08-05 从 `pdf/` 直接删除，合计约 148.6 MB。本表保留为删除记录。

| 文件 | 原因 |
|---|---|
| `Collected EssaysRamanujan.pdf` | 这是文学家、诗人和语言学家 **A. K. Ramanujan** 的文学与文化论文集，不是数学家 Srinivasa Ramanujan 的著作。 |
| `Man Who Knew InfinityKanigel.pdf` | Ramanujan 传记；适合人物历史问答，不是数学定理和证明来源。 |
| `An Introduction to Creativity of RamanujanPrimarySchoolDharmarajan.pdf` | 小学教师教学材料，扫描成双页版，文本层几乎为空；内容层级已被更好的基础教材覆盖。 |
| `An Introduction to Creativity of RamanujanHighSchoolDharmarajan.pdf` | 中学教师教学材料，扫描成双页版；有少量手稿摘录，但不适合作为严谨知识主来源。 |
| `Manuscript book 1Ramanujan.pdf` | 原始彩色手稿，手写、无文本层、许多结果无证明；Berndt Part IV 已对第一手稿的独有结果作证明和整理。 |
| `Manuscript book 2Ramanujan.pdf` | 原始彩色手稿，手写 OCR 风险极高，结果经常没有证明；与 TIFR 影印本及 Berndt 编辑本内容重叠。 |
| `Manuscript book 3Ramanujan.pdf` | 原始彩色第三手稿；无文本层、无系统证明，不适合自动问答。 |
| `NotebooksSriRamanujanVol2Ramanujan.pdf` | TIFR/Springer 的第二、第三手稿影印版；和 `Manuscript book 2/3` 是同一底层手稿的不同影印版本，灰度版质量还低于彩色版。 |
| `RamanujanCVignat-2025-04-15-pictures.pdf` | 基本是各卷封面和少量手稿图片的素材汇编，不是可检索教材。 |

## 重复与重叠关系

### 可以确认的底层内容重复

- `NotebooksSriRamanujanVol2Ramanujan.pdf` 与 `Manuscript book 2Ramanujan.pdf`、`Manuscript book 3Ramanujan.pdf` 都在复现 Ramanujan 的第二、第三手稿。它们不是相同 PDF 文件，但底层数学内容重复。
- `RamanujanCVignat-2025-04-15-pictures.pdf` 中的封面和手稿图片来自其他 Ramanujan 资料，没有独立知识价值。

### 不是重复，不应误删

- Montgomery–Vaughan 的 Part I 与 Part II 是连续两卷：第一卷为第 1～15 章，第二卷从第 16 章继续。
- Berndt 的 Ramanujan's Notebooks Part II、III、IV 是不同卷，分别整理不同章节或手稿部分。
- Berndt 编辑本与 Ramanujan 原始手稿有内容对应，但编辑本提供证明、参考文献和纠错；正确性优先时应保留编辑本、排除原始手稿自动入库。

### 主题重叠但可以互补

- Hill、Grigorieva、蔡天新和 Apostol 都覆盖整除、同余、素数等基础内容，但定位不同：系统教材、解题训练、中文经典数论和解析数论桥梁。
- Apostol、Tenenbaum、Burde、Montgomery–Vaughan 与《解析数论基础》都有解析数论重叠。建议按难度和语言选择，不要在 MVP 中同时全部入库。
- 《哥德巴赫猜想》与《解析数论基础》的筛法、素数分布和哥德巴赫相关章节重叠；前者只在专题研究时有必要。

## 建议的实际入库顺序

1. **端到端样本**：只导入 Hill 的 `Introduction to Number Theory`。
2. **基础教学扩展**：加入 Grigorieva、蔡天新、Apostol。
3. **领域扩展**：加入 Lozano-Robledo 的算术几何教材。
4. **高阶解析数论**：先加入 Montgomery–Vaughan I/II，再根据需求加入 Tenenbaum。
5. **中文高阶资料**：系统稳定后为潘承洞、潘承彪《解析数论基础》做高质量 OCR。
6. **专题库**：Ramanujan 使用 Berndt 编辑本；哥德巴赫、Baker 方法等只在研究模式按需启用。

首个可运行版本不需要处理扫描版、传记、原始手稿或全部 8,452 页。
