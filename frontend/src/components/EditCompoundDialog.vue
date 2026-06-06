<template>
  <el-dialog
    v-model="visible"
    title="小分子信息修改"
    width="850px"
    destroy-on-close
  >
    <el-form :model="editForm" ref="editFormRef" label-width="150px" size="default">
      <el-tabs type="border-card" style="margin-top: 10px;">
        
        <el-tab-pane label="  基础元数据">
          <el-form-item label="化合物主名称">
            <el-input v-model="editForm.compound_name" placeholder="可编辑修改化合物名称" />
          </el-form-item>
          <el-form-item label="CAS 编号">
            <el-input v-model="editForm.cas_number" placeholder="例如: 117-39-5" />
          </el-form-item>
          <el-form-item label="PubMed PMID">
            <el-input v-model="editForm.pmid" placeholder="相关文献 PMID 编号" />
          </el-form-item>
          <el-form-item label="ChEMBL ID">
            <el-input v-model="editForm.chembl_id" placeholder="例如: CHEMBL46" />
          </el-form-item>
          <el-form-item label="DrugBank ID">
            <el-input v-model="editForm.drugbank_id" placeholder="例如: DB00115" />
          </el-form-item>
        </el-tab-pane>

        <el-tab-pane label="  药理学实验证据">
          <el-form-item label="In Vitro 体外数据">
            <el-input v-model="editForm.in_vitro_data" type="textarea" :rows="3" placeholder="体内细胞实验描述..." />
          </el-form-item>
          <el-form-item label="In Vitro 锚点词">
            <el-input v-model="editForm.in_vitro_anchor" placeholder="高亮快速定位词" />
          </el-form-item>
          <el-form-item label="In Vivo 体内数据">
            <el-input v-model="editForm.in_vivo_data" type="textarea" :rows="3" placeholder="体内动物实验描述..." />
          </el-form-item>
          <el-form-item label="In Vivo 锚点词">
            <el-input v-model="editForm.in_vivo_anchor" placeholder="体内高亮特征文本串" />
          </el-form-item>
        </el-tab-pane>

        <el-tab-pane label="  作用机制与衍生信息">
          <el-form-item label="衰老相关适应症">
            <el-input v-model="editForm.indications" placeholder="老化适应症" />
          </el-form-item>
          <el-form-item label="机制与假说总结">
            <el-input v-model="editForm.hypotheses_summary" type="textarea" :rows="3" placeholder="靶点、通路传导及深层清理机制..." />
          </el-form-item>
          <el-form-item label="文献 DOI">
            <el-input v-model="editForm.doi" placeholder="数字对象唯一标识符" />
          </el-form-item>
        </el-tab-pane>

      </el-tabs>
    </el-form>

    <template #footer>
      <div class="dialog-footer" style="padding-top: 10px;">
        <el-button @click="visible = false">放弃修改</el-button>
        <el-button type="warning" :loading="submitLoading" @click="submitEditForm">确认原位修正</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const props = defineProps({
  modelValue: Boolean,
  editItem: Object
})
const emit = defineEmits(['update:modelValue', 'success'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const editFormRef = ref(null)
const submitLoading = ref(false)
const API_BASE = "http://127.0.0.1:8000/api/v1"

const editForm = reactive({
  id: null, compound_name: '', cas_number: '', pmid: '', chembl_id: '', drugbank_id: '',
  doi: '', indications: '', hypotheses_summary: '',
  in_vitro_data: '', in_vitro_anchor: '', in_vivo_data: '', in_vivo_anchor: ''
})

watch(
  () => [visible.value, props.editItem],
  ([isOpen, item]) => {
    if (isOpen && item) {
      Object.keys(editForm).forEach(key => {
        editForm[key] = (item[key] !== null && item[key] !== undefined) ? item[key] : ''
      })
    }
  },
  { deep: true, immediate: true }
)

const submitEditForm = async () => {
  submitLoading.value = true
  try {
    const cleanPayload = { ...editForm }
    for (let key in cleanPayload) {
      if (cleanPayload[key] === '') cleanPayload[key] = null
    }

    const res = await axios.put(`${API_BASE}/compounds/${editForm.id}`, cleanPayload)
    
    if (res.data.status === 'success' || res.status === 200) {
      ElMessage.success("化合物核心条目原位知识修正成功")
      visible.value = false
      emit('success')
    } else {
      ElMessage.error(res.data.message || '更新操作未被后台核准')
    }
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '与后台服务通信阻断或字段规则校验失败')
  } finally {
    submitLoading.value = false
  }
}
</script>