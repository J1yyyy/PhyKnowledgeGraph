export const CATALOG_TYPES = new Set(['TEXTBOOK_VOLUME', 'CHAPTER', 'SECTION'])

// 只改变画布的可见子图；节点关联数仍沿用后端计算的完整图谱关联数。
export const filterGraphForDisplay = (graph, scope) => {
  if (scope === 'with_catalog') return graph
  const nodes = graph.nodes.filter(node => !CATALOG_TYPES.has(node.type))
  const ids = new Set(nodes.map(node => node.id))
  return {
    nodes,
    edges: graph.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target))
  }
}
