<template>
  <div class="question-locator">
    <el-card>
      <template #header>
        <div>
          <h2>题目知识点定位</h2>
          <p>解析题目并从当前初中物理图谱中检索候选知识点，不自动解题。</p>
        </div>
      </template>

      <el-form label-position="top">
        <el-form-item label="选择示例题（可选）">
          <el-select v-model="selectedExampleId" clearable placeholder="选择人工标注示例" @change="selectExample">
            <el-option v-for="item in examples" :key="item.id" :label="item.question" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="物理题">
          <el-input v-model="question" type="textarea" :rows="5" maxlength="5000" show-word-limit
            placeholder="请输入一道物理题……" />
        </el-form-item>
        <el-form-item label="运行方式">
          <el-radio-group v-model="mode">
            <el-radio label="live_api">实时调用火山方舟并执行向量检索</el-radio>
            <el-radio label="offline_example" :disabled="!offlineAvailable">离线示例（不调用 API）</el-radio>
          </el-radio-group>
          <div class="mode-note">
            离线模式只验证接口和页面结构，候选来自人工标注，不包含相似度，不代表实时链路已跑通。
          </div>
        </el-form-item>
        <el-button type="primary" :loading="loading" @click="locate">解析并定位知识点</el-button>
      </el-form>
    </el-card>

    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" />

    <template v-if="result">
      <el-card class="result-card">
        <template #header>
          <div class="result-header">
            <span>结构化解析</span>
            <el-tag :type="result.source === 'live_api' ? 'success' : 'warning'">
              {{ result.source === 'live_api' ? '实时 API' : '离线示例' }}
            </el-tag>
          </div>
        </template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="领域">{{ result.analysis.domain }}</el-descriptions-item>
          <el-descriptions-item label="任务">{{ result.analysis.task }}</el-descriptions-item>
          <el-descriptions-item label="已知量">
            {{ result.analysis.known_quantities.length ? result.analysis.known_quantities.join('；') : '无明确已知量' }}
          </el-descriptions-item>
          <el-descriptions-item label="待求量">{{ result.analysis.target_quantity }}</el-descriptions-item>
          <el-descriptions-item label="候选概念">
            {{ result.analysis.candidate_concepts.length ? result.analysis.candidate_concepts.join('；') : '无' }}
          </el-descriptions-item>
          <el-descriptions-item label="检索文本">{{ result.analysis.retrieval_text }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-alert v-if="result.coverage_message" :title="result.coverage_message"
        :type="result.coverage_sufficient === false ? 'warning' : 'info'" show-icon :closable="false" />

      <el-card class="result-card">
        <template #header>候选知识点（最多 5 个）</template>
        <el-empty v-if="!result.candidates.length" description="当前图谱没有候选知识点" />
        <el-table v-else :data="result.candidates" style="width: 100%">
          <el-table-column prop="name" label="名称" min-width="180" />
          <el-table-column prop="type" label="类型" min-width="180" />
          <el-table-column label="相似度" width="130">
            <template #default="scope">
              {{ scope.row.score === null ? '离线未计算' : scope.row.score.toFixed(4) }}
            </template>
          </el-table-column>
          <el-table-column prop="id" label="实体 ID" min-width="240" />
          <el-table-column label="操作" width="130">
            <template #default="scope">
              <el-button type="primary" link @click="openGraph(scope.row.id)">在图谱中查看</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p class="score-note">相似度只表示语义接近程度，不是答案正确概率。</p>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const router = useRouter()
const examples = ref([])
const selectedExampleId = ref('')
const question = ref('')
const mode = ref('live_api')
const loading = ref(false)
const result = ref(null)
const errorMessage = ref('')

const selectedExample = computed(() => examples.value.find(item => item.id === selectedExampleId.value))
const offlineAvailable = computed(() => Boolean(selectedExample.value && selectedExample.value.question === question.value))

const loadExamples = async () => {
  try {
    const response = await axios.get('/api/junior_demo/question/examples')
    examples.value = response.data.examples
  } catch (error) {
    ElMessage.warning('示例题加载失败，仍可手动输入题目')
  }
}

const selectExample = id => {
  const example = examples.value.find(item => item.id === id)
  if (example) question.value = example.question
  else if (mode.value === 'offline_example') mode.value = 'live_api'
}

const locate = async () => {
  const text = question.value.trim()
  if (!text) {
    ElMessage.warning('请输入物理题')
    return
  }
  if (mode.value === 'offline_example' && !offlineAvailable.value) {
    ElMessage.warning('离线模式只能使用未修改的内置示例题')
    return
  }
  loading.value = true
  result.value = null
  errorMessage.value = ''
  try {
    const response = await axios.post('/api/junior_demo/question/locate', {
      question: text,
      mode: mode.value,
      example_id: mode.value === 'offline_example' ? selectedExampleId.value : null
    })
    result.value = response.data
  } catch (error) {
    const detail = error.response?.data?.detail
    errorMessage.value = typeof detail === 'object' ? detail.message : detail || '题目解析或知识点检索失败，请重试'
  } finally {
    loading.value = false
  }
}

const openGraph = nodeId => {
  router.push({ name: 'GraphView', query: { project: 'junior_demo', node_id: nodeId } })
}

onMounted(loadExamples)
</script>

<style scoped>
.question-locator { max-width: 1100px; margin: 0 auto; display: grid; gap: 16px; }
.question-locator h2 { margin: 0 0 8px; color: #667eea; }
.question-locator p { margin: 0; color: #64748b; }
.question-locator :deep(.el-select) { width: 100%; }
.result-card { margin-top: 0; }
.result-header { display: flex; align-items: center; justify-content: space-between; }
.mode-note, .score-note { margin-top: 8px !important; font-size: 13px; color: #64748b; }
</style>
