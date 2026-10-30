# SenoMiner-AI：抗衰老化合物结构化实验数据库

输入抗衰老相关论文的 PDF、DOI 或 PMID，提取**本论文实际研究、并报告抗衰老相关积极效果的具体化合物**，将研究对象、实验条件、结果和证据来源组织为可查询的实验记录。一个独立实验设计/队列对应一条记录；同一实验的多个检测指标保留在记录内部。

字段分区参考 [CancerPPD 2.0 官方记录说明](https://webs.iiitd.edu.in/raghava/cancerppd2/usr_guide.html)：分子基本信息、实验数据、文献来源。本项目使用 LLM 抽取与程序核对，不能将它标为人工逐条整理的数据库。

本工具用于整理作者报告的实验，不负责证明药物具有临床抗衰老效果。程序仍读取全文并检查药物角色和原文引文，避免把诱导剂、对照、其他论文的结果当作本篇发现；这些检查在后台执行，网页呈现整理后的化合物与实验解读。“HSP90 inhibitors”等类别名称保留在原始报告中，不能作为一个具体化合物进入列表。

## 第一次使用

1. Mac 双击 [启动项目.command](启动项目.command)；Windows 双击 [启动项目.bat](启动项目.bat)，首次按下方说明初始化。不要关闭启动终端。重复启动会复用当前项目已运行的页面，不再另开端口；更新代码后应先关闭旧服务再启动，避免旧代码继续使用缓存。打开 [本地目录页](http://127.0.0.1:8766/catalog)。本项目固定使用 `.conda/SenoMiner_AI`（Python 3.11.15）和包 `chem-pdf-extractor 0.4.0`。
2. 列表按**文献读取时间从新到旧**排列，显示名称、**3D 分子结构**和完整论文名。可以搜索化合物、细胞系、剂量、检测方法或论文，并按实验类型、作用类型筛选；底部可选择页码。点“导出实验表”下载符合当前条件的 CSV。联合用药保持组合身份，分别显示各组分结构。
3. 添加论文有两种方式：在右侧选择 PDF，点“上传并提取”（已有待提取文件可直接点“提取这篇 PDF”）；或在上方输入完整 DOI / PMID，点“按编号直接提取”。关键词检索则先点“查找文献”，再选择“提取公开全文”。全文会发送到 `.env` 配置的云端模型，联网调用可能产生费用。
4. 右侧“提取进展”显示文件名、当前阶段、已完成分段数与耗时。流程为读取 → 分段提取 → 核对原文 → 关联实验 → 查询数据库 → 保存。数字只代表实际完成的分段，不是预测总进度；等待云端时耗时仍更新。失败后点“重试并继续”，会复用成功分段。单个分段在自动重试后仍超时或返回不完整 JSON 时，会保留重叠并拆小处理；拆分计划和完成的子段也会缓存。网络连接失败、限流或服务端错误不会触发拆分，以免增加无效请求。已完成文件默认折叠。
5. 点“查看详情”，最上方默认显示**分子结构与数据库信息**。下面是**结构化实验表**：研究对象、诱导条件、恢复培养、活性药物剂量、时间、对照、检测和结果；再列原文依据、简短结论与文献来源。详细实验操作、参数引文及其他独立实验按需展开。详情与导出使用当前筛选条件。
6. 所有网页操作集中在这一页：上传或查找论文 → 查看提取进展 → 浏览化合物列表 → 阅读详情。不再提供原始提取记录展示页和复杂 PDF 工作台。结束时在启动终端按 **Control+C**。汇报或复现实验前，回原论文核对图表、Methods 与补充材料。

DOI 是文献标识符，不保证能下载全文。系统通过 DOI 精确定位 PubMed，再获取 PMC 公开全文；只有题录或摘要时会显示“需要 PDF”，不会用摘要生成完整实验步骤。找不到对应 PubMed 记录的 DOI 也可以上传 PDF。实时文献与化合物数量以网页为准。

### Windows 复制与双击启动

支持目标为 **Windows 10/11 x64**。源码、论文和结果可以迁移；Mac 的 `.conda` 环境不能复制后直接运行。首次在 Windows 本机重新创建环境，之后日常操作只需双击启动文件。

1. Windows 已安装 Miniforge 或 Miniconda 可跳过这一步；否则先从 [Miniforge 官方页面](https://github.com/conda-forge/miniforge#download)安装 Windows x86_64 版，选择当前用户即可。
2. 把 `dist/SenoMiner-AI-Windows.zip` 复制到 Windows，**完整解压**到固定位置，例如 `C:\Projects\SenoMiner-AI`。
3. 双击根目录的 **`启动项目.bat`**。首次会联网创建 `SenoMiner_AI` 环境、安装固定版本依赖并检查组件；随后自动打开浏览器。以后会复用已经配置好的环境。
4. 启动包不包含真实密钥。首次启动会从 `.env.example` 创建 `.env`，可先浏览已有结果；需要提取新论文时，用记事本在 `.env` 的 `ARK_API_KEY=` 后填写自己的密钥，保存后重新启动。

Windows 专用环境放在 `.conda/win-64/SenoMiner_AI`，使用 **Python 3.11.15**；Mac 环境仍在原路径。启动器通过 `conda run` 设置 Windows 所需的 DLL 路径，不需要手动切换终端环境。原 Mac 启动方式、网页和提取逻辑保持原样。

`requirements-windows.txt` 只选用运行所需依赖，并使用现有 `requirements.lock` 约束版本。若初始化报错，窗口会保留错误信息；网络恢复后可再次启动。请在最终使用位置首次初始化，不要把已安装的 `.conda` 环境在不同电脑或路径间搬动。

迁移时保留 **整个 `output/` 和 `input_pdfs/`**：数据库在 `output/results.sqlite3`，现有报告和原文证据也在 `output/`。SQLite 文件本身[支持跨平台复制](https://www.sqlite.org/onefile.html)，但当前网页还会从原始报告同步数据，因此不能只复制数据库、丢掉报告文件。

需要重新生成迁移包时，在 Mac 项目根目录运行：

```bash
.conda/SenoMiner_AI/bin/python tools/build_windows_bundle.py
```

该工具会备份 SQLite 的一致快照，并保留完整源码、数据库和论文结果，排除 `.conda`、`.git`、日志、缓存字节码和真实 `.env`。压缩包不是免安装 EXE，首次仍需 Windows Conda 和网络。已完成 Windows x64 的 Conda 与 pip 依赖解析检查；尚未在真实 Windows 机器上进行完整启动与提取测试。

### 在本机 Mac 终端激活环境

本机已把项目的 `.conda` 目录加入 Conda 环境搜索路径，可直接按名称激活：

```bash
conda activate SenoMiner_AI
python --version
```

提示符显示 `(SenoMiner_AI)`，Python 应为 `3.11.15`；`conda env list` 可以列出该环境。环境仍保存在项目内部，未移动或重装依赖。若终端还显示旧的完整路径，执行 `conda deactivate` 后重新激活即可。双击启动脚本仍直接调用同一个解释器。

两个实际纠错例子：Piceatannol 论文中的 **5-FU 用于诱导衰老**，其 SA-β-gal 与氧化应激增加不是抗衰老药效；目录保留被验证的 Piceatannol，排除 5-FU。另一篇 abemaciclib/LLOMe 论文主要研究癌细胞溶酶体脆弱性及治疗敏感化，abemaciclib 为诱导/预处理，序贯方案不能作为一个抗衰老化合物条目。GCV 依赖 p16-3MR/HSV-TK 自杀基因的清除对照同样排除。

## 它如何实现

```mermaid
flowchart LR
  A[PubMed 全文 / PDF] --> B[解析正文和图注]
  B --> C[Doubao-Seed-Evolving 分段抽取]
  C --> D[原始候选及实验步骤]
  D --> E[原文字面引文核验]
  E --> R[独立全文复核：角色、方向、对照、支持实验]
  R --> F[通过复核的本篇实验与引文]
  F --> G[重新关联全文：效果句、同一实验方法和结果]
  G --> H[化合物 → 来源论文 → 结构化独立实验记录]
  D --> I[PubChem / ChEMBL / PubMed 增强]
  I --> H
```

- `biology.py` 定义字段与提示词：先识别同一队列、干预、对照和时间窗；不同检测终点可以是同组下的多条结果。模型须区分 `in_vitro`、`ex_vivo`、`in_vivo`、`clinical`，以及剂量分母、给药途径和频率。SA-β-gal、p16、p21 下降仅是标志物变化，不能自动称为衰老细胞被清除。
- `biomedical.py` 将全文按约 8,000 字符分段并保留重叠，用当前 `.env` 的火山方舟 `doubao-seed-evolving` 产生原始记录。`validation.py` 将结果和步骤的逐字引文定位回 `source.md`，并保存待复核状态。
- `claim_review.py` 以整篇原文重新审查各候选和具体记录，区分有效干预、衰老诱导剂、对照、机制探针及癌症治疗结果。它要求明确的抗衰老作用方向、原文效果句、具体实验 ID 及连续结果引文；未完成、证据不匹配或来源变化时暂不收录。复核使用当前配置模型的另一次调用，并非另一个模型或已验证的科学裁判。
- `evidence_cards.py` 对通过角色复核的名称，从整篇原文重新提取效果句与支持它的同一个实验；不把旧记录中混在一起的凋亡、Western blot、机制变化直接当实验卡。每张卡包含对象、剂量、时间、给药、检测、对照和对应原文，多个指标作为同卡子项。引文找不到、模型或检测方法未定位时不展示该卡。
- 剂量、时间、样本量必须逐字出现在对应原文引文中，否则留空。对象/检测方法若被模型概述，只在相关原文描述能完整定位时显示该段原文，丢弃模型改写。格式不合格的参数最多修复一次，仍然执行逐字核对。`catalog.py` 只从这些证据卡建目录；第一遍原始候选用于追溯，不直接组成页面。
- `experiment_groups.py` 提供剂量口径及结果类别等展示辅助。`evidence_cards.py` 以已经定位的对象、方法、图、处理与造模原文建立卡身份，合并相同卡的多个结果，避免把不同造模或队列仅凭相同药物和剂量合并。Hickson 的同一人体给药队列合并组织和循环指标；其他设计仍需核查。
- `evidence_story.py` 从已核验的实验组中选择一条核心原文结果句，生成供结构化实验记录使用的主要发现与流程摘要。Hickson 2019、Fisetin 2018、Chang 2016 与本地 Piceatannol 示例的阅读摘要经过同篇原文锚点核验；对其他新论文使用保守的通用选择，仍需人工核对。原始多指标记录保留供追溯，不再作为首页的“实验数”。
- 剂量显示区分 **500 ppm = 每千克饲料含 500 mg**，与 **100 mg/kg 体重口服灌胃**。不会把前者当作小鼠每日每千克体重 500 mg。内部区分寿命、炎症/SASP、器官指标或衰老标志物，默认界面不显示这组分类标签；只有直接的细胞死亡/凋亡证据才可支持清除推断。
- `structures.py` 优先取 PubChem 3D SDF；没有构象时取相同 CID 的化学结构，用固定版本 RDKit 的 ETKDGv3 生成三维坐标，并验证分子图和立体化学未改变。页面明确标注 PubChem 构象与 RDKit 计算构象；后者用于展示，不是实验测定或对接验证结果。SDF 和来源信息缓存于 `output/.structure_cache/`。列表和详情默认使用本地 `3Dmol.js` 的 WebGL 立体渲染，显示有光照的球体与化学键。详情可切换“球棍／空间填充”、拖动旋转、滚轮缩放及重置视角；分子信息始终在详情最上方。列表共用快照与交互渲染器，鼠标移入后可拖动旋转，翻页不会累积图形上下文。浏览器不支持 WebGL 或图形上下文丢失时使用有明暗和遮挡的 Canvas 兼容显示，页面会注明；也可手动切换。同页结构请求共享缓存，后台刷新不重建未变化的分子图。
- 读取时间保存在新报告的 `read_at`；旧报告采用原始 `report.json` 完成时间。化合物按其最新来源文献的读取时间排序，复核或缓存更新不会使旧论文跳到顶部。同一确认 CID 的别名聚合，组合仍按各组分区分。

原 [Chem-PDF-Extractor](https://github.com/myklovenyzforever/chem-pdf-extractor) 提供 PDF 解析、模型调用和导出基础；[LLM-TPD-Extraction](https://github.com/yaochenr/LLM-TPD-Extraction) 提供生物实验信息抽取参考；[Google DeepMind Science Skills](https://github.com/google-deepmind/science-skills) 的 PubChem、ChEMBL、PubMed 包装脚本保留在 `vendor/`。第三方版本和许可证见 [第三方来源](docs/第三方来源.md)。

## 实验记录字段

| 字段 | 含义 |
| --- | --- |
| 研究对象、实验类型 | 细胞/动物/离体组织/人体给药及具体模型 |
| 诱导剂、诱导条件 | 造模或预处理使用的物质及其剂量、时间 |
| 恢复培养 | 原文明示的造模后无药恢复时间 |
| 活性药物浓度/剂量、处理时间 | 当前被研究化合物的处理条件，与诱导剂分开 |
| 给药方式、对照、样本量、检测方法 | 同一个实验的实际设计 |
| 实验结果、结论适用范围 | 作者报告的结果及其支持的模型范围 |
| 原文证据、位置、文献来源 | 支持结果的原句、章节/图号、论文名、PMID/DOI |

未知值在网页显示“未提取”，JSON/CSV 保持空值；不能据此断言原论文没有报告。所有筛选条件必须命中同一条实验，不能把一个细胞实验的剂量和另一个动物实验的对象拼在一起。

当前保留本地 JSON 报告与已核验实验卡，并自动同步到 SQLite `output/results.sqlite3`，生成“化合物—论文—独立实验”的记录视图，无需额外数据库服务。`GET /api/catalog/records` 返回结构化记录，`?format=csv` 导出表格；两者需要本地页面 token，支持 `q`、`study_type`、`effect_type` 筛选。每条记录保留来源、参数引文、子检测结果和真实操作步骤，CSV 仍是一实验一行。

## 项目结构与数据文件

```text
启动项目.command                 双击启动本地网页
run_senolytics.py                校验虚拟环境、读取 .env、启动程序
.conda/SenoMiner_AI/             固定 Python 3.11.15 虚拟环境
.env                             本机模型与密钥；不会进入 Git
input_pdfs/                      用户上传或下载的原论文 PDF
output/                          每篇原始报告、表格与 PDF/结构缓存
chem_pdf_extractor/
  sources.py, pdf.py              获取 PMC 全文 / PDF 转 Markdown
  biology.py, llm.py              字段、抽取规则和云端模型调用
  biomedical.py                   分段、恢复、逐篇提取与导出
  validation.py                   原文引文与步骤字面核验
  claim_review.py                 独立全文复核、角色判断及收录理由
  evidence_cards.py               从全文重新关联效果句与支持实验，核对参数原文
  enrichment.py, science_skills.py PubChem/ChEMBL/PubMed 增强
  catalog.py                      本篇实验收录、跨论文聚合、3D 数据
  structures.py                   PubChem 3D / RDKit 构象与来源缓存
  experiment_groups.py            剂量口径、模型类型与结果类别辅助
  evidence_story.py               同篇原文约束下的主要发现与流程摘要
  experimental_records.py         独立实验字段、记录索引、同实验筛选与 CSV 导出
  server.py                       本地 API、任务与页面
  catalog_progress.py             当前任务、真实分段计数、耗时与失败状态
  network.py                      使用当前环境的 CA 证书进行严格 HTTPS 校验
  templates/catalog.html          目录页面骨架
  static/catalog.css, catalog.js  简洁页面与 WebGL / 兼容渲染
  static/3Dmol-min.js             本地 WebGL 分子绘图库
vendor/                           第三方脚本与许可证
tests/                            无需真实密钥的自动测试
docs/                             开发流程与来源说明
```

原“原始提取记录”页面用于开发排查，会显示尚未经过筛选的模型候选，容易与正式结果混淆，因此已移除该页面及下载/启动接口。原始文件保留在本地供追溯。每篇论文的 `report.json` 是未经人工判定的**原始候选**；`source.md` 是字面引文定位基准；`experiments.jsonl` 和 `experiments.xlsx` 便于脚本及人工审查。`claim_review.json` 单独保存角色复核决定与分子身份，`evidence_cards.json` 保存从全文重新关联的实验卡及每个参数的原文。它们绑定全文、关键候选字段和已通过名称，避免复用其他版本的结果；模型原始响应也保留供审查。Chang 2016 的 `report.revalidated.json` 是先前保留的字面核验副本，不直接进入页面。原始 `report.json` 不覆盖。模型缓存、结构缓存、论文、输出和 `.env` 均被 `.gitignore` 排除。

需要对已有报告重新复核时，在项目根目录运行（使用 `.env` 的模型，可能产生 API 费用）：

```bash
.conda/SenoMiner_AI/bin/python -m chem_pdf_extractor.claim_review --output-root output --workers 2
```

该命令复用同源、同规则的成功复核缓存；失败的复核会重试。具体参考的文献精读项目和备份逻辑见 [开发说明](docs/开发说明.md)。



这个系统把文献检索、实验抽取、数据库增强和证据展示串联起来，解决“同一篇论文的不同终点被当成独立实验”的展示问题。它采用论文和队列作为边界，不能把 Fisetin 动物/离体数据混成 2019 年 D+Q 人体试验的证据。自动分组、图号识别、模型语义标签、PDF 转文字和引文修复仍可能漏报或误归组；目前没有人工 Gold 数据，不能宣称提取召回率或精确率，也不能把它当作直接可复现实验方案。

更详细的字段、接口、示例纠错和扩展方式见 [开发说明](docs/开发说明.md)。

## 网络报错与重试

项目文件夹改名后，Conda 的编译时默认证书路径可能仍指向旧文件夹，引发 `CERTIFICATE_VERIFY_FAILED`；旧提示会将它包装成 `Cloud API/network temporarily unavailable after retries.`。程序现使用原虚拟环境中的 `certifi 2026.10.23` CA 文件，保持主机名与证书校验，不需要关闭 HTTPS 校验或重建环境。显式配置的 `SSL_CERT_FILE` / `SSL_CERT_DIR` 仍优先，需由其配置者保证有效。

普通网络超时会有限重试；只有结构化响应不完整才拆分片段，网络故障不会递归拆分并放大请求。成功片段保存在该论文的 `extraction_cache/`，再次提取时复用。原始报告保存后，如果全文核对或实验关联失败，任务仍显示失败并允许继续，不会误标完成。

## 开发检查

```bash
.conda/SenoMiner_AI/bin/python -m pip check
.conda/SenoMiner_AI/bin/python -m unittest discover -s tests -v
.conda/SenoMiner_AI/bin/python -m chem_pdf_extractor --help
.conda/SenoMiner_AI/bin/python -m chem_pdf_extractor.biomedical --help
git diff --check
```
