# 项目整体流程与实现状态

本图依据项目经历描述整理。当前演示仓库直接提供“JSON 校验与导入 → Neo4j → Web 搜索与图谱探索”；上游解析、抽取和 Gephi 检查的代码及证据需要从原项目/服务器补充。题目解析与本地向量检索尚未接入本演示。

## 完整流程图

```mermaid
flowchart TD
    A[物理教材 PDF] --> B[MinerU 解析为 Markdown]
    B --> C[GraphRAG-more 方案探索<br/>模型、Prompt、实体关系及查询测试]
    C --> D[针对物理领域问题调整方案]
    B --> E[PhyKgraph 按章节与文本块处理]
    D --> E
    E --> F[LLM 抽取物理实体与关系]
    F --> G[规则校验、重复实体合并<br/>统一实体 ID 与关系]
    G --> H[结构化 entities + edges JSON]
    H --> I[GEXF → Gephi 结构检查]
    H --> J[示例 JSON 校验与导入]
    J --> K[Neo4j]
    K --> L[Web 查询与展示<br/>搜索、详情、分级、一跳探索]

    H -.拟实现.-> M[组织知识点文本与实体 ID]
    M -.-> N[嵌入服务编码知识文本]
    N -.-> O[本地向量索引]
    P[用户输入物理题] -.-> Q[LLM 题目解析<br/>任务、已知量、待求量、相关概念]
    Q -.-> R[组织检索文本并编码]
    R -.-> S[语义相似度检索]
    O -.-> S
    S -.-> T[匹配当前图谱实体 ID]
    K -.-> U[Neo4j 关联节点与路径查询]
    T -.-> U
    U -.-> V[题目知识点定位与图谱上下文]

    classDef current fill:#dbeafe,stroke:#2563eb,color:#172554;
    classDef evidence fill:#f1f5f9,stroke:#64748b,color:#334155;
    classDef planned fill:#fff7ed,stroke:#ea580c,color:#7c2d12;
    class A,B,C,D,E,F,G,H,I evidence;
    class J,K,L current;
    class M,N,O,P,Q,R,S,T,U,V planned;
```

蓝色：本演示可运行的环节。灰色：项目整体经历，待补原项目代码与真实材料。橙色和虚线：待接入本演示的题目查询分支。

PaddleOCR 是解析阶段最初尝试的方案，可在技术选择说明中配双栏顺序案例，不必让主流程图同时展示两条生产输入线路。

旧流程中的 BGE-M3/LanceDB 若确有服务器实现，应另附对应代码与结果。当前演示拟采用远程嵌入服务与本地向量索引，模型尚未确定；因此此图暂不写具体模型或向量库产品名。

## 当前演示的真实请求流程

```mermaid
sequenceDiagram
    actor User as 用户
    participant Web as Vue / D3
    participant API as FastAPI
    participant DB as Neo4j
    User->>Web: 输入关键词，例如电荷
    Web->>API: GET /api/junior_demo/search
    API->>DB: 名称/描述模糊匹配
    DB-->>API: 候选实体
    API-->>Web: 候选列表
    User->>Web: 选择候选或点击图谱节点
    par 详情请求
        Web->>API: GET /api/junior_demo/node/{id}
        API->>DB: 节点属性和关联关系
        DB-->>API: 详情
        API-->>Web: 详情与关联节点
    and 一跳请求
        Web->>API: GET /api/junior_demo/graph?center_id=...&depth=1
        API->>DB: 一跳节点与真实关系
        DB-->>API: 邻域
        API-->>Web: 邻域数据
    end
    Web->>Web: 基础图谱加当前邻域，去重并替换临时补充
    Web-->>User: 高亮关联范围与节点详情
    User->>Web: 返回分级视图
    Web->>Web: 恢复缓存的基础图谱
```

## 阶段与证据

| 阶段 | 当前作品集状态 | 应补的真实材料 |
|---|---|---|
| PaddleOCR → MinerU 教材解析 | 根据项目经历描述整理 | 同一页教材与两种解析结果 |
| GraphRAG-more 探索 | 根据项目经历描述整理 | 模型/Prompt 版本、实际抽取与查询案例 |
| PhyKgraph 领域构建 | 示例 JSON 已获得并通过规则校验；本仓库未包含抽取引擎 | Markdown 文本块、抽取/合并/校验记录 |
| Gephi 图谱检查 | 根据项目经历描述整理 | GEXF 与 Gephi 截图 |
| Neo4j + Web 演示 | 当前仓库已实现 | 101/104、搜索、分级、一跳截图及运行验证 |
| 题目解析 + 语义检索 | 待接入当前演示 | 待实现 API、索引、实体映射与人工标注题目 |

“JSON 来源于 PhyKgraph output”与“可以复现该文件的全部生成过程”是不同程度的证据；作品集中按实际材料表述。
