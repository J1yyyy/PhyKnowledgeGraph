# Windows 本机演示

演示数据：PhyKgraph 初中物理图谱，101 个节点、104 条关系。它是独立示例，不能称为旧版 38,942 节点图谱的已证实子集。

随仓库提供 `data/demo_junior_physics.json`，不依赖原始桌面文件或服务器。以下命令假设项目放在 `D:\Desktop\new-project\physics-knowledge-graph-demo`，其他位置请替换路径。

以下命令全部在 **Windows PowerShell** 中执行。提示符应是 `PS ...>`，不是 Python 的 `>>>`。如果已经进入 Python 交互模式，先输入 `exit()`。

## 1. 依赖与数据库

打开 Neo4j Desktop 并启动本地实例，用户数据库默认 `neo4j`。

首次安装依赖：

```powershell
Set-Location 'D:\Desktop\new-project\physics-knowledge-graph-demo'
py -3.12 -m venv .venv
& 'D:\Desktop\new-project\physics-knowledge-graph-demo\.venv\Scripts\python.exe' -m pip install -r backend\requirements.txt
Set-Location 'D:\Desktop\new-project\physics-knowledge-graph-demo\frontend'
npm.cmd ci
```

作用：建立独立 Python 环境，安装已有后端依赖和锁文件指定的前端依赖。本次如果已安装成功，不必重复执行。

## 2. 本机配置

```powershell
& 'D:\Desktop\new-project\physics-knowledge-graph-demo\.venv\Scripts\python.exe' 'D:\Desktop\new-project\physics-knowledge-graph-demo\materials\import_phykgraph_json.py' --configure
```

在任意目录执行均可。按提示输入 URI、用户名、数据库名和密码。默认 URI 为 `bolt://localhost:7687`，默认用户名及数据库名为 `neo4j`。实际配置以 Desktop 的实例信息为准。

密码输入不显示字符。配置保存在 `backend/neo4j.local.json`，已被现有 `.gitignore` 的 `*.local.json` 排除。环境变量 `NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD/NEO4J_DATABASE` 优先于本机配置。

## 3. 校验和导入

```powershell
& 'D:\Desktop\new-project\physics-knowledge-graph-demo\.venv\Scripts\python.exe' 'D:\Desktop\new-project\physics-knowledge-graph-demo\materials\import_phykgraph_json.py' --validate-only
& 'D:\Desktop\new-project\physics-knowledge-graph-demo\.venv\Scripts\python.exe' 'D:\Desktop\new-project\physics-knowledge-graph-demo\materials\import_phykgraph_json.py'
```

第一条不写数据库；第二条校验通过后写入。预期打印 101 个节点、104 条关系，以及相同的数据库统计。

导入使用 `DemoJuniorPhysics` 标签和 `junior_demo:` ID 前缀，原 ID 保存为 `source_id`。保留四种真实关系：`PARENT_CHILD`、`CONTAINS_VARIABLE`、`PREREQUISITE`、`APPLICABLE_UNDER`。

节点和关系使用 MERGE 写入一个事务；对同一份数据重复执行不会增加节点或关系。导入不删除其他项目，也不自动删除文件更新后消失的旧记录。不要把不同图谱共用同一套标签和项目 ID。

## 4. 启动后端

在一个 PowerShell 窗口执行：

```powershell
Set-Location 'D:\Desktop\new-project\physics-knowledge-graph-demo'
& 'D:\Desktop\new-project\physics-knowledge-graph-demo\.venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 9000
```

预期服务地址 `http://127.0.0.1:9000`，API 文档 `http://127.0.0.1:9000/docs`。窗口保持运行。若提示端口占用，先检查已经启动的本项目服务，不要重复启动。

## 5. 启动前端

在另一个 PowerShell 窗口执行：

```powershell
Set-Location 'D:\Desktop\new-project\physics-knowledge-graph-demo\frontend'
npm.cmd run dev -- --host 127.0.0.1
```

访问 `http://127.0.0.1:5173/kgraph/`，选择“初中物理演示图谱”。完整图谱地址：`http://127.0.0.1:5173/kgraph/graph?project=junior_demo`。

默认“全部节点”，预期 101 个节点、104 条真实关系。核心/重要级别只显示选中节点及其之间的关系。可以搜索“密度”、点击节点查看详情、拖动节点、缩放及导出图片。

### 搜索与定位

输入至少两个字符，停顿约 300 毫秒后显示候选列表，每项包含完整节点名称和类型。搜索“电荷”会显示五个候选，“电荷”本身排在前面。搜索按钮或回车用于展开结果；选择候选后才打开详情，不会自动只显示第一个结果。

点击候选后，前端调用 `/api/{project_id}/node/{node_id}` 获取真实属性和关联节点，并平移、缩放及高亮选中的节点。右侧详情面板不遮罩整张图，可以继续操作搜索框。

如果选中的节点不在当前核心/重要级别中，加载该节点的一跳邻域，状态栏明确显示“当前显示：节点一跳邻域”。重新选择显示级别可恢复正常图谱。

关联节点可以继续点击定位。方向箭头表示关系相对当前节点的方向。

在浏览器开发者工具 Network 中清除过滤框内容并选择 Fetch/XHR，可以观察：

- 输入关键词：`/api/junior_demo/search?keyword=...`。
- 选择节点：`/api/junior_demo/node/junior_demo%3AG_NODE_...`。
- 当前图中缺少该节点：`/api/junior_demo/graph?center_id=...&depth=1`。

浏览器显示请求地址为前端的 5173 端口是正常的，Vite 会将 `/api` 转发到后端 9000 端口。候选数最多显示 20 条；快速输入时旧请求不会覆盖新关键词的结果。

历史项目配置仍保留；本机尚未导入 Physics、Curriculum、Materials 的历史数据，其统计为空不代表演示导入失败。

## 6. 验证

在任意 PowerShell 目录执行：

```powershell
& 'D:\Desktop\new-project\physics-knowledge-graph-demo\.venv\Scripts\python.exe' 'D:\Desktop\new-project\physics-knowledge-graph-demo\materials\verify_demo.py'
```

需要后端运行。它检查每个节点的名称/类型、每条真实三元组、搜索、节点详情、类型过滤、二跳子图和错误响应。预期全部打印 PASS。

在 Neo4j Query 中分别执行（不是 PowerShell）：

```cypher
MATCH (n:DemoJuniorPhysics) RETURN count(n) AS nodes;
```

```cypher
MATCH (:DemoJuniorPhysics)-[r]->(:DemoJuniorPhysics)
RETURN type(r) AS relation, count(*) AS count
ORDER BY count DESC;
```

预期节点 101；关系分别为 PARENT_CHILD 82、CONTAINS_VARIABLE 11、PREREQUISITE 7、APPLICABLE_UNDER 4。

```cypher
MATCH (a:DemoJuniorPhysics)-[r]->(b:DemoJuniorPhysics)
RETURN a, r, b LIMIT 25;
```

用于查看真实连线。停止前后端时，在对应 PowerShell 窗口按 Ctrl+C；停止 Desktop 实例不会清空已保存数据。
