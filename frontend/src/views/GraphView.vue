<template>
  <div class="graph-view">
    <el-card>
      <div class="toolbar">
        <el-select v-model="currentProject" placeholder="选择项目" @change="loadGraph()" style="width: 200px;">
          <el-option
            v-for="proj in projects"
            :key="proj.id"
            :label="proj.name"
            :value="proj.id"
          />
        </el-select>

        <!-- 分级控制 -->
        <el-select v-model="graphLevel" placeholder="显示级别" @change="loadGraph()" style="width: 150px; margin-left: 10px;">
          <el-option label="核心节点" value="core" />
          <el-option label="重要节点" value="important" />
          <el-option label="全部节点" value="all" />
        </el-select>

        <el-autocomplete
          ref="searchInput"
          v-model="searchKeyword"
          value-key="label"
          :fetch-suggestions="fetchSuggestions"
          :debounce="300"
          :trigger-on-focus="false"
          :highlight-first-item="false"
          placeholder="搜索节点..."
          clearable
          @select="selectNode"
          style="width: 340px; margin-left: 20px;"
        >
          <template #default="{ item }">
            <div class="search-suggestion">
              <span>{{ item.label }}</span>
              <el-tag size="small" type="info">{{ item.type }}</el-tag>
            </div>
          </template>
          <template #append>
            <el-button @mousedown.prevent @click="search">搜索</el-button>
          </template>
        </el-autocomplete>
        <span v-if="searchCount !== null" class="search-status" role="status">
          {{ searchFailed ? '搜索失败，可重试' : searchCount ? `找到 ${searchCount} 个结果，请选择节点` : '未找到相关节点' }}
        </span>

        <div class="controls">
          <el-button @click="resetView">重置视图</el-button>
          <el-button @click="exportImage">导出图片</el-button>
        </div>
      </div>

      <div class="stats-bar">
        <el-tag type="info" size="small">
          当前显示：{{ currentNodeCount }} 个节点
        </el-tag>
        <el-tag type="success" size="small" style="margin-left: 10px;">
          {{ currentEdgeCount }} 条真实关系
        </el-tag>
        <el-tag type="success" size="small" style="margin-left: 10px;">
          {{ activeCenterId ? '当前显示：节点一跳邻域' : `级别：${levelLabels[graphLevel]}` }}
        </el-tag>
      </div>

      <div ref="graphContainer" class="graph-container"></div>
    </el-card>

    <el-drawer v-model="showNodeDetail" title="节点详情" size="400px" :modal="false" :modal-penetrable="true" :lock-scroll="false">
      <div v-if="selectedNode">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="ID">{{ selectedNode.id }}</el-descriptions-item>
          <el-descriptions-item label="名称">{{ selectedNode.label }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ selectedNode.type }}</el-descriptions-item>
          <el-descriptions-item label="原始 ID" v-if="selectedNode.source_id">{{ selectedNode.source_id }}</el-descriptions-item>
          <el-descriptions-item label="描述" v-if="selectedNode.description">
            {{ selectedNode.description }}
          </el-descriptions-item>
        </el-descriptions>
        <h4>关联节点（{{ nodeConnections.length }}）</h4>
        <div v-for="connection in nodeConnections"
          :key="`${connection.neighbor.id}:${connection.relationship.type}:${connection.relationship.source_id}`"
          class="node-connection">
          <span>{{ connection.relationship.source_id === selectedNode.id ? '→' : '←' }}</span>
          <el-tag size="small">{{ relationNames[connection.relationship.type] || connection.relationship.type }}</el-tag>
          <el-button link type="primary" @click="selectNode({ id: connection.neighbor.id })">
            {{ connection.neighbor.name || connection.neighbor.title || connection.neighbor.label }}
          </el-button>
        </div>
        <p v-if="!nodeConnections.length">该节点暂无关联关系。</p>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import * as d3 from 'd3'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const route = useRoute()
const projects = ref([])
const currentProject = ref('')
const searchKeyword = ref('')
const searchInput = ref(null)
const searchCount = ref(null)
const searchFailed = ref(false)
const graphLevel = ref('all') // 演示数据默认完整展示；大图谱可切换核心节点
const showNodeDetail = ref(false)
const selectedNode = ref(null)
const nodeConnections = ref([])
const activeCenterId = ref('')
const graphContainer = ref(null)
const currentNodeCount = ref(0)
const currentEdgeCount = ref(0)
let loadVersion = 0
let suggestionVersion = 0
let selectionVersion = 0
let visibleNodes = new Map()

const levelLabels = {
  'core': '核心',
  'important': '重要',
  'all': '全部'
}

let svg = null
let simulation = null
let fitGraphView = null
let focusGraphNode = null
const relationNames = {
  PARENT_CHILD: '层级关系',
  CONTAINS_VARIABLE: '包含变量',
  PREREQUISITE: '前置依赖',
  APPLICABLE_UNDER: '适用条件'
}

// 加载项目列表
const loadProjects = async () => {
  try {
    const response = await axios.get('/api/projects')
    projects.value = response.data.projects
    if (projects.value.length > 0) {
      currentProject.value = route.query.project || projects.value[0].id
      loadGraph()
    }
  } catch (error) {
    ElMessage.error('加载项目列表失败')
  }
}

// 加载图谱数据
const loadGraph = async (centerId = null) => {
  if (!currentProject.value) return false
  if (!centerId) {
    ++selectionVersion
    showNodeDetail.value = false
    selectedNode.value = null
    nodeConnections.value = []
  }
  const version = ++loadVersion

  try {
    // 根据级别加载节点
    let limit = 200
    if (graphLevel.value === 'core') limit = 100
    if (graphLevel.value === 'important') limit = 500
    if (graphLevel.value === 'all') limit = 1000

    const response = await axios.get(`/api/${currentProject.value}/graph`, {
      params: {
        limit: limit,
        level: centerId ? undefined : graphLevel.value,
        center_id: centerId || undefined,
        depth: 1
      }
    })
    if (version !== loadVersion) return false
    activeCenterId.value = centerId || ''

    const nodes = response.data.nodes.map(n => ({
      id: n.id,
      label: n.label || n.title,
      type: n.type || 'Unknown',
      description: n.description,
      group: n.type || 'Unknown',
      value: n.degree || n.value || 1 // 连接数
    }))

    currentNodeCount.value = nodes.length
    visibleNodes = new Map(nodes.map(node => [node.id, node]))

    // Neo4j 返回真实关系；D3 使用 source / target 定位节点。
    const edges = response.data.edges.map(edge => ({
      source: edge.from,
      target: edge.to,
      label: edge.label,
      relation_type: edge.relation_type
    }))
    currentEdgeCount.value = edges.length

    visualizeGraph(nodes, edges)
    ElMessage.success(`已加载 ${nodes.length} 个节点、${edges.length} 条真实关系`)
    return true
  } catch (error) {
    if (version !== loadVersion) return false
    currentNodeCount.value = 0
    currentEdgeCount.value = 0
    visibleNodes.clear()
    focusGraphNode = null
    fitGraphView = null
    simulation?.stop()
    d3.select(graphContainer.value).selectAll('*').remove()
    console.error('加载图谱数据失败:', error)
    ElMessage.error('加载图谱数据失败')
    return false
  }
}

// D3 可视化
const visualizeGraph = (nodesData, edgesData) => {
  if (!graphContainer.value) return
  simulation?.stop()

  // 清空容器
  d3.select(graphContainer.value).selectAll('*').remove()

  const width = graphContainer.value.clientWidth
  const height = 600

  // 创建 SVG
  const zoomBehavior = d3.zoom().on('zoom', (event) => {
    g.attr('transform', event.transform)
  })
  svg = d3.select(graphContainer.value)
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .call(zoomBehavior)
  const g = svg.append('g')
  svg.append('defs').append('marker')
    .attr('id', 'relation-arrow')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 19)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#999')

  // 颜色映射
  const types = [...new Set(nodesData.map(n => n.type))]
  const color = d3.scaleOrdinal(d3.schemeCategory10).domain(types)

  // 创建力导向模拟
  simulation = d3.forceSimulation(nodesData)
    .force('link', d3.forceLink(edgesData).id(d => d.id).distance(100))
    .force('charge', d3.forceManyBody().strength(-300))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('x', d3.forceX(width / 2).strength(0.04))
    .force('y', d3.forceY(height / 2).strength(0.04))
    .force('collide', d3.forceCollide().radius(30))

  // 绘制边
  const links = g.append('g')
    .selectAll('line')
    .data(edgesData)
    .join('line')
    .attr('stroke', '#999')
    .attr('stroke-opacity', 0.6)
    .attr('stroke-width', 1.5)
    .attr('marker-end', 'url(#relation-arrow)')
  links.append('title').text(d => d.label)
  const relationLabels = g.append('g').selectAll('text')
    .data(edgesData).join('text')
    .attr('font-size', 9).attr('fill', '#64748b')
    .attr('text-anchor', 'middle').attr('pointer-events', 'none')
    .text(d => relationNames[d.relation_type] || d.label)

  // 绘制节点
  const nodes = g.append('g')
    .selectAll('circle')
    .data(nodesData)
    .join('circle')
    .attr('data-node-id', d => d.id)
    .attr('r', 8)
    .attr('fill', d => color(d.type))
    .attr('stroke', '#fff')
    .attr('stroke-width', 1.5)
    .call(d3.drag()
      .on('start', dragstarted)
      .on('drag', dragged)
      .on('end', dragended))
    .on('click', (event, d) => selectNode(d))
    .on('mouseover', function(event, d) {
      d3.select(this).attr('r', 12)
      // 显示 tooltip
      g.append('text')
        .attr('class', 'tooltip')
        .attr('x', d.x + 12)
        .attr('y', d.y - 12)
        .text(d.label)
        .attr('font-size', '12px')
        .attr('fill', '#333')
    })
    .on('mouseout', function(event, d) {
      d3.select(this).attr('r', selectedNode.value?.id === d.id ? 14 : 8)
      svg.selectAll('.tooltip').remove()
    })
  nodes.append('title').text(d => `${d.label} (${d.type})`)
  const nodeLabels = g.append('g').selectAll('text')
    .data(nodesData).join('text')
    .attr('font-size', 11).attr('fill', '#1f2937')
    .attr('pointer-events', 'none')
    .text(d => d.label?.length > 18 ? `${d.label.slice(0, 18)}…` : d.label)

  // 更新位置
  const updatePositions = () => {
    links
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y)

    nodes
      .attr('cx', d => d.x)
      .attr('cy', d => d.y)
    nodeLabels.attr('x', d => d.x + 10).attr('y', d => d.y + 4)
    relationLabels.attr('x', d => (d.source.x + d.target.x) / 2)
      .attr('y', d => (d.source.y + d.target.y) / 2 - 3)
  }
  simulation.on('tick', updatePositions)
  fitGraphView = () => {
    const bounds = g.node().getBBox()
    if (!bounds.width || !bounds.height) return
    const scale = Math.min((width - 60) / bounds.width, (height - 60) / bounds.height, 1)
    const transform = d3.zoomIdentity
      .translate(width / 2 - scale * (bounds.x + bounds.width / 2),
        height / 2 - scale * (bounds.y + bounds.height / 2))
      .scale(scale)
    svg.call(zoomBehavior.transform, transform)
  }
  focusGraphNode = (nodeId) => {
    const node = visibleNodes.get(nodeId)
    if (!node) return
    simulation.stop()
    nodes.classed('selected-node', d => d.id === nodeId)
      .attr('r', d => d.id === nodeId ? 14 : 8)
      .attr('stroke', d => d.id === nodeId ? '#f59e0b' : '#fff')
      .attr('stroke-width', d => d.id === nodeId ? 4 : 1.5)
    nodeLabels.attr('font-weight', d => d.id === nodeId ? 'bold' : 'normal')
    const rect = svg.node().getBoundingClientRect()
    const availableWidth = Math.max(120, Math.min(rect.right, window.innerWidth - 424) - rect.left)
    const scale = 1.5
    const transform = d3.zoomIdentity.translate(availableWidth / 2 - node.x * scale,
      height / 2 - node.y * scale).scale(scale)
    svg.interrupt().transition().duration(450).call(zoomBehavior.transform, transform)
  }
  // 先完成小图谱的初始布局，让首屏节点可见且可以立即点击。
  simulation.stop().tick(180)
  if (nodesData.length) {
    // 将初始位置铺到画布内，保留文字和节点的可读尺寸。
    const xScale = d3.scaleLinear().domain(d3.extent(nodesData, d => d.x)).range([60, width - 180])
    const yScale = d3.scaleLinear().domain(d3.extent(nodesData, d => d.y)).range([40, height - 40])
    nodesData.forEach(node => {
      node.x = xScale(node.x)
      node.y = yScale(node.y)
    })
  }
  updatePositions()
  fitGraphView()

  function dragstarted(event, d) {
    if (!event.active) simulation.alphaTarget(0.3).restart()
    d.fx = d.x
    d.fy = d.y
  }

  function dragged(event, d) {
    d.fx = event.x
    d.fy = event.y
  }

  function dragended(event, d) {
    if (!event.active) simulation.alphaTarget(0)
    d.fx = null
    d.fy = null
  }
}

// 自动补全只列出候选结果，选择后才打开详情。
const fetchSuggestions = async (query, callback) => {
  const keyword = query.trim()
  const project = currentProject.value
  const version = ++suggestionVersion
  if (keyword.length < 2) {
    callback([])
    return
  }
  try {
    const response = await axios.get(`/api/${project}/search`, { params: { keyword, limit: 20 } })
    if (version !== suggestionVersion || project !== currentProject.value || keyword !== searchKeyword.value.trim()) return
    searchCount.value = response.data.results.length
    searchFailed.value = false
    callback(response.data.results.map(node => ({ ...node, project_id: project })))
  } catch (error) {
    if (version !== suggestionVersion || project !== currentProject.value) return
    searchCount.value = 0
    searchFailed.value = true
    callback([])
  }
}

const search = () => {
  if (searchKeyword.value.trim().length < 2) {
    ElMessage.warning('请输入至少 2 个字符')
    return
  }
  searchInput.value.focus()
  searchInput.value.getData(searchKeyword.value)
}

// 通过唯一 ID 查询详情，再定位到节点；避免误选同名结果。
const selectNode = async (node) => {
  if (!node.id || (node.project_id && node.project_id !== currentProject.value)) return
  const project = currentProject.value
  const version = ++selectionVersion
  ++loadVersion
  searchInput.value?.close()
  try {
    const response = await axios.get(`/api/${project}/node/${encodeURIComponent(node.id)}`)
    if (version !== selectionVersion || project !== currentProject.value) return
    if (!visibleNodes.has(node.id)) {
      const loaded = await loadGraph(node.id)
      if (!loaded || version !== selectionVersion || project !== currentProject.value) return
    }
    const detail = response.data.n
    selectedNode.value = { ...detail, label: detail.name || detail.title || detail.label }
    nodeConnections.value = response.data.connections
    showNodeDetail.value = true
    await nextTick()
    if (version !== selectionVersion || project !== currentProject.value) return
    focusGraphNode?.(node.id)
  } catch (error) {
    if (version !== selectionVersion || project !== currentProject.value) return
    ElMessage.error('加载节点详情失败，请重试')
  }
}

watch(searchKeyword, () => {
  ++suggestionVersion
  searchCount.value = null
  searchFailed.value = false
  if (searchInput.value) searchInput.value.suggestions = []
}, { flush: 'sync' })

watch(currentProject, () => {
  ++suggestionVersion
  ++selectionVersion
  searchKeyword.value = ''
  searchCount.value = null
  searchInput.value?.close()
  visibleNodes.clear()
})

// 重置视图
const resetView = () => {
  fitGraphView?.()
}

// 导出图片
const exportImage = () => {
  const svgElement = d3.select(graphContainer.value).select('svg').node()
  if (!svgElement) {
    ElMessage.warning('请先加载图谱')
    return
  }
  const svgData = new XMLSerializer().serializeToString(svgElement)
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  const img = new Image()

  canvas.width = Number(svgElement.getAttribute('width'))
  canvas.height = Number(svgElement.getAttribute('height'))

  img.onload = () => {
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0)

    const link = document.createElement('a')
    link.download = `kgraph-${currentProject.value}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
  }

  img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgData)))
}

// 监听路由变化
watch(() => route.query.project, (newProject) => {
  if (newProject) {
    currentProject.value = newProject
    loadGraph()
  }
})

onMounted(() => {
  loadProjects()
})
onUnmounted(() => {
  ++loadVersion
  ++suggestionVersion
  ++selectionVersion
  simulation?.stop()
})
</script>

<style scoped>
.graph-view {
  height: calc(100vh - 140px);
}

.toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 10px;
}

.controls {
  margin-left: auto;
  display: flex;
  gap: 10px;
}

.search-suggestion {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 6px 0;
  line-height: 1.5;
  white-space: normal;
}

.search-status {
  font-size: 12px;
  color: #64748b;
}

.node-connection {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}

.graph-container {
  width: 100%;
  height: calc(100% - 80px);
  background: #f8f9fa;
  border-radius: 8px;
  overflow: hidden;
}
</style>
