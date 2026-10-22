# 初中物理知识图谱

这是一个个人开发并持续维护的初中物理知识图谱项目。我从教材中抽取知识实体与关系，清洗并统一数据，后来参考人教版 2024 年教材目录进行扩充。项目使用 FastAPI、Neo4j、Vue 3、Element Plus、D3 和 NumPy，提供图谱可视化、搜索、节点详情，以及题目解析到候选知识点的定位链路。

## 图谱数据

仓库包含 `data/junior_physics_2024.json`：**436 个节点、686 条有方向的关系**。原抽取图谱的 101 个实体 ID、名称和类型得以保留；新增教材册别、章、节和知识实体。题目向量检索只索引 319 个知识实体，不把 117 个目录节点当成候选知识点。

数据来源、抽取与 AI 辅助扩充过程，以及章节归属的核验边界见[数据说明](data/DATA_SOURCE.md)。知识点到节的映射主要是主题推定，不代表已按教材逐页核验。

## 运行

需要 Python 3.12、Node.js/npm，以及已启动的 Neo4j Desktop 实例。完整的可复制 PowerShell 命令见 [本机运行说明](docs/LOCAL_RUN.md)。

1. 使用已有 `.phyvenv`，安装 `backend/requirements.txt`；在 `frontend` 执行 `npm ci`。
2. 使用虚拟环境 Python 运行 `materials/import_phykgraph_json.py --configure`，在本机输入数据库密码。
3. 运行同一脚本导入初中物理 JSON。它使用新的 `junior_physics` 项目 ID，不删除旧图谱数据。
4. 在仓库根目录运行 `.\.phyvenv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 9000`。
5. 在 `frontend` 运行 `npm run dev -- --host 127.0.0.1`。

访问 http://127.0.0.1:5173/kgraph/graph?project=junior_physics 。后端接口文档：http://127.0.0.1:9000/docs 。

`backend/neo4j.example.json` 仅展示配置格式；真实配置由配置命令保存为 `backend/neo4j.local.json`。

## 搜索请求流程

输入至少两个字符，约 300 毫秒后调用 `/api/junior_physics/search` 获取候选。点击候选才调用 `/api/junior_physics/node/{node_id}` 获取详情，并高亮、定位该节点；每次选择都调用 `/api/junior_physics/graph?center_id=...&depth=1`，在当前基础分级图谱上补充一跳邻域，去重并替换上一次临时补充。可通过“返回分级视图”恢复。

例如搜索“电荷”会返回名称匹配的候选，可分别点击查看。开发时 `/api` 由 Vite 代理到 9000 端口。

## 题目知识点定位

独立页面 `/kgraph/question-locator` 支持输入题目或选择人工标注示例。实时模式使用火山方舟 LLM 生成经过 Pydantic 校验的结构化解析，再以相同模型和编码配置查询本地 NumPy 向量索引，最多返回五个候选。选择候选后通过路由进入图谱页，复用已有详情和一跳探索。教材章、节节点不参与候选排序。

真实 API Key 只保存在被 Git 忽略的 `backend/ai.local.json`。导入新图谱并启动 Neo4j 后，先运行 `.\.phyvenv\Scripts\python.exe materials\build_local_index.py --verify-only` 校验实体映射；确认付费调用量后，再使用 `--yes` 构建新索引。没有新索引时仍可使用明确标记的离线示例。

## 目录

- `backend/main.py`：FastAPI 接口及 Neo4j 查询。
- `frontend/src/views/GraphView.vue`：D3 图谱、搜索与详情交互。
- `data/junior_physics_2024.json`：初中物理实体和关系。
- `data/DATA_SOURCE.md`：来源、扩充过程与核验边界。
- `materials/import_phykgraph_json.py`：规则校验、配置、事务导入。
- `materials/verify_graph.py`：数据与 API 验证。
- `materials/build_local_index.py`：校验实体 ID 并构建本地向量索引。
- `materials/evaluate_question_locator.py`：人工标注题目的 Top-5 评测。

## 验证

后端启动后，在仓库根目录执行 `.\.phyvenv\Scripts\python.exe materials\verify_graph.py`，预期全部 PASS。前端构建在 `frontend` 执行 `npm run build`。

重复导入相同数据使用 MERGE，不增加重复节点和关系。导入不删除其他项目；更新 JSON 后删除的记录也不会自动从数据库删除。

## 项目来源与实现

项目最初以已有的 Kgraph 可视化代码为起点，我在此基础上持续整理和优化本地运行、图谱导入、查询交互与题目定位功能。图谱数据由我从教材解析结果中抽取和清洗，后续借助 AI 扩充；具体过程和核验边界见数据说明。

主要实现和整理内容包括：本机 Neo4j 配置、图谱数据校验与导入、真实关系展示、搜索候选和节点定位、节点详情与关联方向、验证脚本及运行文档。

服务默认仅监听回环地址；未提供登录鉴权，不直接作为公网服务部署。历史项目配置保留，本仓库当前提供 `junior_physics` 的数据。

早期 101 节点版本的整理差异和验证结果见 [历史发布验证记录](docs/RELEASE_CHECK.md)。
