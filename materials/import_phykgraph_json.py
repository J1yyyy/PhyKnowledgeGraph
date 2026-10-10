"""校验并导入 PhyKgraph 原生 JSON；原文件不修改，项目 ID 隔离。"""
import argparse
from collections import Counter
from getpass import getpass
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "backend" / "neo4j.local.json"
ENTITY_TYPES = {
    "PHYSICS_CONCEPT", "LAW_OR_PRINCIPLE", "FORMULA", "CONSTANT",
    "PHYSICS_MODEL", "PHENOMENON", "CONDITION", "TYPICAL_SCENARIO",
    "METHOD", "MISCONCEPTION", "MATH_TOOL", "PHYSICAL_QUANTITY", "EXPERIMENT",
}
# 对应 PhyKgraph src/phykgraph/core/validator.py 的源类型、目标类型限制。
RELATION_RULES = {
    "PREREQUISITE": None,
    "PARENT_CHILD": None,
    "DERIVED_FROM": ({"FORMULA"}, {"LAW_OR_PRINCIPLE", "FORMULA"}),
    "APPLICABLE_UNDER": ({"LAW_OR_PRINCIPLE", "FORMULA"}, {"CONDITION", "PHYSICS_MODEL"}),
    "EXPLAINS": ({"LAW_OR_PRINCIPLE"}, {"PHENOMENON"}),
    "MODELLED_BY": ({"PHENOMENON", "TYPICAL_SCENARIO"}, {"PHYSICS_MODEL"}),
    "CONTAINS_VARIABLE": ({"FORMULA"}, {"PHYSICAL_QUANTITY", "CONSTANT"}),
    "MATHEMATICAL_LINK": ({"FORMULA"}, {"FORMULA"}),
    "EXPRESSED_IN": ({"PHYSICAL_QUANTITY", "LAW_OR_PRINCIPLE"}, {"MATH_TOOL"}),
    "EMPLOY_METHOD": ({"TYPICAL_SCENARIO", "PHENOMENON"}, {"METHOD"}),
    "IMPLEMENTED_BY": ({"METHOD"}, {"MATH_TOOL"}),
    "CONFUSED_WITH": ({"PHYSICS_CONCEPT", "PHYSICAL_QUANTITY"}, {"PHYSICS_CONCEPT", "PHYSICAL_QUANTITY"}),
    "CORRECTS": ({"LAW_OR_PRINCIPLE", "PHYSICS_CONCEPT"}, {"MISCONCEPTION"}),
    "VERIFIES": ({"EXPERIMENT"}, {"LAW_OR_PRINCIPLE", "PHENOMENON"}),
}


def validate_graph(data):
    """检查完整图谱；发现问题则停止，避免静默丢弃数据。"""
    if not isinstance(data, dict) or not all(isinstance(data.get(k), list) for k in ("entities", "edges")):
        raise ValueError("JSON 必须包含 entities 和 edges 两个数组")
    entities = {}
    for node in data["entities"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"].strip():
            raise ValueError("节点必须有非空字符串 ID")
        if node["id"] in entities:
            raise ValueError(f"重复节点 ID：{node['id']}")
        if not isinstance(node.get("type"), str) or node["type"] not in ENTITY_TYPES:
            raise ValueError(f"节点类型不符合 PhyKgraph：{node['id']}")
        if not isinstance(node.get("name"), str) or not node["name"].strip():
            raise ValueError(f"节点名称为空：{node['id']}")
        if not isinstance(node.get("attributes", {}), dict):
            raise ValueError(f"attributes 必须为对象：{node['id']}")
        entities[node["id"]] = node
    seen_edges = set()
    for edge in data["edges"]:
        if not isinstance(edge, dict):
            raise ValueError("关系必须为对象")
        source, target, relation = (edge.get(k) for k in ("source_id", "target_id", "relation_type"))
        if not all(isinstance(value, str) for value in (source, target, relation)):
            raise ValueError("关系端点和关系类型必须为字符串")
        if source not in entities or target not in entities:
            raise ValueError(f"关系端点不存在：{source} -> {target}")
        if source == target:
            raise ValueError(f"不允许自环：{source}")
        if relation not in RELATION_RULES:
            raise ValueError(f"未知关系类型：{relation}")
        rule = RELATION_RULES[relation]
        if rule and (entities[source]["type"] not in rule[0] or entities[target]["type"] not in rule[1]):
            raise ValueError(f"关系类型组合不合法：{source} -[{relation}]-> {target}")
        key = (source, relation, target)
        if key in seen_edges:
            raise ValueError(f"重复关系：{key}")
        seen_edges.add(key)
    return data


def configure_database():
    """密码在本机终端输入，保存到已被 Git 忽略的本地配置。"""
    config = {
        "uri": input("Neo4j URI [bolt://localhost:7687]: ").strip() or "bolt://localhost:7687",
        "user": input("用户名 [neo4j]: ").strip() or "neo4j",
        "database": input("数据库名 [neo4j]: ").strip() or "neo4j",
        "password": getpass("Neo4j 密码（输入不显示）: "),
    }
    if not config["password"]:
        raise ValueError("密码不能为空")
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"配置已保存到 {CONFIG_FILE}（Git 已忽略）")


def import_graph(data, project, label):
    from neo4j import GraphDatabase

    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    uri = os.getenv("NEO4J_URI", config.get("uri", "bolt://localhost:7687"))
    user = os.getenv("NEO4J_USER", config.get("user", "neo4j"))
    password = os.getenv("NEO4J_PASSWORD", config.get("password"))
    database = os.getenv("NEO4J_DATABASE", config.get("database", "neo4j"))
    if not password:
        raise ValueError("请先运行 --configure，在本机输入 Neo4j 密码")
    nodes = [
        {"id": f"{project}:{node['id']}", "source_id": node["id"], "name": node["name"],
         "type": node["type"], "attributes_json": json.dumps(node.get("attributes", {}), ensure_ascii=False)}
        for node in data["entities"]
    ]
    edge_groups = {}
    for edge in data["edges"]:
        edge_groups.setdefault(edge["relation_type"], []).append({
            "source": f"{project}:{edge['source_id']}", "target": f"{project}:{edge['target_id']}"
        })

    def write_graph(tx):
        tx.run(f"""
            UNWIND $nodes AS item
            MERGE (n:{label} {{id: item.id}})
            SET n.source_id = item.source_id, n.project_id = $project,
                n.name = item.name, n.title = item.name, n.type = item.type,
                n.attributes_json = item.attributes_json
        """, nodes=nodes, project=project).consume()
        for relation, edges in edge_groups.items():
            # label 经标识符校验，relation 来自上述本体白名单。
            tx.run(f"""
                UNWIND $edges AS item
                MATCH (a:{label} {{id: item.source}}), (b:{label} {{id: item.target}})
                MERGE (a)-[r:{relation}]->(b)
                SET r.project_id = $project, r.relation_type = $relation
            """, edges=edges, project=project, relation=relation).consume()

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.verify_connectivity()
        with driver.session(database=database) as session:
            session.run(f"CREATE CONSTRAINT {label.lower()}_id_unique IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
            session.execute_write(write_graph)
            counts = session.run(f"""
                MATCH (n:{label} {{project_id: $project}})
                WITH count(n) AS nodes
                OPTIONAL MATCH (:{label} {{project_id: $project}})-[r]->(:{label} {{project_id: $project}})
                RETURN nodes, count(r) AS edges
            """, project=project).single().data()
    print(json.dumps({"project": project, "source_nodes": len(nodes), "source_edges": len(data["edges"]),
                      "database_counts": counts}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "demo_junior_physics.json")
    parser.add_argument("--project", default="junior_demo")
    parser.add_argument("--label", default="DemoJuniorPhysics")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--configure", action="store_true")
    args = parser.parse_args()
    try:
        if args.configure:
            configure_database()
            return
        if not re.fullmatch(r"[a-z][a-z0-9_]*", args.project) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", args.label):
            raise ValueError("项目 ID 和节点标签必须为合法标识符")
        data = validate_graph(json.loads(args.input.read_text(encoding="utf-8-sig")))
        print(f"校验通过：{len(data['entities'])} 个节点，{len(data['edges'])} 条关系")
        print("关系分布：", dict(Counter(edge["relation_type"] for edge in data["edges"])))
        if not args.validate_only:
            import_graph(data, args.project, args.label)
    except (ValueError, OSError) as error:
        parser.exit(1, f"失败：{error}\n")


if __name__ == "__main__":
    main()
