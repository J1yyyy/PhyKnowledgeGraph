<template>
  <div class="graph-view">
    <el-card>
      <div class="toolbar">
        <el-select v-model="currentProject" placeholder="选择项目" :disabled="isQuestionMode" @change="loadGraph()" style="width: 200px;">
          <el-option
            v-for="proj in projects"
            :key="proj.id"
            :label="proj.available ? proj.name : `${proj.name}（未开放）`"
            :disabled="!proj.available"
            :value="proj.id"
          />
        </el-select>

        <!-- 分级控制 -->
        <el-select v-if="!isQuestionMode" v-model="graphLevel" placeholder="显示级别" @change="loadGraph()" style="width: 150px;">
          <el-option label="核心节点" value="core" />
          <el-option label="重要节点" value="important" />
          <el-option label="全部节点" value="all" />
        </el-select>

        <el-select v-if="!isQuestionMode" v-model="graphScope" aria-label="图谱显示范围" @change="loadGraph()" style="width: 150px;">
          <el-option label="知识实体" value="knowledge" />
          <el-option label="含教材目录" value="with_catalog" />
        </el-select>

        <div v-if="!isQuestionMode" class="node-search">
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
            style="width: 100%;"
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
        </div>
        <span v-if="!isQuestionMode && searchCount !== null" class="search-status" role="status">
          {{ searchFailed ? '搜索失败，可重试' : searchCount ? `找到 ${searchCount} 个结果，请选择节点` : '未找到相关节点' }}
        </span>

        <div class="controls">
          <el-checkbox v-model="showRelationLabels" :disabled="!currentAvailable">显示关系名称</el-checkbox>
          <el-button @click="resetView">重置视图</el-button>
          <el-button @click="exportImage">导出图片</el-button>
        </div>
      </div>

      <el-alert v-if="!currentAvailable" title="该项目未开放，请选择初中物理知识图谱" type="info" :closable="false" />

      <div v-if="currentAvailable" class="stats-bar">
        <el-button v-if="isQuestionMode" size="small" @click="returnToQuestion">返回题目与解析结果</el-button>
        <el-button v-if="isQuestionMode" size="small" @click="openRegularGraph">查看普通图谱</el-button>
        <el-button v-if="activeCenterId && !isQuestionMode" size="small" @click="returnToLevel">返回分级视图</el-button>
        <el-tag type="info" size="small">
          当前显示：{{ currentNodeCount }} 个节点
        </el-tag>
        <el-tag type="success" size="small" style="margin-left: 10px;">
          {{ currentEdgeCount }} 条真实关系
        </el-tag>
        <el-tag type="success" size="small" style="margin-left: 10px;">
          {{ isQuestionMode ? '题目候选上下文' : `级别：${levelLabels[graphLevel]}` }}{{ activeCenterId && !isQuestionMode ? ' ＋ 选中节点一跳关联' : '' }}
        </el-tag>
        <el-tag v-if="activeCenterId && !isQuestionMode" size="small" type="info" style="margin-left: 10px;">基础 {{ baseNodeCount }} 个 · 临时补充 {{ currentNodeCount - baseNodeCount }} 个</el-tag>
      </div>

      <div v-if="isQuestionMode" class="question-candidates" aria-label="题目候选知识点">
        <span>候选知识点：</span>
        <el-button v-for="(candidate, index) in questionResult.candidates" :key="candidate.id"
          size="small" :type="activeCenterId === candidate.id ? 'primary' : 'default'"
          @click="selectNode({ id: candidate.id })">
          {{ index + 1 }}. {{ candidate.name }}（{{ candidate.score == null ? '离线示例' : candidate.score.toFixed(4) }}）
        </el-button>
        <span class="context-note">相似度不是正确概率；未连线的候选不表示没有知识关联。</span>
      </div>
      <el-alert v-if="isQuestionMode && questionResult.coverage_sufficient === false"
        title="当前图谱可能覆盖不足；只展示候选之间的真实关系，不自动补充邻居" type="warning" :closable="false" />

      <div v-if="currentAvailable" class="graph-legend" aria-label="节点图例">
        <span v-for="type in legendTypes" :key="type" class="legend-item">
          <i :style="{ backgroundColor: typeStyle(type).color }"></i>{{ typeStyle(type).name }}
        </span>
        <span class="legend-note">{{ isQuestionMode
          ? '蓝色描边：候选知识点 · 橙色描边：当前选中 · 连线均为经筛选的真实关系'
          : '颜色：实体类型 · 大小：完整图谱的关联节点数，非重要程度 · 橙色描边：当前选中 · 淡色：一跳范围外的背景节点' }}</span>
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
        <h4>{{ isQuestionMode ? '当前上下文中的关联节点' : '关联节点' }}（{{ visibleConnections.length }}）</h4>
        <div v-for="connection in visibleConnections"
          :key="`${connection.neighbor.id}:${connection.relationship.type}:${connection.relationship.source_id}`"
          class="node-connection">
          <span>{{ connection.relationship.source_id === selectedNode.id ? '→' : '←' }}</span>
          <el-tag size="small">{{ relationNames[connection.relationship.type] || connection.relationship.type }}</el-tag>
          <el-button link type="primary" @click="selectNode({ id: connection.neighbor.id, type: connection.neighbor.type })">
            {{ connection.neighbor.name || connection.neighbor.title || connection.neighbor.label }}
          </el-button>
        </div>
        <p v-if="!visibleConnections.length">{{ isQuestionMode ? '筛选后没有需要展示的关联节点。' : '该节点暂无关联关系。' }}</p>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as d3 from 'd3'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { loadQuestionSession } from '../questionSession'
import { CATALOG_TYPES, filterGraphForDisplay } from '../graphDisplay'

const route = useRoute()
const router = useRouter()
const projects = ref([])
const currentProject = ref('')
const searchKeyword = ref('')
const searchInput = ref(null)
const searchCount = ref(null)
const searchFailed = ref(false)
const showRelationLabels = ref(false)
const graphLevel = ref('all') // 默认不按关联数筛选，教材目录由显示范围单独控制。
const graphScope = ref('knowledge')
const showNodeDetail = ref(false)
const selectedNode = ref(null)
const nodeConnections = ref([])
const questionResult = ref(null)
const activeCenterId = ref('')
const graphContainer = ref(null)
const currentNodeCount = ref(0)
const currentEdgeCount = ref(0)
let loadVersion = 0
let suggestionVersion = 0
let selectionVersion = 0
let visibleNodes = new Map()
let baseGraph = null // 缓存当前分级图谱，不累积临时邻域。
const baseNodeCount = ref(0)
let neighborhoodIds = new Set()

const levelLabels = {
  'core': '核心（关联节点数 ≥ 5）',
  'important': '重要（关联节点数 ≥ 2）',
  'all': '全部'
}

let svg = null
let simulation = null
let fitGraphView = null
let focusGraphNode = null
const nodeTypes = {
  PHYSICS_CONCEPT: { name: '物理概念', color: '#2563eb' },
  PHYSICAL_QUANTITY: { name: '物理量', color: '#059669' },
  FORMULA: { name: '公式', color: '#d97706' },
  LAW_OR_PRINCIPLE: { name: '定律与原理', color: '#dc2626' },
  PHYSICS_MODEL: { name: '物理模型', color: '#7c3aed' },
  PHENOMENON: { name: '物理现象', color: '#0891b2' },
  TYPICAL_SCENARIO: { name: '典型情境', color: '#db2777' },
  CONDITION: { name: '适用条件', color: '#64748b' },
  EXPERIMENT: { name: '实验', color: '#65a30d' },
  METHOD: { name: '方法', color: '#9333ea' },
  CONSTANT: { name: '常量', color: '#92400e' },
  MISCONCEPTION: { name: '易错认识', color: '#be123c' },
  MATH_TOOL: { name: '数学工具', color: '#0f766e' },
  MEASUREMENT_TOOL: { name: '测量工具', color: '#0d9488' },
  TEXTBOOK_VOLUME: { name: '教材册别', color: '#334155' },
  CHAPTER: { name: '教材章', color: '#475569' },
  SECTION: { name: '教材节', color: '#64748b' }
}
const typeStyle = type => nodeTypes[type] || { name: type, color: '#475569' }
const nodeRadius = node => 6 + Math.min(8, Math.sqrt(Math.max(0, node.degree)) * 1.6)
const legendTypes = ref([])
const currentAvailable = computed(() => projects.value.some(project => project.id === currentProject.value && project.available))
const isQuestionMode = computed(() => route.query.context === 'question' && questionResult.value?.project_id === currentProject.value)
const candidateIds = computed(() => new Set(questionResult.value?.candidates.map(item => item.id) || []))
const visibleConnections = computed(() => {
  if (!isQuestionMode.value) return nodeConnections.value
  // 详情只列出上下文图实际保留的边，不能让未选中的一跳关系从侧栏混入。
  const edgeKeys = new Set(baseGraph?.edges.map(edge => JSON.stringify([
    edge.source, edge.relation_type, edge.target
  ])) || [])
  return nodeConnections.value.filter(item => edgeKeys.has(JSON.stringify([
    item.relationship.source_id, item.relationship.type, item.relationship.target_id
  ])))
})
let resizeObserver = null

const relationNames = {
  PARENT_CHILD: '层级关系',
  CONTAINS_VARIABLE: '包含变量',
  PREREQUISITE: '前置依赖',
  APPLICABLE_UNDER: '适用条件',
  TAUGHT_IN: '对应教材节',
  BELONGS_TO: '属于',
  COVERED_IN_CHAPTER: '涉及教材章',
  DESCRIBED_BY: '由公式或规律描述',
  IS_A: '属于一种',
  MEASURES: '测量',
  RELATED_TO: '相关知识',
  RELATES_TO: '关联',
  ABSORBS_HEAT: '吸热',
  RELEASES_HEAT: '放热',
  CHANGED_BY: '改变方式'
}

// 加载项目列表
const loadProjects = async () => {
  try {
    const response = await axios.get('/api/projects')
    projects.value = response.data.projects
    if (projects.value.length > 0) {
      currentProject.value = route.query.project || projects.value.find(project => project.available)?.id || ''
      loadGraph()
    }
  } catch (error) {
    ElMessage.error('加载项目列表失败')
  }
}

// 缓存分级数据与当前显示分开；每次选择都从基础图谱重新合并。
const normalizeGraph = data => ({
  nodes: data.nodes.map(node => ({
    id: node.id, label: node.label || node.title, type: node.type || 'Unknown',
    description: node.description, degree: Number(node.degree ?? 0)
  })),
  edges: data.edges.map(edge => ({
    source: edge.from, target: edge.to, label: edge.label, relation_type: edge.relation_type
  }))
})

const renderGraph = (graph, preservePositions = false) => {
  const previous = visibleNodes
  const center = previous.get(activeCenterId.value)
  const nodes = graph.nodes.map(node => ({ ...node }))
  let addedIndex = 0
  for (const node of nodes) {
    const old = preservePositions && previous.get(node.id)
    if (old && Number.isFinite(old.x) && Number.isFinite(old.y)) {
      node.x = old.x
      node.y = old.y
      node.fx = old.x
      node.fy = old.y
    } else if (preservePositions) {
      const angle = addedIndex++ * 2.399963
      const radius = node.id === activeCenterId.value ? 0 : 110 + 14 * Math.sqrt(addedIndex)
      node.x = (center?.x ?? graphContainer.value.clientWidth / 2) + Math.cos(angle) * radius
      node.y = (center?.y ?? graphContainer.value.clientHeight / 2) + Math.sin(angle) * radius
      node.fx = node.x
      node.fy = node.y
    }
  }
  const edges = graph.edges.map(edge => ({ ...edge })) // D3 会修改 source/target，不能直接修改缓存。
  currentNodeCount.value = nodes.length
  currentEdgeCount.value = edges.length
  legendTypes.value = [...new Set(nodes.map(node => node.type))].sort()
  visibleNodes = new Map(nodes.map(node => [node.id, node]))
  visualizeGraph(nodes, edges, preservePositions)
}

const loadGraph = async (requestedNodeId = '') => {
  const version = ++loadVersion
  ++selectionVersion
  const session = route.query.context === 'question' ? loadQuestionSession() : null
  questionResult.value = session?.result?.project_id === currentProject.value ? session.result : null
  baseGraph = null
  baseNodeCount.value = 0
  activeCenterId.value = ''
  neighborhoodIds.clear()
  showNodeDetail.value = false
  selectedNode.value = null
  nodeConnections.value = []
  if (!currentProject.value || !currentAvailable.value) {
    currentNodeCount.value = 0
    currentEdgeCount.value = 0
    visibleNodes.clear()
    simulation?.stop()
    resizeObserver?.disconnect()
    d3.select(graphContainer.value).selectAll('*').remove()
    return false
  }
  await nextTick()
  try {
    const limits = { core: 100, important: 500, all: 1000 }
    // 题目模式只请求筛选后的候选上下文；普通分级图谱继续走原有接口。
    const response = isQuestionMode.value
      ? await axios.post(`/api/${currentProject.value}/question/context`, {
          candidates: questionResult.value.candidates.map(item => ({ id: item.id, score: item.score })),
          analysis: questionResult.value.analysis,
          coverage_sufficient: questionResult.value.coverage_sufficient
        })
      : await axios.get(`/api/${currentProject.value}/graph`, {
          params: { limit: limits[graphLevel.value], level: graphLevel.value }
        })
    if (version !== loadVersion) return false
    const graph = normalizeGraph(response.data)
    baseGraph = isQuestionMode.value ? graph : filterGraphForDisplay(graph, graphScope.value)
    baseNodeCount.value = baseGraph.nodes.length
    renderGraph(baseGraph)
    ElMessage.success(`已加载 ${currentNodeCount.value} 个节点、${currentEdgeCount.value} 条真实关系`)
    if (route.query.context === 'question' && !isQuestionMode.value) {
      ElMessage.warning('当前标签页没有可恢复的题目结果，已显示普通图谱')
    }
    await nextTick()
    if (version === loadVersion) await openRouteNode(requestedNodeId)
    return true
  } catch (error) {
    if (version !== loadVersion) return false
    currentNodeCount.value = 0
    currentEdgeCount.value = 0
    visibleNodes.clear()
    focusGraphNode = null
    fitGraphView = null
    simulation?.stop()
    resizeObserver?.disconnect()
    d3.select(graphContainer.value).selectAll('*').remove()
    const detail = error.response?.data?.detail
    const message = typeof detail === 'object' ? detail.message : detail
    ElMessage.error(isQuestionMode.value ? message || '加载题目上下文失败' : '加载图谱数据失败')
    return false
  }
}

const returnToLevel = () => {
  ++selectionVersion
  activeCenterId.value = ''
  neighborhoodIds.clear()
  showNodeDetail.value = false
  selectedNode.value = null
  nodeConnections.value = []
  if (baseGraph) renderGraph(baseGraph, true)
}

const returnToQuestion = () => router.push({ name: 'QuestionLocator' })
const openRegularGraph = () => router.push({ name: 'GraphView', query: { project: currentProject.value } })

// D3 可视化
const visualizeGraph = (nodesData, edgesData, preservePositions = false) => {
  if (!graphContainer.value) return
  simulation?.stop()
  resizeObserver?.disconnect()

  // 清空容器
  d3.select(graphContainer.value).selectAll('*').remove()

  let width = graphContainer.value.clientWidth
  let height = graphContainer.value.clientHeight

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
    .attr('refX', 10)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path').attr('d', 'M0,-5L10,0L0,5').attr('fill', '#999')

  // 颜色映射
  const color = type => typeStyle(type).color

  // 创建力导向模拟
  simulation = d3.forceSimulation(nodesData)
    .force('link', d3.forceLink(edgesData).id(d => d.id).distance(115))
    .force('charge', d3.forceManyBody().strength(-360))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('x', d3.forceX(width / 2).strength(0.04))
    .force('y', d3.forceY(height / 2).strength(0.04))
    .force('collide', d3.forceCollide().radius(node => nodeRadius(node) + 22))

  // 绘制边
  const links = g.append('g')
    .selectAll('line')
    .data(edgesData)
    .join('line')
    .attr('stroke', '#999')
    .attr('stroke-opacity', 0.6)
    .attr('stroke-width', 1.5)
    .attr('data-source-id', d => d.source.id)
    .attr('data-target-id', d => d.target.id)
    .attr('data-relation-type', d => d.relation_type)
    .attr('marker-end', 'url(#relation-arrow)')
  links.append('title').text(d => d.label)
  const relationLabels = g.append('g').attr('class', 'relation-labels')
    .attr('display', showRelationLabels.value ? null : 'none').selectAll('text')
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
    .attr('r', nodeRadius)
    .attr('fill', d => color(d.type))
    .attr('stroke', d => isQuestionMode.value && candidateIds.value.has(d.id) ? '#2563eb' : '#fff')
    .attr('stroke-width', d => isQuestionMode.value && candidateIds.value.has(d.id) ? 3 : 1.5)
    .call(d3.drag()
      .on('start', dragstarted)
      .on('drag', dragged)
      .on('end', dragended))
    .on('click', (event, d) => selectNode(d))
    .on('mouseover', function(event, d) {
      d3.select(this).attr('r', nodeRadius(d) + 3)
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
      d3.select(this).attr('r', nodeRadius(d) + (selectedNode.value?.id === d.id ? 3 : 0))
      svg.selectAll('.tooltip').remove()
    })
  nodes.append('title').text(d => `${d.label}（${typeStyle(d.type).name}）· 关联节点：${d.degree}`)
  const nodeLabels = g.append('g').selectAll('text')
    .data(nodesData).join('text')
    .attr('font-size', 11).attr('fill', '#1f2937')
    .attr('pointer-events', 'none')
    .text(d => d.label?.length > 12 ? `${d.label.slice(0, 12)}…` : d.label)

  // 更新位置
  const edgeEnd = edge => {
    const dx = edge.target.x - edge.source.x
    const dy = edge.target.y - edge.source.y
    const length = Math.max(1, Math.hypot(dx, dy))
    const offset = Math.min(length, nodeRadius(edge.target) + 5)
    return { x: edge.target.x - dx / length * offset, y: edge.target.y - dy / length * offset }
  }
  const updatePositions = () => {
    links
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => edgeEnd(d).x)
      .attr('y2', d => edgeEnd(d).y)

    nodes
      .attr('cx', d => d.x)
      .attr('cy', d => d.y)
    nodeLabels.attr('x', d => d.x + nodeRadius(d) + 4).attr('y', d => d.y + 4)
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
      .attr('r', d => nodeRadius(d) + (d.id === nodeId ? 3 : 0))
      .attr('stroke', d => d.id === nodeId ? '#f59e0b' : isQuestionMode.value && candidateIds.value.has(d.id) ? '#2563eb' : '#fff')
      .attr('stroke-width', d => d.id === nodeId ? 4 : isQuestionMode.value && candidateIds.value.has(d.id) ? 3 : 1.5)
    nodes.classed('neighbor-node', d => neighborhoodIds.has(d.id) && d.id !== nodeId)
      .classed('context-node', d => !neighborhoodIds.has(d.id))
      .attr('opacity', d => neighborhoodIds.has(d.id) ? 1 : 0.25)
    nodeLabels.attr('font-weight', d => d.id === nodeId ? 'bold' : 'normal')
      .attr('opacity', d => neighborhoodIds.has(d.id) ? 1 : 0.25)
    const isDirectRelation = edge => edge.source.id === nodeId || edge.target.id === nodeId
    links.attr('stroke', edge => isDirectRelation(edge) ? '#f59e0b' : '#999')
      .attr('stroke-width', edge => isDirectRelation(edge) ? 2.5 : 1.5)
      .attr('stroke-opacity', edge => isDirectRelation(edge) ? 0.9 : 0.15)
    relationLabels.attr('opacity', edge => isDirectRelation(edge) ? 1 : 0.25)
    const rect = svg.node().getBoundingClientRect()
    const availableWidth = Math.max(120, Math.min(rect.right, window.innerWidth - (showNodeDetail.value ? 424 : 24)) - rect.left)
    const related = nodesData.filter(item => neighborhoodIds.has(item.id))
    const bounds = {
      left: d3.min(related, item => item.x) ?? node.x,
      right: d3.max(related, item => item.x) ?? node.x,
      top: d3.min(related, item => item.y) ?? node.y,
      bottom: d3.max(related, item => item.y) ?? node.y
    }
    const scale = Math.max(0.2, Math.min(1.5,
      (availableWidth - 70) / Math.max(1, bounds.right - bounds.left + 100),
      (height - 70) / Math.max(1, bounds.bottom - bounds.top + 80)))
    const transform = d3.zoomIdentity.translate(
      availableWidth / 2 - (bounds.left + bounds.right) / 2 * scale,
      height / 2 - (bounds.top + bounds.bottom) / 2 * scale).scale(scale)
    svg.interrupt().transition().duration(450).call(zoomBehavior.transform, transform)
  }
  // 先完成小图谱的初始布局，让首屏节点可见且可以立即点击。
  simulation.stop()
  if (!preservePositions) simulation.tick(180)
  if (nodesData.length && !preservePositions) {
    // 将初始位置铺到画布内，保留文字和节点的可读尺寸。
    const xScale = d3.scaleLinear().domain(d3.extent(nodesData, d => d.x)).range([60, width - 180])
    const yScale = d3.scaleLinear().domain(d3.extent(nodesData, d => d.y)).range([40, height - 40])
    nodesData.forEach(node => {
      node.x = xScale(node.x)
      node.y = yScale(node.y)
    })
  }
  // 预布局时固定已有节点，完成后释放，仍允许用户拖动。
  nodesData.forEach(node => { node.fx = null; node.fy = null })
  updatePositions()
  fitGraphView()
  resizeObserver = new ResizeObserver(() => {
    const nextWidth = graphContainer.value.clientWidth
    const nextHeight = graphContainer.value.clientHeight
    if (!nextWidth || !nextHeight || (width === nextWidth && height === nextHeight)) return
    width = nextWidth
    height = nextHeight
    svg.attr('width', width).attr('height', height)
    simulation.force('center', d3.forceCenter(width / 2, height / 2))
    simulation.force('x', d3.forceX(width / 2).strength(0.04))
    simulation.force('y', d3.forceY(height / 2).strength(0.04))
    if (showNodeDetail.value && selectedNode.value && visibleNodes.has(selectedNode.value.id)) focusGraphNode(selectedNode.value.id)
    else fitGraphView()
  })
  resizeObserver.observe(graphContainer.value)

  function dragstarted(event, d) {
    d.fx = d.x
    d.fy = d.y
  }

  function dragged(event, d) {
    simulation.alphaTarget(0.3).restart()
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
  if (!currentAvailable.value || keyword.length < 2) {
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
  if (!currentAvailable.value) return
  if (searchKeyword.value.trim().length < 2) {
    ElMessage.warning('请输入至少 2 个字符')
    return
  }
  searchInput.value.focus()
  searchInput.value.getData(searchKeyword.value)
}

// 普通模式统一查询一跳邻域；题目模式只切换固定上下文中的详情。
const selectNode = async (node) => {
  if (!baseGraph || !currentAvailable.value || !node.id || (node.project_id && node.project_id !== currentProject.value)) return
  if (!isQuestionMode.value && graphScope.value === 'knowledge' && CATALOG_TYPES.has(node.type)) {
    graphScope.value = 'with_catalog'
    await loadGraph(node.id)
    return
  }
  const project = currentProject.value
  const version = ++selectionVersion
  const baseline = baseGraph
  simulation?.stop()
  searchInput.value?.close()
  try {
    if (isQuestionMode.value) {
      // 题目图是固定的筛选上下文；点击节点只打开详情，不展开完整一跳。
      const detailResponse = await axios.get(`/api/${project}/node/${encodeURIComponent(node.id)}`)
      if (version !== selectionVersion || project !== currentProject.value || baseline !== baseGraph) return
      const detail = detailResponse.data.n
      activeCenterId.value = node.id
      selectedNode.value = { ...detail, label: detail.name || detail.title || detail.label }
      nodeConnections.value = detailResponse.data.connections
      neighborhoodIds = new Set(baseGraph.nodes.map(item => item.id))
      showNodeDetail.value = true
      await nextTick()
      if (version !== selectionVersion || project !== currentProject.value) return
      focusGraphNode?.(node.id)
      if (candidateIds.value.has(node.id) && route.query.node_id !== node.id) {
        router.replace({ name: 'GraphView', query: { ...route.query, node_id: node.id } })
      }
      return
    }
    const [detailResponse, graphResponse] = await Promise.all([
      axios.get(`/api/${project}/node/${encodeURIComponent(node.id)}`),
      axios.get(`/api/${project}/graph`, { params: { center_id: node.id, depth: 1, limit: 1000 } })
    ])
    if (version !== selectionVersion || project !== currentProject.value || baseline !== baseGraph) return
    if (graphScope.value === 'knowledge' && CATALOG_TYPES.has(detailResponse.data.n.type)) {
      // 路由只携带 ID 时，详情类型确认后再切到含目录视图定位该节点。
      graphScope.value = 'with_catalog'
      await loadGraph(node.id)
      return
    }
    const neighborhood = filterGraphForDisplay(normalizeGraph(graphResponse.data), graphScope.value)
    if (!neighborhood.nodes.some(item => item.id === node.id)) throw new Error('一跳邻域缺少选中节点')
    const mergedNodes = new Map([...baseline.nodes, ...neighborhood.nodes].map(item => [item.id, item]))
    const mergedEdges = new Map([...baseline.edges, ...neighborhood.edges].map(edge => [
      JSON.stringify([edge.source, edge.relation_type, edge.target]), edge
    ]))
    activeCenterId.value = node.id
    neighborhoodIds = new Set(neighborhood.nodes.map(item => item.id))
    const detail = detailResponse.data.n
    selectedNode.value = { ...detail, label: detail.name || detail.title || detail.label }
    nodeConnections.value = detailResponse.data.connections
    showNodeDetail.value = true
    renderGraph({ nodes: [...mergedNodes.values()], edges: [...mergedEdges.values()] }, true)
    await nextTick()
    if (version !== selectionVersion || project !== currentProject.value) return
    focusGraphNode?.(node.id)
  } catch (error) {
    if (version !== selectionVersion || project !== currentProject.value) return
    ElMessage.error(isQuestionMode.value ? '加载节点详情失败，请重试' : '加载节点详情和一跳关联失败，请重试')
  }
}

// 外部页面通过路由传递节点 ID；题目模式从会话状态恢复全部候选。
const openRouteNode = async (requestedNodeId = '') => {
  let nodeId = requestedNodeId || (typeof route.query.node_id === 'string' ? route.query.node_id.trim() : '')
  const project = typeof route.query.project === 'string' ? route.query.project : currentProject.value
  if (isQuestionMode.value && !baseGraph?.nodes.some(item => item.id === nodeId)) {
    nodeId = questionResult.value.candidates[0]?.id || ''
  }
  if (!nodeId || !baseGraph || project !== currentProject.value || nodeId === activeCenterId.value) return
  await selectNode({ id: nodeId, project_id: project })
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

watch(showNodeDetail, visible => {
  if (!visible && activeCenterId.value) nextTick(() => focusGraphNode?.(activeCenterId.value))
})

watch(showRelationLabels, visible => {
  svg?.select('.relation-labels').attr('display', visible ? null : 'none')
})

// 监听路由变化
watch(() => route.query.project, (newProject) => {
  if (newProject) {
    currentProject.value = newProject
    loadGraph()
  }
})

watch(() => route.query.node_id, () => {
  openRouteNode()
})

watch(() => route.query.context, () => {
  loadGraph()
})

onMounted(() => {
  loadProjects()
})
onUnmounted(() => {
  ++loadVersion
  ++suggestionVersion
  ++selectionVersion
  simulation?.stop()
  resizeObserver?.disconnect()
})
</script>

<style scoped>
.graph-view { height: 100%; min-height: 0; }
.graph-view > .el-card { height: 100%; box-sizing: border-box; }
.graph-view :deep(.el-card__body) {
  height: 100%; box-sizing: border-box; padding: 12px;
  display: flex; flex-direction: column; gap: 10px;
}
.graph-legend {
  display: flex; flex-wrap: wrap; align-items: center;
  gap: 6px 14px; font-size: 12px; color: #475569;
}
.legend-item { display: inline-flex; align-items: center; gap: 5px; }
.legend-item i { width: 10px; height: 10px; border-radius: 50%; }
.legend-note { color: #64748b; }
.stats-bar, .graph-legend, .toolbar { flex-shrink: 0; }
.stats-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.question-candidates {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  flex-shrink: 0; font-size: 13px; color: #334155;
}
.question-candidates .el-button { margin-left: 0; }
.context-note { color: #64748b; }

.toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 0;
  flex-wrap: wrap;
  gap: 10px;
}

.toolbar > .node-search {
  width: 260px;
  flex: 0 0 260px;
  min-width: 0;
}

.node-search :deep(.el-input) { width: 100%; min-width: 0; }

.controls {
  margin-left: auto;
  display: flex;
  align-items: center;
  flex-shrink: 0;
  gap: 10px;
}

.controls :deep(.el-checkbox) { margin-right: 0; }

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
  flex: 0 1 220px;
  min-width: 0;
  white-space: normal;
  line-height: 20px;
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
  flex: 1;
  min-height: 180px;
  background: #f8f9fa;
  border-radius: 8px;
  overflow: hidden;
}
</style>
