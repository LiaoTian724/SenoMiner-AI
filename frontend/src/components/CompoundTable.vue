
<template>
  <div class="section-title">知识库已收录 Senolytic 小分子数据</div>
  
  <div class="articles-collapse-container">
    <el-collapse v-model="activeNames" class="custom-collapse" @change="handleCollapseChange">
      <el-collapse-item 
        v-for="article in paginatedArticles" 
        :key="article.articleKey" 
        :name="article.articleKey"
      >
        <template #title>
          <div class="collapse-header-flex">
            <div class="left-meta">
              <span class="source-tag">  文献源</span>
              <span class="meta-item">PMID: <strong class="pmid-highlight">{{ article.pmid || '无' }}</strong></span>
              <span class="divider">|</span>
              <span class="meta-item doi-item">DOI: <span>{{ article.doi || '暂无 DOI' }}</span></span>
            </div>
            <div class="right-counter">
              <el-tag size="small" type="info" effect="light" round>
                内含 {{ article.compounds.length }} 个小分子
              </el-tag>
            </div>
          </div>
        </template>

        <div class="drawer-body-content">
          <div class="cards-container">
            <el-card 
              v-for="item in article.compounds" 
              :key="item.id" 
              class="compound-detail-card"
              shadow="hover"
            >
              <template #header>
                <div class="card-header-flex">
                  <span class="c-name">compound_name: {{ item.compound_name }}</span>
                  <div class="header-tags">
                    <template v-if="item.chembl_id && item.chembl_id !== 'N/A'">
                      <a
                        :href="`https://www.ebi.ac.uk/chembl/compound_report_card/${item.chembl_id}/`"
                        target="_blank"
                        class="ext-db-tag chembl"
                        @click.stop
                      >
                        ChEMBL: {{ item.chembl_id }}
                      </a>
                    </template>
                    <span v-else class="ext-db-tag chembl disabled">ChEMBL: N/A</span>

                    <template v-if="item.drugbank_id && item.drugbank_id !== 'N/A'">
                      <a
                        :href="`https://go.drugbank.com/drugs/${item.drugbank_id}`"
                        target="_blank"
                        class="ext-db-tag drugbank"
                        @click.stop
                      >
                        DrugBank: {{ item.drugbank_id }}
                      </a>
                    </template>
                    <span v-else class="ext-db-tag drugbank disabled">DrugBank: N/A</span>

                    <el-tag size="small" type="success" plain>CAS: {{ item.cas_number || 'N/A' }}</el-tag>

                    <el-button-group class="action-btn-group" style="margin-left:6px;">
                      <el-button size="small" type="primary" plain @click.stop="openEditDialog(item)">修改</el-button>
                      <el-button size="small" type="danger" plain @click.stop="confirmDelete(item)">删除</el-button>
                    </el-button-group>
                    
                  </div>
                </div>
              </template>
              
              <div class="card-split-layout">
                <div class="left-structure-pod">
                  <div class="pod-lbl">3D STRUCTURE (条目 #{{ item.id }})</div>
                  <div :id="`viewer-${item.id}`" class="viewer-wrapper">
                    <PdbViewer 
                      :key="`pdb-${item.id}-${renderTriggerCounter}`"
                      :compoundId="Number(item.id)" 
                      :compoundName="item.compound_name || ''" 
                      :casNumber="item.cas_number || ''"
                      :smiles="item.smiles || ''"
                    />
                  </div>
                </div>

                <div class="right-data-pod">
                  <div class="data-block vitro">
                    <span class="block-tag"> 局部文献上下文精准定位 (体外)</span>
                    <p class="data-text">"{{ item.in_vitro_data || '暂无提取数据' }}"</p>
                    <small v-if="item.in_vitro_anchor" class="anchor-text">锚点: {{ item.in_vitro_anchor }}</small>
                  </div>
                  <div class="data-block vivo">
                    <span class="block-tag"> 局部文献上下文精准定位 (体内)</span>
                    <p class="data-text">"{{ item.in_vivo_data || '暂无提取数据' }}"</p>
                  </div>
                  <div class="meta-brief">
                    <p><b> 证实适应症:</b> {{ item.indications || '暂无数据' }}</p>
                    <p><b> 机制总结:</b> {{ item.hypotheses_summary || '暂无数据' }}</p>
                  </div>
                </div>
              </div>
            </el-card>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
    <!-- 分页控件 -->
    <div style="margin:22px 0;text-align:center;">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="aggregatedArticles.length"
        :page-sizes="[6,12,18]"
        layout="total, sizes, prev, pager, next, jumper"
        background
      />
    </div>
  </div>

  <el-dialog 
    title=" 修改化合物资产元数据" 
    v-model="editDialogVisible" 
    width="550px"
    append-to-body
  >
    <el-form v-if="editingForm" :model="editingForm" label-width="110px" size="small">
      <el-form-item label="化合物名称">
        <el-input v-model="editingForm.compound_name" placeholder="请输入核心化学资产别名" />
      </el-form-item>
      <el-form-item label="CAS 注册号">
        <el-input v-model="editingForm.cas_number" placeholder="例如: 117-39-5" />
      </el-form-item>
      <el-form-item label="SMILES 结构式">
        <el-input type="textarea" :rows="2" v-model="editingForm.smiles" placeholder="输入合法的 SMILES 用于更新 3D 渲染" />
      </el-form-item>
      <el-form-item label="体外数据上下文">
        <el-input type="textarea" :rows="3" v-model="editingForm.in_vitro_data" />
      </el-form-item>
      <el-form-item label="体内数据上下文">
        <el-input type="textarea" :rows="3" v-model="editingForm.in_vivo_data" />
      </el-form-item>
      <el-form-item label="证实适应症">
        <el-input v-model="editingForm.indications" />
      </el-form-item>
    </el-form>
    <template #footer>
      <span class="dialog-footer">
        <el-button size="small" @click="editDialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="submitEditUpdate">保存修改</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, defineProps, defineEmits, nextTick } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import axios from 'axios'
import PdbViewer from './PdbViewer.vue'

const props = defineProps({
  compounds: { type: Array, default: () => [] }
})
const emit = defineEmits(['refresh-data'])

const activeNames = ref([])
const editDialogVisible = ref(false)
const editingForm = ref(null)
const renderTriggerCounter = ref(0)

//分页配置
const currentPage = ref(1)
const pageSize = ref(6)

//原有分组排序逻辑不动
const aggregatedArticles = computed(() => {
  const map = {}
  props.compounds.forEach(c => {
    const pmid = c.pmid ? String(c.pmid).trim() : ''
    const doi = c.doi ? String(c.doi).trim() : ''
    const articleKey = pmid || doi || 'Manual_Added_Group'
    if (!map[articleKey]) {
      map[articleKey] = {
        articleKey,pmid,doi,compounds:[],latestCreatedAt:c.created_at
      }
    }
    map[articleKey].compounds.push(c)
    if(c.created_at>map[articleKey].latestCreatedAt) map[articleKey].latestCreatedAt=c.created_at
  })
  return Object.values(map).sort((a,b)=>new Date(b.latestCreatedAt)-new Date(a.latestCreatedAt))
})

//分页切片
const paginatedArticles = computed(()=>{
  const start=(currentPage.value-1)*pageSize.value
  const end=start+pageSize.value
  return aggregatedArticles.value.slice(start,end)
})

//原有业务逻辑全部保留
const handleCollapseChange = () => nextTick(()=>renderTriggerCounter.value++)
const openEditDialog = (item) => {
  console.log("【点击修改按钮】事件触发成功，传入数据项:", item);
  editingForm.value = JSON.parse(JSON.stringify(item))
  editDialogVisible.value = true
}
const submitEditUpdate = async () => {
  if (!editingForm.value || !editingForm.value.id) return
  try {
    const res = await axios.put(`/api/compounds/${editingForm.value.id}`, editingForm.value)
    if (res.status === 200 || res.data.status === 'success') {
      ElMessage.success('修改数据成功')
      editDialogVisible.value = false
      emit('refresh-data')
    }
  } catch (err) {
    console.error("【修改保存失败详情】:", err)
    ElMessage.error('同步至服务器失败，请检查网络或后端更新接口')
  }
}
const confirmDelete = (item) => {
  ElMessageBox.confirm(`确定要删除化合物 [${item.compound_name || '未命名'}] 吗？`, '警告', {
    confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
  }).then(async () => {
    try {
      await axios.delete(`/api/v1/compounds/${item.id}`)
      ElMessage.success('删除成功')
      emit('refresh-data')
    } catch (err) {
      ElMessage.error('删除请求失败')
    }
  }).catch(() => {})
}
</script>

<style scoped>
/* 全部沿用你原始CSS，无任何修改 */
.section-title { font-size: 16px; font-weight: bold; color: #334155; margin: 25px 0 15px 0; border-left: 4px solid #409EFF; padding-left: 8px; }
.articles-collapse-container { margin-top: 10px; }
.custom-collapse { border: 1px solid #e2e8f0; border-radius: 6px; background-color: #fff; }
.collapse-header-flex { display: flex; justify-content: space-between; align-items: center; width: 100%; padding-right: 20px; box-sizing: border-box; }
.left-meta { display: flex; align-items: center; gap: 12px; font-size: 13.5px; color: #475569; }
.source-tag { background: #f59e0b; color: white; font-size: 11px; font-weight: bold; padding: 2px 6px; border-radius: 4px; }
.pmid-highlight { color: #2563eb; font-family: monospace; }
.doi-item span { color: #059669; font-family: monospace; font-weight: bold; }
.divider { color: #cbd5e1; }
.drawer-body-content { padding: 15px 20px; background-color: #f8fafc; border-top: 1px solid #f1f5f9; }
.cards-container { display: flex; flex-direction: column; gap: 20px; }
.compound-detail-card { border-left: 4px solid #409EFF; border-radius: 8px; }
.card-header-flex { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.c-name { font-weight: bold; color: #1e293b; font-size: 15px; }
.header-tags { display: flex; align-items: center; gap: 8px; }
.action-btn-group { margin-left: auto; padding-left: 15px; }
.card-split-layout { display: flex; flex-direction: row; gap: 20px; margin-top: 5px; }
.left-structure-pod { width: 320px; flex-shrink: 0; display: flex; flex-direction: column; }
.pod-lbl { font-size: 11px; font-weight: bold; color: #94a3b8; margin-bottom: 5px; }
.viewer-wrapper { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; height: 240px; position: relative; overflow: hidden; }
.right-data-pod { flex: 1; display: flex; flex-direction: column; gap: 10px; }
.data-block { padding: 10px; border-radius: 6px; font-size: 12.5px; }
.data-block.vitro { background-color: #eff6ff; border: 1px solid #dbeafe; }
.data-block.vivo { background-color: #ecfdf5; border: 1px solid #d1fae5; }
.block-tag { font-weight: 600; display: block; margin-bottom: 4px; }
.data-block.vitro .block-tag { color: #1d4ed8; }
.data-block.vivo .block-tag { color: #047857; }
.data-text { margin: 0; color: #334155; }
.anchor-text { display: block; margin-top: 5px; color: #64748b; font-style: italic; }
.meta-brief { font-size: 12.5px; color: #334155; }
.meta-brief p { margin: 4px 0; }
.jump-btn.compound-pubmed {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 3px;
  text-decoration: none;
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #dbeafe;
  transition: all 0.2s ease;
}
.jump-btn.compound-pubmed:hover {background: #1d4ed8;color: #fff;}
.ext-db-tag {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
  font-weight: bold;
  text-decoration: none;
  transition: all 0.2s ease;
  cursor: pointer;
  margin-right: 3px;
}
.ext-db-tag.chembl.has-id { background: #fff7ed; color: #ea580c; border: 1px solid #ffedd5;}
.ext-db-tag.drugbank.has-id { background: #fef2f2; color: #dc2626;  border: 1px solid #fee2e2;}
.ext-db-tag.chembl.search { background: #fffaf5; color: #f97316; border: 1px dashed #fdba74;}
.ext-db-tag.drugbank.search {background: #fff5f5; color: #ef4444; border: 1px dashed #fca5a5;}
.ext-db-tag.chembl:hover { background: #ea580c;color: #fff;border-color: #ea580c;border-style: solid;}
.ext-db-tag.drugbank:hover { background: #dc2626; color: #fff; border-color: #dc2626; border-style: solid;}
.jump-btn.pubmed {display: inline-flex;align-items: center;font-size: 11px;padding: 2px 6px;border-radius: 4px;background: #eff6ff; 
  color: #1d4ed8;border: 1px solid #dbeafe;text-decoration: none; font-weight: bold;margin-right: 3px;}
.jump-btn.pubmed:hover {background: #1d4ed8; color: #fff;}
</style>