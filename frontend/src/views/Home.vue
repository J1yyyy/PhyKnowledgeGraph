<template>
  <div class="home">
    <el-card class="welcome-card">
      <h2>欢迎使用 Kgraph 多项目知识图谱系统</h2>
      <p class="description">
        展示 PhyKgraph 初中物理示例数据，支持多项目知识图谱查询与可视化
      </p>

      <el-row :gutter="20" style="margin-top: 30px;">
        <el-col :span="8" v-for="project in projects" :key="project.id">
          <el-card shadow="hover" class="project-card" :class="{ unavailable: !project.available }" @click="goToProject(project.id)">
            <h3>{{ project.name }}</h3>
            <el-tag :type="project.available ? 'success' : 'info'" size="small">{{ project.available ? '已开放' : '未开放' }}</el-tag>
            <p>{{ project.description }}</p>
            <el-tag :type="project.source === 'neo4j' ? 'success' : 'info'">
              {{ project.source === 'neo4j' ? 'Neo4j' : 'JSON' }}
            </el-tag>
          </el-card>
        </el-col>
      </el-row>

      <el-divider />

      <h3>快速开始</h3>
      <el-steps :active="1" finish-status="success" align-center>
        <el-step title="选择项目" description="从项目列表中选择要查看的图谱" />
        <el-step title="可视化" description="查看图谱结构和节点关系" />
        <el-step title="搜索探索" description="搜索感兴趣的节点和概念" />
      </el-steps>
    </el-card>

    <el-card class="stats-card" style="margin-top: 20px;">
      <h3>系统状态</h3>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="API 状态">
          <el-tag :type="apiStatus ? 'success' : 'danger'">
            {{ apiStatus ? '运行中' : '离线' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="Neo4j 连接">
          <el-tag :type="neo4jConnected ? 'success' : 'warning'">
            {{ neo4jConnected ? '已连接' : '未连接' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="已开放项目数量">
          {{ projects.filter(project => project.available).length }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router = useRouter()
const projects = ref([])
const apiStatus = ref(false)
const neo4jConnected = ref(false)

const loadProjects = async () => {
  try {
    const response = await axios.get('/api/projects')
    projects.value = response.data.projects

    // 检查 API 状态
    const rootResponse = await axios.get('/api/health')
    apiStatus.value = true
    neo4jConnected.value = rootResponse.data.neo4j_connected || false
  } catch (error) {
    console.error('加载项目失败:', error)
    apiStatus.value = false
  }
}

const goToProject = (projectId) => {
  if (!projects.value.find(project => project.id === projectId)?.available) return
  router.push(`/graph?project=${projectId}`)
}

onMounted(() => {
  loadProjects()
})
</script>

<style scoped>
.home {
  max-width: 1200px;
  margin: 0 auto;
}

.welcome-card h2 {
  color: #667eea;
  margin-bottom: 10px;
}

.description {
  color: #666;
  font-size: 16px;
}

.project-card {
  cursor: pointer;
  transition: transform 0.3s;
  height: 200px;
}

.project-card.unavailable { cursor: not-allowed; opacity: 0.65; }
.project-card:not(.unavailable):hover {
  transform: translateY(-5px);
}

.project-card h3 {
  color: #333;
  margin-bottom: 10px;
}

.project-card p {
  color: #666;
  font-size: 14px;
  margin-bottom: 15px;
}

.stats-card {
  margin-top: 20px;
}
</style>
