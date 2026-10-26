
<template>
  <el-row :gutter="20" style="margin-bottom: 20px;">
    <el-col :span="14">
      <el-card class="box-card" header="自动批量文献捕获">
        <el-form :model="scraperForm" label-width="100px" size="small">
          <el-form-item label="关键字">
            <el-input v-model="scraperForm.keyword" placeholder="如 senolytics" />
          </el-form-item>
          <el-row>
            <el-col :span="12">
              <el-form-item label="开始日期">
                <el-input v-model="scraperForm.start_date" placeholder="2010/01/01" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="结束日期">
                <el-input v-model="scraperForm.end_date" placeholder="2025/12/31" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="吞吐上限 (篇)">
            <el-input-number v-model="scraperForm.total_fetch_num" :min="1" :max="100" />
          </el-form-item>
          <el-form-item label="高级过滤后缀">
            <el-input v-model="scraperForm.other_filters" placeholder="例如: AND free full text[Filter] NOT review[pt]" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="pipelineStatus.is_running" @click="startAutoPipeline">
              {{ pipelineStatus.is_running ? '后台查询中...' : '正在自动查询' }}
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </el-col>

    <el-col :span="10">
      <el-card class="box-card" header="单篇手动查找">
        <el-form :model="manualForm" label-width="80px" size="small" style="margin-top: 15px;">
          <el-form-item label="查找模式">
            <el-radio-group v-model="manualForm.mode">
              <el-radio label="PMID">PMID 定向挖掘</el-radio>
              <el-radio label="DOI">DOI 逆向定位</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="特征输入值">
            <el-input 
              v-model="manualForm.value" 
              :placeholder="manualForm.mode === 'PMID' ? '请输入纯数字文献号，如 25754485' : '请输入标准DOI号,如 10.1126/science...'" 
            />
          </el-form-item>
          <el-form-item>
            <el-button type="success" :loading="manualLoading" @click="submitManualMine">
              立即定向托举入库
            </el-button>
          </el-form-item>
        </el-form>
        <div style="margin-top: 20px; font-size: 12px; color: #909399; line-height: 1.6;">
          * 提示：手动查找会直接触发系统层<b> 时间轴修改 </b>，通过向后端提供 PMID 或 DOI，绕过冲突物理更新时间戳。
        </div>
      </el-card>
    </el-col>
  </el-row>

  <el-collapse style="margin-bottom: 20px;">
    <el-collapse-item name="logs">
      <template #title>
        <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
          <div style="font-weight: bold; color: #E6A23C;">
            后台实时运行状态监视面板 (当前状态: {{ pipelineStatus.message }})
          </div>
          <el-button 
            size="small" 
            type="danger" 
            text 
            @click="clearLogs"
            :disabled="pipelineStatus.logs.length === 0"
          >
            清空日志
          </el-button>
        </div>
      </template>
      <div class="log-console">
        <div v-for="(log, idx) in pipelineStatus.logs" :key="idx" class="log-line">
          {{ log }}
        </div>
        <div v-if="pipelineStatus.logs.length === 0" style="color: #909399;">暂无最新的后台流水线日志。</div>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<script setup>
import { reactive, ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const emit = defineEmits(['refreshData'])
const BASE_URL = 'http://127.0.0.1:8000'

// 自动化抓取表单
const scraperForm = reactive({
  keyword: 'senolytics',
  start_date: '2010/01/01',
  end_date: '2025/12/31',
  total_fetch_num: 5,
  other_filters: 'AND free full text[Filter] NOT review[pt]'
})

// 手动急件表单
const manualForm = reactive({
  mode: 'PMID',
  value: ''
})

const manualLoading = ref(false)
const pipelineStatus = reactive({
  is_running: false,
  message: '未知',
  logs: []
})

let timer = null


const isValidDate = (dateStr) => {
  const regex = /^\d{4}\/\d{2}\/\d{2}$/
  if (!regex.test(dateStr)) return false
  const d = new Date(dateStr)
  return d instanceof Date && !isNaN(d)
}

const isValidPMID = (str) => {
  return /^\d+$/.test(str.trim())
}

// 状态轮询
const pollStatus = async () => {
  try {
    const res = await axios.get(`${BASE_URL}/api/v1/scraper/status`)
    pipelineStatus.is_running = res.data.is_running
    pipelineStatus.message = res.data.message
    pipelineStatus.logs = res.data.logs || []
    
    if (!res.data.is_running) {
      emit('refreshData')
    }
  } catch (err) {
    console.error('状态轮询失败', err)
  }
}

// 激活批量自动化挖掘
const startAutoPipeline = async () => {

  if (!isValidDate(scraperForm.start_date)) {
    ElMessage.error('开始日期格式错误！必须是 YYYY/MM/DD')
    return
  }
  if (!isValidDate(scraperForm.end_date)) {
    ElMessage.error('结束日期格式错误！必须是 YYYY/MM/DD')
    return
  }

  try {
    const res = await axios.post(`${BASE_URL}/api/v1/scraper/run`, scraperForm)
    ElMessage({ message: res.data.message, type: res.data.status })
    pollStatus()
  } catch (err) {
    ElMessage.error('激活自动流水线失败')
  }
}

const clearLogs = () => {
  pipelineStatus.logs = []
  ElMessage.success('日志已清空')
}

// 手动点杀
const submitManualMine = async () => {
  if (!manualForm.value || !manualForm.value.trim()) {
    return ElMessage.warning('请输入特征值！')
  }

  if (manualForm.mode === 'PMID' && !isValidPMID(manualForm.value)) {
    ElMessage.error('PMID 必须是纯数字！')
    return
  }

  manualLoading.value = true
  
  try {
    const isDoi = manualForm.mode === 'DOI'
    const queryParam = isDoi ? `?doi=${encodeURIComponent(manualForm.value.trim())}` : `?pmid=${manualForm.value.trim()}`
    
    const res = await axios.post(`${BASE_URL}/api/v1/scraper/manual_fetch${queryParam}`)
    
    if (res.data.status === 'success') {
      ElMessage.success('手动定向托举成功！时间轴已刷新置顶。')
      emit('refreshData')
      manualForm.value = ''
    }
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '手动点杀未命中，请检查输入标识符')
  } finally {
    manualLoading.value = false
  }
}

onMounted(() => {
  pollStatus()
  timer = setInterval(pollStatus, 2000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.log-console { background: #0f172a; color: #38bdf8; padding: 15px; border-radius: 6px; font-family: monospace; font-size: 13px; max-height: 200px; overflow-y: auto; line-height: 1.5; }
.log-line { margin-bottom: 4px; }
</style>