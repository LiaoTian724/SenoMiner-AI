
<template>
  <el-dialog
    v-model="visible"
    :title="`文献浏览 (PMID: ${pmid})`"
    width="70%"
    top="5vh"
    destroy-on-close
    custom-class="scientific-dialog"
  >
    <div class="article-reader-container" v-loading="loading">
      <h2 class="article-title">{{ articleTitle || '未知文献标题' }}</h2>
      
      <div class="article-meta-tags">
        <el-tag v-if="isAbstractMode" type="warning" effect="dark" class="status-tag">
          闭源/纯摘要降级挖掘
        </el-tag>
        <el-tag v-else type="success" effect="dark" class="status-tag">
          官方开源全文物
        </el-tag>
        
        <el-tag v-if="isValidPmcId" type="info" size="small">
          PMCID: {{ pmcId }}
        </el-tag>

        <el-tag type="danger" effect="plain" size="small" class="count-badge">
          已找到有效分子: <strong>{{ compoundCount }}</strong> 个
        </el-tag>

        <!-- ✅ 新增：PMID 和 DOI 跳转按钮 -->
        <a
          v-if="pmid"
          :href="`https://pubmed.ncbi.nlm.nih.gov/${pmid}`"
          target="_blank"
          rel="noopener noreferrer"
          class="jump-btn pmid-link"
        >
          <i class="el-icon-link"></i> 查看原文
        </a>
      </div>

      <hr class="title-divider" />
      
      <el-alert
        v-if="isAbstractMode"
        title="版权受限提示"
        type="warning"
        description="该文献在官方网关属于闭源/付费墙(Paywall)保护。系统已自动启动【降级互补流】为您榨取并定位免费摘要(Abstract)中的核心药理数据。"
        show-icon
        :closable="false"
        class="mb-4"
      />
      
      <div ref="contentRef" class="article-body-text" v-html="highlightedText"></div>
    </div>
    
    <template #footer>
      <div class="dialog-footer-layout">
        <div>
          <el-button 
            type="danger" 
            plain 
            icon="Delete"
            @click="handleDeleteArticle"
          >
            物理擦除该文献
          </el-button>
        </div>

        <div class="right-actions">
          <el-button 
            type="warning" 
            icon="Edit"
            @click="handleEditArticle"
          >
            修改文献信息
          </el-button>
          <el-button type="primary" @click="visible = false">关闭阅览</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, nextTick, computed } from 'vue'
import axios from 'axios'
import { ElMessageBox, ElMessage } from 'element-plus'

const visible = ref(false)
const loading = ref(false)
const pmid = ref('')
const pmcId = ref('')
const articleTitle = ref('')
const fullText = ref('')
const anchorString = ref('')
const contentRef = ref(null)

const isAbstractMode = ref(false)
const compoundCount = ref(0)

const emit = defineEmits(['refresh-list'])

const isValidPmcId = computed(() => {
  if (!pmcId.value) return false
  const val = String(pmcId.value).trim().toUpperCase()
  return val !== 'NON-OA' && val !== 'NULL' && val !== 'NONE' && val !== ''
})

const open = async (targetPmid, title, anchor, recordPmcId = '') => {
  pmid.value = targetPmid
  articleTitle.value = title || ''
  anchorString.value = anchor || ''
  
  const checkPmc = String(recordPmcId).trim().toUpperCase()
  pmcId.value = (checkPmc === 'NULL' || checkPmc === 'NONE' || checkPmc === 'NON-OA' || !recordPmcId) ? 'NON-OA' : recordPmcId

  visible.value = true
  loading.value = true
  fullText.value = ''
  isAbstractMode.value = false 
  compoundCount.value = 0      

  try {
    const res = await axios.get(`http://127.0.0.1:8000/api/v1/articles/${targetPmid}`)
    
    if (res.data) {
      if (res.data.compound_count !== undefined) {
        compoundCount.value = parseInt(res.data.compound_count) || 0
      }

      if (res.data.title) {
        articleTitle.value = res.data.title
      }

      // 纠偏 NULL 值
      if (res.data.pmc_id) {
        const serverPmc = String(res.data.pmc_id).trim().toUpperCase()
        pmcId.value = (serverPmc === 'NON-OA' || serverPmc === 'NULL' || serverPmc === 'NONE') ? 'NON-OA' : res.data.pmc_id
      } else {
        pmcId.value = 'NON-OA'
      }

      // 后端真实标准：is_open_access = 1 开源 = 全文模式
      if (res.data.is_open_access !== undefined) {
        isAbstractMode.value = !res.data.is_open_access
      } else if (res.data.is_abstract_mode !== undefined) {
        isAbstractMode.value = !!res.data.is_abstract_mode
      } else {
        isAbstractMode.value = pmcId.value === 'NON-OA'
      }

      // 如果全是 NULL，塞入保底提示文本，防死锁
      fullText.value = res.data.full_text || res.data.abstract || `暂无此文献的可读纯文本数据 (当前 PMID: ${targetPmid})`
    }
  } catch (e) {
    console.error("后端加载异常:", e)
    fullText.value = "无法从后端数据库加载该文献的文本内容。"
    isAbstractMode.value = true
  } finally {
    loading.value = false
  }

  await nextTick()
  setTimeout(() => {
    const markElement = contentRef.value?.querySelector('.research-highlight')
    if (markElement) {
      markElement.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, 300)
}

const handleDeleteArticle = () => {
  ElMessageBox.confirm(
    `此操作将永久从系统内抹除文献 (PMID: ${pmid.value}) 及其提炼出的所有小分子化合物关联记录！确定继续吗？`,
    '危险：底层物理数据删除',
    {
      confirmButtonText: '确定删除',
      cancelButtonText: '继续保存',
      type: 'danger',
    }
  ).then(async () => {
    loading.value = true
    try {
      await axios.delete(`http://127.0.0.1:8000/api/v1/articles/${pmid.value}`)
      ElMessage.success(`文献 PMID ${pmid.value} 数据已被彻底清除！`)
      visible.value = false
      emit('refresh-list') 
    } catch (err) {
      console.error("级联删除失败:", err)
      ElMessage.error(`删除失败: ${err.response?.data?.message || '后端网关不可达'}`)
    } finally {
      loading.value = false
    }
  }).catch(() => {})
}

const handleEditArticle = () => {
  ElMessageBox.prompt('请输入新的文献标题：', ' 编辑文献元数据', {
    confirmButtonText: '保存修改',
    cancelButtonText: '取消',
    inputValue: articleTitle.value,
    inputPattern: /\S+/,
    inputErrorMessage: '标题不能为空'
  }).then(async ({ value }) => {
    loading.value = true
    try {
      await axios.put(`http://127.0.0.1:8000/api/v1/articles/${pmid.value}`, {
        title: value
      })
      ElMessage.success('文献数据修改成功！')
      articleTitle.value = value 
      emit('refresh-list')       
    } catch (err) {
      console.error("更新文献失败:", err)
      ElMessage.error(`修改失败: ${err.response?.data?.message || '后端接口异常'}`)
    } finally {
      loading.value = false
    }
  }).catch(() => {})
}

const highlightedText = computed(() => {
  // 保底返回，绝对不允许抛出 undefined
  if (!fullText.value) return '暂无文本内容'
  if (!anchorString.value) return fullText.value

  try {
    const decodedAnchor = decodeURIComponent(anchorString.value)
    const parts = decodedAnchor.split(',')
    let startText = parts[0]
    let endText = parts[parts.length - 1]
    if (!startText || !endText) return fullText.value

    const escapedStart = startText.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&').replace(/\s+/g, '\\s+')
    const escapedEnd = endText.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&').replace(/\s+/g, '\\s+')
    const regex = new RegExp(`(${escapedStart}[\\s\\S]*?${escapedEnd})`, 'i')
    return fullText.value.replace(regex, `<mark class="research-highlight">$1</mark>`)
  } catch (err) {
    console.error("高亮正则解析失败:", err)
    return fullText.value
  }
})

defineExpose({ open })
</script>

<style scoped>
.dialog-footer-layout {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
.right-actions {
  display: flex;
  gap: 12px;
}
.article-reader-container {
  max-height: 65vh;
  overflow-y: auto;
  padding: 0 10px;
}
.article-title {
  font-size: 20px;
  color: #1a202c;
  line-height: 1.4;
  font-weight: 700;
  margin-bottom: 8px;
}
.article-meta-tags {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}
.status-tag {
  font-weight: bold;
  letter-spacing: 0.5px;
}
.count-badge {
  font-weight: 500;
}
.count-badge strong {
  color: #f56c6c;
  margin: 0 2px;
}
.mb-4 {
  margin-bottom: 16px;
}
.title-divider {
  border: 0;
  height: 1px;
  background: #e2e8f0;
  margin-bottom: 20px;
}
.article-body-text {
  font-size: 15px;
  color: #2d3748;
  line-height: 1.8;
  white-space: pre-wrap;
  font-family: "Times New Roman", Georgia, serif;
  padding: 10px;
  background: #f8fafc;
  border-radius: 6px;
  border: 1px solid #f1f5f9;
}
:deep(.research-highlight) {
  background-color: #fef08a !important;
  color: #000000 !important;
  font-weight: bold;
  padding: 2px 4px;
  border-radius: 4px;
  border-bottom: 2px solid #eab308;
}

/* 阅读器弹窗跳转按钮样式 */
.jump-btn.pmid-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  text-decoration: none;
  background: #f0f5fa;
  color: #1a5a96;
  border: 1px solid #d2e1f0;
  transition: all 0.2s ease;
}
.jump-btn.pmid-link:hover {
  background: #1a5a96;
  color: #fff;
}
</style>