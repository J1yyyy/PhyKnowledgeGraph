# Windows 本机运行

本项目使用从初中物理教材中抽取并整理的图谱，包含 436 个节点、788 条关系。数据结构见 [数据说明](../data/DATA_SOURCE.md)。

随仓库提供 `data/junior_physics_2024.json`，不依赖原始桌面文件或服务器。以下命令使用 Windows PowerShell：在文件资源管理器中打开仓库文件夹，在地址栏输入 `powershell` 并回车，即可从仓库根目录执行命令。路径均相对于仓库根目录。

## 1. 依赖与数据库

打开 Neo4j Desktop 并启动本地实例，用户数据库默认 `neo4j`。

首次安装依赖：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend ci
```

作用：创建示例虚拟环境 `.venv`、安装后端依赖，并按锁文件安装前端依赖。已有其他虚拟环境时，将后续命令中的 Python 路径换成自己的解释器路径。

## 2. 本机配置

```powershell
.\.venv\Scripts\python.exe .\materials\import_phykgraph_json.py --configure
```

在仓库根目录执行。按提示输入 URI、用户名、数据库名和密码。默认 URI 为 `bolt://localhost:7687`，默认用户名及数据库名为 `neo4j`。实际配置以 Desktop 的实例信息为准。

密码输入不显示字符。配置保存在 `backend/neo4j.local.json`，已被现有 `.gitignore` 的 `*.local.json` 排除。环境变量 `NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD/NEO4J_DATABASE` 优先于本机配置。

如需实时解析题目，在仓库根目录复制 AI 配置模板，再在 `backend/ai.local.json` 中填写 API Key：

```powershell
Copy-Item backend\ai.example.json backend\ai.local.json
```

本机配置文件已被 Git 忽略；使用仓库附带的索引时，保持示例文件中的嵌入模型和向量维度配置。

## 3. 校验和导入

```powershell
.\.venv\Scripts\python.exe .\materials\import_phykgraph_json.py --validate-only
.\.venv\Scripts\python.exe .\materials\import_phykgraph_json.py
```

第一条不写数据库；第二条校验通过后写入。预期打印 436 个节点、788 条关系，以及相同的数据库统计。

导入使用 `JuniorPhysics2024` 标签和 `junior_physics:` ID 前缀，原 ID 保存为 `source_id`。

节点和关系使用 MERGE 写入一个事务；对同一份数据重复执行不会增加节点或关系。

## 4. 启动后端

在仓库根目录的一个 PowerShell 窗口执行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 9000
```

预期服务地址 `http://127.0.0.1:9000`，API 文档 `http://127.0.0.1:9000/docs`。窗口保持运行。若提示端口占用，先检查已经启动的本项目服务，不要重复启动。

## 5. 启动前端

另开一个 PowerShell 窗口，先进入仓库根目录，再执行：

```powershell
Set-Location frontend
npm.cmd run dev -- --host 127.0.0.1
```

访问 `http://127.0.0.1:5173/kgraph/`，选择“初中物理知识图谱”。完整图谱地址：`http://127.0.0.1:5173/kgraph/graph?project=junior_physics`。

默认级别为“全部节点”、显示范围为“知识实体”，预期显示 319 个知识节点、327 条节点之间的真实关系。切换到“含教材目录”后显示 436 个节点、788 条真实关系；核心和重要级别可独立选择。节点大小和级别仍按完整图谱的关联节点数计算。可以搜索“密度”、点击节点查看详情、拖动节点、缩放及导出图片。

### 搜索与定位

输入至少两个字符，停顿约 300 毫秒后显示候选列表，每项包含完整节点名称和类型。搜索“电荷”时精确名称优先，实际候选数以新图谱为准。搜索按钮或回车用于展开结果；选择候选后才打开详情。

点击画布节点、搜索候选或详情中的关联节点，前端都会同时查询节点详情和按 ID 的一跳邻域。选中节点以橙色描边显示，一跳邻居正常显示，其余背景节点淡化；视图缩放到能显示当前一跳范围。右侧详情面板不遮罩整张图，可以继续操作搜索框。

全部、重要、核心都保留当前基础分级图谱，再补充当前选中节点的一跳邻域。“知识实体”范围也会过滤一跳中的教材目录节点及关联边；搜索或详情中明确选择教材节点时，自动切到“含教材目录”后定位。已存在的节点和同类型、同方向的关系去重，已有节点坐标保留。每次选择从基础图谱重新合并，替换上一次临时补充的邻域，不逐次累积。统计栏显示基础和临时补充节点数量；点击“返回分级视图”或切换级别可恢复基础图谱。

关联节点可以继续点击定位。方向箭头表示关系相对当前节点的方向。

在浏览器开发者工具 Network 中清除过滤框内容并选择 Fetch/XHR，可以观察：

- 输入关键词：`/api/junior_physics/search?keyword=...`。
- 选择节点：`/api/junior_physics/node/junior_physics%3AG_NODE_...`。
- 每次选择节点：`/api/junior_physics/graph?center_id=...&depth=1`。

浏览器显示请求地址为前端的 5173 端口是正常的，Vite 会将 `/api` 转发到后端 9000 端口。候选数最多显示 20 条；快速输入时旧请求不会覆盖新关键词的结果。

## 6. 验证

在仓库根目录的 PowerShell 窗口执行：

```powershell
.\.venv\Scripts\python.exe .\materials\verify_graph.py
```

需要后端运行。它检查每个节点的名称/类型、每条真实三元组、搜索、节点详情、类型过滤、二跳子图和错误响应。预期全部打印 PASS。

仓库附带 `data/generated/junior_physics_embeddings.npz`，已包含当前 319 个知识实体的向量。使用当前 JSON 和示例模型配置时，无需重新构建索引。导入图谱并启动 Neo4j 后，可在仓库根目录只读核对实体 ID：

```powershell
.\.venv\Scripts\python.exe .\materials\build_local_index.py --verify-only
```

该命令核对 JSON 原 ID 与 Neo4j 中 `junior_physics:` 前缀 ID，不调用模型。若更换知识实体文本或嵌入模型，先导入更新后的 JSON，并在本机 AI 配置中填写对应模型和维度；确认付费调用后执行：

```powershell
.\.venv\Scripts\python.exe .\materials\build_local_index.py --yes
```

脚本会报告预计需要编码的知识实体数，缺失向量会调用付费嵌入 API；费用取决于模型与实际调用量。117 个目录节点不编码。访问 `http://127.0.0.1:5173/kgraph/question-locator` 使用题目定位页面。离线示例不调用模型，也不代表实时检索效果。

若只调整 JSON 中的关系，而知识实体 ID、名称、类型和模型配置均未改变，可以运行 `.\.venv\Scripts\python.exe .\materials\build_local_index.py --reuse-only`，离线复用已有向量并更新源文件指纹。

题目结果页点击任一候选，图谱页保留最多 5 个候选，并按关系类型、候选相似度和题目解析内容筛选、排序，最多补充 8 个真实一跳知识节点。点击节点只切换详情，不会加入完整一跳邻域。通过“返回题目与解析结果”可回到原题和候选；结果只保存在当前浏览器标签页，关闭标签页后不保留。通过“查看普通图谱”进入分级视图与一跳探索。图谱覆盖不足时不自动补充邻居；候选可能互不连线。

在 Neo4j Query 中分别执行（不是 PowerShell）：

```cypher
MATCH (n:JuniorPhysics2024) RETURN count(n) AS nodes;
```

```cypher
MATCH (:JuniorPhysics2024)-[r]->(:JuniorPhysics2024)
RETURN type(r) AS relation, count(*) AS count
ORDER BY count DESC;
```

预期节点 436、关系总数 788；其中 `TAUGHT_IN` 336、`BELONGS_TO` 114。完整关系分布以 JSON 校验输出为准。

```cypher
MATCH (a:JuniorPhysics2024)-[r]->(b:JuniorPhysics2024)
RETURN a, r, b LIMIT 25;
```

用于查看真实连线。停止前后端时，在对应 PowerShell 窗口按 Ctrl+C；停止 Desktop 实例不会清空已保存数据。


## 图谱展示说明

图谱页使用剩余窗口空间，隐藏页脚，画布随窗口尺寸调整。默认隐藏关系文字以减少拥挤，可勾选“显示关系名称”；连线和方向箭头始终保留。

节点颜色固定表示实体类型，画布上方提供中文图例；节点大小按完整项目图谱中直接关联的不同节点数量计算，半径限制为 6～14 像素，不表示重要程度。补充邻域时使用相同的完整图谱关联数量；选中的节点以橙色描边突出显示。

只有初中物理知识图谱开放。其他项目保留名称并标注“未开放”，首页、项目管理和图谱下拉框均禁止进入；直接访问未开放项目的图谱页面显示提示。

后端代码变更后需要重新启动后端；Vite 开发服务通常自动更新前端，必要时刷新浏览器。


### 分级筛选规则

关联节点数是完整项目中直接相连的不同节点数量，合并入向和出向连接，同一邻居只计一次。核心筛选关联节点数 ≥5，重要筛选 ≥2，全部不按关联数量过滤；新图谱包含教材目录关系，层级数量须以导入后的实际统计为准，关联数不表示知识重要性。

前端仍保留加载上限：核心 100、重要 500、全部 1000；这些是数量上限，不是分级阈值。未选点时，每层只显示该层节点之间的真实关系；选点后保留基础图谱并补充一跳节点和真实关系。


### 一跳探索验收

1. 切换“核心节点”，记录基础节点与真实关系数。
2. 搜索并选择“密度”，确认保留基础图且只补充当前一跳邻域；详情能够打开。
3. 改选另一个知识点，确认上一节点的临时邻域不继续累积。
4. 点击“返回分级视图”，确认恢复原基础节点与关系数。
5. 在“全部节点”选择已有节点，确认高亮和一跳关系可用且节点不重复。
