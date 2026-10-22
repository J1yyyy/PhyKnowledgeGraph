# 初中物理知识图谱数据说明

`junior_physics_2024.json` 以我从初中物理教材中抽取的知识图谱为基础。我先使用 MinerU 将 PDF 教材解析为 Markdown，再借助大语言模型提取知识实体与关系，对结果进行清洗、去重和实体 ID 统一，整理成可导入 Neo4j 的 JSON。原图谱的 101 个实体 ID、名称和类型在本版中保留。

为了支持题目知识点到教材章节的定位，我后来借助 AI 扩充原图谱，参考人教版 2024 年新教材目录，补充年级、册别、章、节、知识点和公式，并修复部分关系。当前文件含 436 个实体、686 条关系；其中 117 个实体是册别、章、节目录节点，其余 319 个是知识实体。目录节点用于定位，不作为题目向量检索的候选知识点。

数据中的 `TAUGHT_IN` 表示知识实体到节的关联，`COVERED_IN_CHAPTER` 表示较宽泛知识点到章的关联；`BELONGS_TO` 连接节、章和册别。关系上的 `mapping_method` 与 `verification` 记录增强过程中的推定或复核标记。

## 来源边界

- 章、节名称参考增强文件列出的[八年级上册](https://www.renjiaoshe.com/jiaocai/3414.html)、[八年级下册](https://www.renjiaoshe.com/jiaocai/3415.html)和[九年级全一册](https://www.renjiaoshe.com/jiaocai/3416.html)目录。
- 知识点到具体节的归属主要按主题推定，标记为 `topic_inferred`；跨节补充关联标记为 `topic_inferred_secondary`。这些映射未依据教材 PDF 逐页核验，`source_pages` 为空，不能作为教材原文页码或逐页引用的证据。
- 新增知识点和公式是对原抽取图谱的 AI 辅助扩充，不应表述为全部直接从教材 PDF 抽取。题目检索得到的相似度也不是答案正确概率。

JSON 仅保留 `entities` 和 `edges`，以便导入与程序读取；以上来源、统计和限制由本说明记录。原始 PDF 和 Markdown 不包含在本仓库中。
