<template>
  <div class="projects">
    <el-card>
      <h2>项目管理</h2>
      <p class="description">管理和查看所有知识图谱项目</p>

      <el-table :data="projects" style="width: 100%; margin-top: 20px;" v-loading="loading">
        <el-table-column prop="id" label="项目 ID" width="150" />
        <el-table-column prop="name" label="项目名称" width="250" />
        <el-table-column prop="description" label="描述" />
        <el-table-column prop="source" label="数据源" width="120">
          <template #default="scope">
            <el-tag :type="scope.row.source === 'neo4j' ? 'success' : 'info'">
              {{ scope.row.source }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="开放状态" width="110">
          <template #default="scope">
            <el-tag :type="scope.row.available ? 'success' : 'info'">{{ scope.row.available ? '已开放' : '未开放' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="scope">
            <el-button size="small" :disabled="!scope.row.available" @click="viewStats(scope.row.id)">统计</el-button>
            <el-button size="small" type="primary" :disabled="!scope.row.available" @click="viewGraph(scope.row.id)">查看图谱</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="statsDialogVisible" title="图谱统计" width="600px">
      <div v-if="currentStats">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="项目名称">{{ currentStats.project_name }}</el-descriptions-item>
          <el-descriptions-item label="数据源">{{ currentStats.source || 'JSON' }}</el-descriptions-item>
          <el-descriptions-item label="节点总数">{{ currentStats.total_nodes }}</el-descriptions-item>
          <el-descriptions-item label="关系总数">{{ currentStats.total_edges }}</el-descriptions-item>
        </el-descriptions>

        <h4 style="margin-top: 20px;">节点类型分布</h4>
        <el-table :data="currentStats.by_type || []" size="small">
          <el-table-column prop="type" label="类型" />
          <el-table-column prop="count" label="数量" width="100" />
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const router = useRouter()
const projects = ref([])
const loading = ref(false)
const statsDialogVisible = ref(false)
const currentStats = ref(null)

const loadProjects = async () => {
  loading.value = true
  try {
    const response = await axios.get('/api/projects')
    projects.value = response.data.projects
  } catch (error) {
    ElMessage.error('加载项目列表失败')
  } finally {
    loading.value = false
  }
}

const viewStats = async (projectId) => {
  try {
    const response = await axios.get(`/api/${projectId}/stats`)
    currentStats.value = response.data
    statsDialogVisible.value = true
  } catch (error) {
    ElMessage.error('获取统计信息失败')
  }
}

const viewGraph = (projectId) => {
  router.push(`/graph?project=${projectId}`)
}

onMounted(() => {
  loadProjects()
})
</script>

<style scoped>
.projects {
  max-width: 1200px;
  margin: 0 auto;
}

.projects h2 {
  color: #667eea;
  margin-bottom: 10px;
}

.description {
  color: #666;
  margin-bottom: 20px;
}
</style>
