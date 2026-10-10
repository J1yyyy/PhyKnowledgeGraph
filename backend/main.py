#!/usr/bin/env python3
"""
Kgraph 多项目知识图谱后端 API
支持：Physics, Curriculum, Materials 等多个项目的图谱数据

架构：FastAPI + Neo4j
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import json
from pathlib import Path

# ==================== 配置 ====================
LOCAL_CONFIG_FILE = Path(__file__).parent / "neo4j.local.json"
LOCAL_CONFIG = json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")) if LOCAL_CONFIG_FILE.exists() else {}
NEO4J_URI = os.getenv("NEO4J_URI", LOCAL_CONFIG.get("uri", "bolt://localhost:7687"))
NEO4J_USER = os.getenv("NEO4J_USER", LOCAL_CONFIG.get("user", "neo4j"))
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", LOCAL_CONFIG.get("password"))
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", LOCAL_CONFIG.get("database", "neo4j"))
if not NEO4J_PASSWORD:
    raise RuntimeError("缺少 Neo4j 密码：请运行 materials/import_phykgraph_json.py --configure，或设置 NEO4J_PASSWORD 环境变量")

# 项目配置（支持多个图谱项目）
PROJECTS = {
    "junior_demo": {
        "name": "初中物理演示图谱",
        "available": True,
        "neo4j_label": "DemoJuniorPhysics",
        "description": "PhyKgraph 示例数据：101 个节点、104 条语义关系"
    },
    "physics": {
        "name": "Physics 知识图谱",
        "neo4j_label": "Physics",  # 使用 Neo4j 存储
        "description": "高中/大学物理学知识图谱"
    },
    "curriculum": {
        "name": "Curriculum 知识图谱",
        "neo4j_label": "Curriculum",  # 使用 Neo4j 存储
        "description": "初中物理课程标准知识图谱"
    },
    "materials": {
        "name": "Materials 知识图谱",
        "neo4j_label": "Entity",  # Materials 使用 Neo4j 存储
        "description": "材料科学知识图谱"
    }
}

BASE_DIR = Path(__file__).parent
app = FastAPI(
    title="Kgraph API",
    description="多项目知识图谱后端 API",
    version="2.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境改为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== Neo4j 客户端 ====================
class Neo4jClient:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.connected = False
        try:
            # 测试连接
            self.driver.verify_connectivity()
            self.connected = True
            print(f"Neo4j 连接成功：{uri}")
        except Exception as e:
            print(f"Neo4j 连接失败：{e}")

    def close(self):
        self.driver.close()

    def query(self, query: str, parameters: Dict = None):
        """执行 Cypher 查询"""
        try:
            with self.driver.session(database=NEO4J_DATABASE) as session:
                result = [record.data() for record in session.run(query, parameters)]
            self.connected = True
            return result
        except (Neo4jError, ServiceUnavailable) as error:
            self.connected = False
            raise HTTPException(status_code=503, detail="Neo4j 查询失败，请检查数据库运行状态和本机配置") from error

    def check_connection(self):
        try:
            self.driver.verify_connectivity()
            self.connected = True
        except (Neo4jError, ServiceUnavailable):
            self.connected = False
        return self.connected

    def get_stats(self, label: str = "Entity"):
        """获取图谱统计"""
        query = f"""
        MATCH (n:{label})
        WITH count(n) as node_count
        OPTIONAL MATCH (:{label})-[r]->(:{label})
        RETURN node_count, count(r) as rel_count
        """
        result = self.query(query)
        return result[0] if result else {}

    def get_nodes(self, label: str, limit: int = 100, level: Optional[str] = None, node_type: Optional[str] = None):
        """获取节点列表"""
        query = f"""
        MATCH (n:{label})
        WHERE $node_type IS NULL OR coalesce(n.type, n.group) = $node_type
        OPTIONAL MATCH (n)--(m:{label})
        WITH n, count(DISTINCT m) AS degree
        WHERE ($level <> 'core' OR degree >= 5)
          AND ($level <> 'important' OR degree >= 2)
        RETURN n.id as id, coalesce(n.title, n.name, n.label) as label,
               coalesce(n.type, n.group, 'Unknown') as type,
               n.description as description, n.human_readable_id as hr_id, degree,
               n.source_id as source_id
        ORDER BY degree DESC, id
        LIMIT $limit
        """
        return self.query(query, {"limit": limit, "level": level or "all", "node_type": node_type})

    def get_graph(self, center_node: Optional[str], depth: int = 1, label: str = "Entity", limit: int = 100, level: Optional[str] = None, center_id: Optional[str] = None):
        """获取子图"""
        if center_id or center_node:
            # 长度边界来自 API 的 1..3 校验，不把用户文本插入 Cypher。
            depth = max(1, min(3, depth))
            nodes = self.query(f"""
                MATCH (center:{label})
                WHERE ($center_id IS NOT NULL AND center.id = $center_id)
                   OR ($center_id IS NULL AND coalesce(center.title, center.name, center.label) CONTAINS $center_node)
                MATCH path = (center)-[*0..{depth}]-(n:{label})
                WHERE all(item IN nodes(path) WHERE item:{label})
                WITH DISTINCT n
                ORDER BY CASE WHEN n.id = $center_id THEN 0 ELSE 1 END, n.id LIMIT $limit
                OPTIONAL MATCH (n)--(neighbor:{label})
                WITH n, count(DISTINCT neighbor) AS degree
                RETURN n.id AS id, coalesce(n.title, n.name, n.label) AS label,
                       coalesce(n.type, n.group, 'Unknown') AS type, n.description AS description,
                       n.source_id AS source_id, degree
                ORDER BY CASE WHEN n.id = $center_id THEN 0 ELSE 1 END, id LIMIT $limit
            """, {"center_id": center_id, "center_node": center_node, "limit": limit})
        else:
            nodes = self.get_nodes(label, limit, level)
        ids = [node["id"] for node in nodes]
        edges = self.query(f"""
            MATCH (a:{label})-[r]->(b:{label})
            WHERE a.id IN $ids AND b.id IN $ids
            RETURN a.id AS from, b.id AS to, type(r) AS relation_type,
                   coalesce(r.relation_type, r.description, type(r)) AS label
            ORDER BY from, to, relation_type
        """, {"ids": ids}) if ids else []
        return {"nodes": nodes, "edges": edges}

    def search_nodes(self, keyword: str, label: str = "Entity", limit: int = 20):
        """搜索节点"""
        query = f"""
        MATCH (n:{label})
        WHERE coalesce(n.title, n.name, n.label) CONTAINS $keyword OR n.description CONTAINS $keyword
        RETURN n.id as id, coalesce(n.title, n.name, n.label) as label,
               coalesce(n.type, n.group, 'Unknown') as type, n.description as description
        ORDER BY CASE WHEN label = $keyword THEN 0 WHEN label STARTS WITH $keyword THEN 1 ELSE 2 END, label, id
        LIMIT $limit
        """
        return self.query(query, {"keyword": keyword, "limit": limit})

    def get_node_types(self, label: str = "Entity"):
        """获取节点类型分布"""
        query = f"""
        MATCH (n:{label})
        RETURN coalesce(n.type, n.group, 'Unknown') as type, count(n) as count
        ORDER BY count DESC
        """
        return self.query(query)

# 初始化 Neo4j 客户端
neo4j_client = Neo4jClient(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)


def get_project_config(project_id):
    """统一检查项目和数据源，数据库离线时返回明确错误。"""
    if project_id not in PROJECTS:
        raise HTTPException(status_code=404, detail="项目不存在")
    project = PROJECTS[project_id]
    if "neo4j_label" in project and not neo4j_client.connected and not neo4j_client.check_connection():
        raise HTTPException(status_code=503, detail="Neo4j 未连接，请启动本地实例并检查配置")
    return project

# ==================== 数据模型 ====================
class Node(BaseModel):
    id: str
    label: str
    type: Optional[str] = None
    description: Optional[str] = None

class Edge(BaseModel):
    from_id: str
    to_id: str
    label: Optional[str] = None

# ==================== API 接口 ====================

@app.get("/")
async def root():
    """API 首页"""
    return {
        "message": "Kgraph API - 多项目知识图谱后端",
        "version": "2.0.0",
        "projects": list(PROJECTS.keys()),
        "neo4j_connected": neo4j_client.check_connection(),
        "docs": "/docs"
    }


@app.get("/api/health")
async def health():
    """供前端检测后端和数据库连接状态。"""
    return {"api_status": "ok", "neo4j_connected": neo4j_client.check_connection()}

@app.get("/api/projects")
async def get_projects():
    """获取所有项目列表"""
    return {
        "projects": [
            {
                "id": pid,
                "name": info["name"],
                "description": info["description"],
                "source": "neo4j" if "neo4j_label" in info else "json",
                "available": info.get("available", False)
            }
            for pid, info in PROJECTS.items()
        ]
    }

@app.get("/api/{project_id}/stats")
async def get_project_stats(project_id: str):
    """获取项目统计信息"""
    project = get_project_config(project_id)

    # 如果是 Neo4j 数据源
    if "neo4j_label" in project and neo4j_client.connected:
        stats = neo4j_client.get_stats(project["neo4j_label"])
        types = neo4j_client.get_node_types(project["neo4j_label"])
        return {
            "project_id": project_id,
            "project_name": project["name"],
            "total_nodes": stats.get("node_count", 0),
            "total_edges": stats.get("rel_count", 0),
            "by_type": types,
            "source": "neo4j"
        }

    # 如果是 JSON 数据源（兼容旧版）
    data_file = BASE_DIR / project["data_file"]
    if data_file.exists():
        with open(data_file, 'r', encoding='utf-8') as f:
            nodes = json.load(f)

        edges_file = data_file.parent / f"edges_{project_id.split('_')[0] if '_' in project_id else project_id}.json"
        edges = []
        if edges_file.exists():
            with open(edges_file, 'r', encoding='utf-8') as f:
                edges = json.load(f)

        # 按类型统计
        type_count = {}
        for node in nodes:
            node_type = node.get('type', node.get('group', 'Unknown'))
            type_count[node_type] = type_count.get(node_type, 0) + 1

        return {
            "project_id": project_id,
            "project_name": project["name"],
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "by_type": type_count
        }

    raise HTTPException(status_code=404, detail="数据文件不存在")

@app.get("/api/{project_id}/nodes")
async def get_nodes(
    project_id: str,
    limit: int = Query(100, ge=1, le=1000),
    node_type: Optional[str] = None,
    level: Optional[str] = Query(None, description="分级：core, important, all")
):
    """获取节点列表（支持分级）"""
    project = get_project_config(project_id)

    # Neo4j 数据源
    if "neo4j_label" in project and neo4j_client.connected:
        nodes = neo4j_client.get_nodes(project["neo4j_label"], limit, level, node_type)

        return {"count": len(nodes), "nodes": nodes, "level": level or "all"}

    # JSON 数据源（兼容旧版）
    data_file = BASE_DIR / project["data_file"]
    if data_file.exists():
        with open(data_file, 'r', encoding='utf-8') as f:
            nodes = json.load(f)

        # 按类型过滤
        if node_type:
            nodes = [n for n in nodes if n.get('type') == node_type or n.get('group') == node_type]

        # 分级过滤（按 value 字段，即连接数）
        if level:
            if level == 'core':
                nodes = [n for n in nodes if n.get('value', 0) >= 5]
            elif level == 'important':
                nodes = [n for n in nodes if n.get('value', 0) >= 2]

        # 按连接数排序
        nodes = sorted(nodes, key=lambda x: x.get('value', 0), reverse=True)

        # 限制数量
        nodes = nodes[:limit]
        return {"count": len(nodes), "nodes": nodes, "level": level or "all"}

    raise HTTPException(status_code=404, detail="数据文件不存在")

@app.get("/api/{project_id}/graph")
async def get_graph(
    project_id: str,
    center_node: Optional[str] = Query(None, description="中心节点关键词；不传时返回分级图谱"),
    depth: int = Query(1, ge=1, le=3),
    limit: int = Query(100, ge=1, le=1000),
    level: Optional[str] = Query(None, pattern="^(core|important|all)$"),
    center_id: Optional[str] = Query(None, min_length=1, description="精确节点 ID；优先于中心节点关键词")
):
    """获取子图（用于可视化）"""
    project = get_project_config(project_id)

    # Neo4j 数据源
    if "neo4j_label" in project and neo4j_client.connected:
        graph = neo4j_client.get_graph(center_node, depth, project["neo4j_label"], limit, level, center_id)
        return graph

    # JSON 数据源（简化实现：返回所有数据）
    raise HTTPException(status_code=400, detail="该项目不支持子图查询，请使用 Neo4j 数据源")

@app.get("/api/{project_id}/search")
async def search_nodes(
    project_id: str,
    keyword: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=100)
):
    """搜索节点"""
    project = get_project_config(project_id)

    # Neo4j 数据源
    if "neo4j_label" in project and neo4j_client.connected:
        results = neo4j_client.search_nodes(keyword, project["neo4j_label"], limit)
        return {"query": keyword, "count": len(results), "results": results}

    # JSON 数据源（兼容旧版）
    data_file = BASE_DIR / project["data_file"]
    if data_file.exists():
        with open(data_file, 'r', encoding='utf-8') as f:
            nodes = json.load(f)

        keyword_lower = keyword.lower()
        results = []
        for node in nodes:
            label = node.get('label', node.get('title', '')).lower()
            node_type = node.get('type', node.get('group', '')).lower()
            if keyword_lower in label or keyword_lower in node_type:
                results.append(node)
                if len(results) >= limit:
                    break

        return {"query": keyword, "count": len(results), "results": results}

    raise HTTPException(status_code=404, detail="数据文件不存在")

@app.get("/api/{project_id}/types")
async def get_node_types(project_id: str):
    """获取节点类型分布"""
    project = get_project_config(project_id)

    # Neo4j 数据源
    if "neo4j_label" in project and neo4j_client.connected:
        types = neo4j_client.get_node_types(project["neo4j_label"])
        return {"types": types}

    # JSON 数据源
    data_file = BASE_DIR / project["data_file"]
    if data_file.exists():
        with open(data_file, 'r', encoding='utf-8') as f:
            nodes = json.load(f)

        type_count = {}
        for node in nodes:
            node_type = node.get('type', node.get('group', 'Unknown'))
            type_count[node_type] = type_count.get(node_type, 0) + 1

        types = [{"type": k, "count": v} for k, v in sorted(type_count.items(), key=lambda x: x[1], reverse=True)]
        return {"types": types}

    raise HTTPException(status_code=404, detail="数据文件不存在")

@app.get("/api/{project_id}/node/{node_id}")
async def get_node_detail(project_id: str, node_id: str):
    """获取节点详情"""
    project = get_project_config(project_id)

    # Neo4j 数据源
    if "neo4j_label" in project and neo4j_client.connected:
        query = f"""
        MATCH (n:{project['neo4j_label']} {{id: $id}})
        OPTIONAL MATCH (n)-[r]-(neighbor:{project['neo4j_label']})
        RETURN properties(n) AS n,
               [item IN collect(DISTINCT CASE WHEN r IS NOT NULL THEN {{
                   relationship: {{type: type(r), properties: properties(r),
                                  source_id: startNode(r).id, target_id: endNode(r).id}},
                   neighbor: properties(neighbor)
               }} END) WHERE item IS NOT NULL] AS connections
        """
        result = neo4j_client.query(query, {"id": node_id})
        if result:
            return result[0]
        raise HTTPException(status_code=404, detail="节点不存在")

    # JSON 数据源
    data_file = BASE_DIR / project["data_file"]
    if data_file.exists():
        with open(data_file, 'r', encoding='utf-8') as f:
            nodes = json.load(f)

        for node in nodes:
            if str(node.get('id')) == str(node_id):
                return {"node": node}

        raise HTTPException(status_code=404, detail="节点不存在")

    raise HTTPException(status_code=404, detail="数据文件不存在")

# ==================== 前端路由 ====================

@app.get("/frontend")
async def serve_frontend():
    """提供前端页面"""
    return FileResponse(BASE_DIR / "frontend" / "index.html")

@app.get("/frontend/{path:path}")
async def serve_frontend_static(path: str):
    """提供前端静态资源"""
    file_path = BASE_DIR / "frontend" / path
    if file_path.exists():
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="文件不存在")

# ==================== 生命周期 ====================

@app.on_event("shutdown")
async def shutdown_db():
    """关闭数据库连接"""
    neo4j_client.close()

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("Kgraph API 服务器启动中...")
    print("=" * 60)
    print(f"支持项目：{list(PROJECTS.keys())}")
    print(f"Neo4j: {NEO4J_URI}")
    print("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=9000)
