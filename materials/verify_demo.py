"""验证演示 JSON 校验器，以及 API 返回的每个节点和真实三元组。"""
import argparse
from collections import Counter
from copy import deepcopy
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from import_phykgraph_json import ROOT, validate_graph


def check_validation(data):
    validate_graph(data)
    invalid_samples = []
    sample = deepcopy(data)
    sample["entities"].append(deepcopy(sample["entities"][0]))
    invalid_samples.append(sample)
    for changes in (
        {"target_id": "missing_node"},
        {"target_id": data["edges"][0]["source_id"]},
        {"relation_type": "UNKNOWN_RELATION"},
        {"relation_type": "DERIVED_FROM"},
    ):
        sample = deepcopy(data)
        sample["edges"][0].update(changes)
        invalid_samples.append(sample)
    for sample in invalid_samples:
        try:
            validate_graph(sample)
        except ValueError:
            continue
        raise AssertionError("校验器没有拒绝非法节点或关系")
    print("PASS：有效图谱通过；重复 ID、缺失端点、自环、未知关系和错误类型组合被拒绝")


def check_api(data, base_url):
    def get(path, **params):
        url = base_url.rstrip("/") + path
        if params:
            url += "?" + urlencode(params)
        with urlopen(url, timeout=15) as response:
            return json.load(response)

    assert get("/api/health")["neo4j_connected"] is True
    prefix = "junior_demo:"
    expected_nodes = {prefix + n["id"]: (n["name"], n["type"]) for n in data["entities"]}
    expected_edges = {(prefix + e["source_id"], e["relation_type"], prefix + e["target_id"]) for e in data["edges"]}
    stats = get("/api/junior_demo/stats")
    assert (stats["total_nodes"], stats["total_edges"]) == (len(expected_nodes), len(expected_edges))
    graph = get("/api/junior_demo/graph", limit=1000, level="all")
    assert {n["id"]: (n["label"], n["type"]) for n in graph["nodes"]} == expected_nodes
    all_neighbors = {node_id: set() for node_id in expected_nodes}
    for source, _, target in expected_edges:
        all_neighbors[source].add(target)
        all_neighbors[target].add(source)
    assert {n['id']: n['degree'] for n in graph['nodes']} == {node_id: len(ids) for node_id, ids in all_neighbors.items()}
    projects = get('/api/projects')['projects']
    assert {p['id'] for p in projects if p['available']} == {'junior_demo'}
    actual_edges = {(e["from"], e["relation_type"], e["to"]) for e in graph["edges"]}
    assert actual_edges == expected_edges and len(graph["edges"]) == len(expected_edges)
    assert Counter(e["relation_type"] for e in graph["edges"]) == Counter(e["relation_type"] for e in data["edges"])
    results = get("/api/junior_demo/search", keyword="密度")["results"]
    assert results and all("密度" in n["label"] for n in results)
    detail = get("/api/junior_demo/node/" + results[0]["id"])
    assert detail["n"]["id"] == results[0]["id"]
    charges = get("/api/junior_demo/search", keyword="电荷")["results"]
    expected_charges = {node_id for node_id, (name, _) in expected_nodes.items() if "电荷" in name}
    assert len(charges) == 5 and {n["id"] for n in charges} == expected_charges
    assert charges[0]["label"] == "电荷"
    charge_id = charges[0]["id"]
    charge_detail = get("/api/junior_demo/node/" + charge_id)
    assert charge_detail["n"]["name"] == "电荷"
    for connection in charge_detail["connections"]:
        relationship = connection["relationship"]
        assert (relationship["source_id"], relationship["type"], relationship["target_id"]) in expected_edges
    neighbors = {charge_id}
    neighbors |= {target for source, _, target in expected_edges if source == charge_id}
    neighbors |= {source for source, _, target in expected_edges if target == charge_id}
    exact_graph = get("/api/junior_demo/graph", center_id=charge_id, depth=1, limit=1000)
    assert {n["id"] for n in exact_graph["nodes"]} == neighbors
    assert {(e["from"], e["relation_type"], e["to"]) for e in exact_graph["edges"]} == {
        edge for edge in expected_edges if edge[0] in neighbors and edge[2] in neighbors
    }
    for node in exact_graph['nodes']:
        assert node['degree'] == len(all_neighbors[node['id']])
    print('PASS：项目开放状态准确；完整图和邻域的节点关联数量一致')
    assert get("/api/junior_demo/graph", center_id=charge_id, limit=1)["nodes"][0]["id"] == charge_id
    assert get("/api/junior_demo/graph", center_id="missing_node") == {"nodes": [], "edges": []}
    assert get("/api/physics/graph", center_id=charge_id) == {"nodes": [], "edges": []}
    formulas = get("/api/junior_demo/nodes", node_type="FORMULA", limit=1000)["nodes"]
    assert len(formulas) == sum(n["type"] == "FORMULA" for n in data["entities"])
    assert all(n["type"] == "FORMULA" for n in formulas)
    level_ids = {}
    for level, threshold, expected_count in [('core', 5, 9), ('important', 2, 52), ('all', 0, 101)]:
        expected = {node_id for node_id, neighbors in all_neighbors.items() if len(neighbors) >= threshold}
        level_graph = get('/api/junior_demo/graph', level=level, limit=1000)
        selected_ids = {node['id'] for node in level_graph['nodes']}
        assert selected_ids == expected and len(selected_ids) == expected_count
        assert {node['id'] for node in get('/api/junior_demo/nodes', level=level, limit=1000)['nodes']} == expected
        assert {(edge['from'], edge['relation_type'], edge['to']) for edge in level_graph['edges']} == {
            edge for edge in expected_edges if edge[0] in selected_ids and edge[2] in selected_ids
        }
        level_ids[level] = selected_ids
    assert level_ids['core'] <= level_ids['important'] <= level_ids['all']
    print('PASS：核心 ≥5（9个）、重要 ≥2（52个）、全部（101个）；分级边与 JSON 一致')
    isolated_id = next(node_id for node_id, neighbors in all_neighbors.items() if not neighbors)
    for center_id in sorted(level_ids['core'] | {charge_id, isolated_id}):
        neighborhood = get('/api/junior_demo/graph', center_id=center_id, depth=1, limit=1000)
        expected_ids = {center_id} | all_neighbors[center_id]
        assert {node['id'] for node in neighborhood['nodes']} == expected_ids
        actual = {(edge['from'], edge['relation_type'], edge['to']) for edge in neighborhood['edges']}
        assert len(actual) == len(neighborhood['edges'])
        assert actual == {edge for edge in expected_edges if edge[0] in expected_ids and edge[2] in expected_ids}
        assert all(node['degree'] == len(all_neighbors[node['id']]) for node in neighborhood['nodes'])
    print('PASS：全部核心节点、普通节点和孤立节点的一跳查询与源 JSON 完全一致')

    small_graph = get("/api/junior_demo/graph", level="core", limit=3)
    selected = {n["id"] for n in small_graph["nodes"]}
    assert len(selected) == 3
    assert {(e["from"], e["relation_type"], e["to"]) for e in small_graph["edges"]} == {
        edge for edge in expected_edges if edge[0] in selected and edge[2] in selected
    }
    subgraph = get("/api/junior_demo/graph", center_node="密度", depth=2, limit=1000)
    reached = {n_id for n_id, (name, _) in expected_nodes.items() if "密度" in name}
    for _ in range(2):
        reached |= {target for source, _, target in expected_edges if source in reached} | {
            source for source, _, target in expected_edges if target in reached
        }
    assert {n["id"] for n in subgraph["nodes"]} == reached
    assert get("/api/junior_demo/graph", center_node="不存在的演示节点") == {"nodes": [], "edges": []}
    legacy_graph = get("/api/physics/graph", limit=1, level="all")
    assert not any(n["id"] in expected_nodes for n in legacy_graph["nodes"])
    for path, status in (("/api/not_a_project/stats", 404), ("/api/junior_demo/graph?depth=4", 422)):
        try:
            get(path)
        except HTTPError as error:
            assert error.code == status
        else:
            raise AssertionError(f"{path} 应返回 {status}")
    print(f"PASS：API 节点和三元组与 JSON 完全一致（{len(expected_nodes)} / {len(expected_edges)}）")
    print("PASS：搜索、详情、类型过滤、节点限制、二跳子图和错误响应")
    print("PASS：电荷五个候选、精确匹配优先、真实详情、按 ID 查询邻域和项目隔离")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:9000")
    parser.add_argument("--validation-only", action="store_true")
    args = parser.parse_args()
    data = json.loads((ROOT / "data" / "demo_junior_physics.json").read_text(encoding="utf-8-sig"))
    check_validation(data)
    if not args.validation_only:
        check_api(data, args.base_url)


if __name__ == "__main__":
    main()
