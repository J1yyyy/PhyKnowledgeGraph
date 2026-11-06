import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { CATALOG_TYPES, filterGraphForDisplay } from './graphDisplay.js'

test('知识实体视图只保留知识节点之间的真实关系', () => {
  const data = JSON.parse(readFileSync(new URL('../../data/junior_physics_2024.json', import.meta.url), 'utf8'))
  const graph = {
    nodes: data.entities.map(entity => ({ id: entity.id, type: entity.type })),
    edges: data.edges.map(edge => ({ source: edge.source_id, target: edge.target_id }))
  }
  const knowledge = filterGraphForDisplay(graph, 'knowledge')
  const ids = new Set(knowledge.nodes.map(node => node.id))

  assert.equal(graph.nodes.length, 436)
  assert.equal(graph.edges.length, 788)
  assert.equal(knowledge.nodes.length, 319)
  assert.equal(knowledge.edges.length, 327)
  assert.ok(knowledge.nodes.every(node => !CATALOG_TYPES.has(node.type)))
  assert.ok(knowledge.edges.every(edge => ids.has(edge.source) && ids.has(edge.target)))
  assert.equal(filterGraphForDisplay(graph, 'with_catalog'), graph)
  assert.equal(graph.nodes.length, 436) // 切换范围不能修改原始图谱。
})

test('一跳邻域使用同一筛选规则', () => {
  const neighborhood = {
    nodes: [
      { id: 'knowledge', type: 'PHYSICS_CONCEPT' },
      { id: 'chapter', type: 'CHAPTER' },
      { id: 'formula', type: 'FORMULA' }
    ],
    edges: [
      { source: 'knowledge', target: 'chapter' },
      { source: 'knowledge', target: 'formula' }
    ]
  }
  const filtered = filterGraphForDisplay(neighborhood, 'knowledge')
  assert.deepEqual(filtered.nodes.map(node => node.id), ['knowledge', 'formula'])
  assert.deepEqual(filtered.edges, [{ source: 'knowledge', target: 'formula' }])
})
