<template>
  <el-dialog
    v-model="visible"
    title="手动录入化合物"
    width="850px"
    destroy-on-close
  >
    <el-form :model="addForm" ref="addFormRef" :rules="addRules" label-width="150px" size="default">
      <el-tabs type="border-card" style="margin-top:10px;">
        
        <el-tab-pane label="🧬 基础元数据">
          <el-form-item label="化合物主名称" prop="compound_name">
            <el-input v-model="addForm.compound_name" placeholder="例如: Quercetin" />
          </el-form-item>
          <el-form-item label="CAS 编号">
            <el-input v-model="addForm.cas_number" placeholder="例如: 117-39-5" />
          </el-form-item>
          <el-form-item label="PubMed PMID" prop="pmid">
            <el-input v-model="addForm.pmid" placeholder="必须填写：关联文献PMID" />
          </el-form-item>
          <el-form-item label="ChEMBL ID">
            <el-input v-model="addForm.chembl_id" placeholder="例如: CHEMBL46" />
          </el-form-item>
          <el-form-item label="DrugBank ID">
            <el-input v-model="addForm.drugbank_id" placeholder="例如: DB00115" />
          </el-form-item>
          <el-form-item label="文献发表日期">
            <el-input v-model="addForm.pub_date" placeholder="例如: 2025-01-01" />
          </el-form-item>
        </el-tab-pane>

        <el-tab-pane label="🔬 药理学实验证据">
          <el-form-item label="In Vitro 体外数据">
            <el-input v-model="addForm.in_vitro_data" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="In Vitro 锚点词">
            <el-input v-model="addForm.in_vitro_anchor" />
          </el-form-item>
          <el-form-item label="In Vivo 体内数据">
            <el-input v-model="addForm.in_vivo_data" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="In Vivo 锚点词">
            <el-input v-model="addForm.in_vivo_anchor" />
          </el-form-item>
        </el-tab-pane>

        <el-tab-pane label="💡 作用机制与结构">
          <el-form-item label="衰老相关适应症">
            <el-input v-model="addForm.indications" />
          </el-form-item>
          <el-form-item label="机制与假说总结">
            <el-input v-model="addForm.hypotheses_summary" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="文献 DOI">
            <el-input v-model="addForm.doi" />
          </el-form-item>
          <el-form-item label="SMILES">
            <el-input v-model="addForm.smiles" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="InChIKey">
            <el-input v-model="addForm.inchikey" />
          </el-form-item>
          <el-form-item label="类药性评分">
            <el-input v-model="addForm.drug_likeness" />
          </el-form-item>
          <el-form-item label="别名">
            <el-input v-model="addForm.common_names" />
          </el-form-item>
          <el-form-item label="综合描述">
            <el-input v-model="addForm.description" type="textarea" :rows="2" />
          </el-form-item>
        </el-tab-pane>

      </el-tabs>
    </el-form>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="visible = false">取消放弃</el-button>
        <el-button type="primary" :loading="submitLoading" @click="submitAddForm">一键核准并双向入库</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const props = defineProps({
  modelValue: Boolean
})

const emit = defineEmits(['update:modelValue', 'success'])

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const addFormRef = ref(null)
const submitLoading = ref(false)
const API_BASE = "http://127.0.0.1:8000/api/v1"

const addForm = reactive({
  compound_name: '', cas_number: '', pmid: '', chembl_id: '', drugbank_id: '',
  doi: '', smiles: '', inchikey: '', drug_likeness: '', description: '',
  common_names: '', indications: '', hypotheses_summary: '',
  in_vitro_data: '', in_vitro_anchor: '', in_vivo_data: '', in_vivo_anchor: '', pub_date: ''
})

const addRules = {
  compound_name: [{ required: true, message: '请输入化合物名称', trigger: 'blur' }],
  pmid: [{ required: true, message: '必须填写关联文献PMID', trigger: 'blur' }]
}

const submitAddForm = async () => {
  await addFormRef.value?.validate(async (valid) => {
    if (!valid) return
    submitLoading.value = true

    try {
      const payload = {
        pmid: addForm.pmid.trim(),
        compound_name: addForm.compound_name.trim(),
        cas_number: addForm.cas_number?.trim() || "N/A",
        in_vitro_data: addForm.in_vitro_data?.trim() || "N/A",
        in_vitro_anchor: addForm.in_vitro_anchor?.trim() || addForm.compound_name,
        in_vivo_data: addForm.in_vivo_data?.trim() || "N/A",
        in_vivo_anchor: addForm.in_vivo_anchor?.trim() || addForm.compound_name,
        indications: addForm.indications?.trim() || "Senolytic",
        hypotheses_summary: addForm.hypotheses_summary?.trim() || "手动专家录入",
        additional_metadata: {
          chembl_id: addForm.chembl_id?.trim() || "N/A",
          drugbank_id: addForm.drugbank_id?.trim() || "N/A",
          doi: addForm.doi?.trim() || "N/A",
          smiles: addForm.smiles?.trim() || "N/A",
          inchikey: addForm.inchikey?.trim() || "N/A",
          drug_likeness: addForm.drug_likeness?.trim() || "N/A",
          common_names: addForm.common_names?.trim() || addForm.compound_name,
          description: addForm.description?.trim() || "手动录入"
        }
      }

      await axios.post(`${API_BASE}/compounds/manual-add`, payload)
      ElMessage.success("手动录入化合物成功！")
      visible.value = false
      emit('success')

    } catch (e) {
      console.error(e)
      ElMessage.error("入库失败：" + (e.response?.data?.detail || "服务器错误"))
    } finally {
      submitLoading.value = false
    }
  })
}

const resetForm = () => {
  Object.keys(addForm).forEach(k => addForm[k] = '')
  nextTick(() => addFormRef.value?.clearValidate())
}

defineExpose({ resetForm })
</script>

<style scoped>
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>