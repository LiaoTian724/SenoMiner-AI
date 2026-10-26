<template>
  <div class="common-layout">
    <el-container>
      <el-header class="app-header">
        <div class="logo-title">🧬 Senolytics Repository 知识库协同系统</div>
        <el-tag type="danger" effect="dark">方案二：JSON 动态扩展柔性架构</el-tag>
      </el-header>

      <el-main class="app-main">
        <ControlPanel @refreshData="fetchCompoundList" />
        
        <CompoundTable :compounds="compoundList" @refresh-data="fetchCompoundList" />
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import ControlPanel from './components/ControlPanel.vue'
import CompoundTable from './components/CompoundTable.vue'

const BASE_URL = 'http://127.0.0.1:8000'
const compoundList = ref([])

// 统一由主框架负责拉取底层的化合物总清单数据
const fetchCompoundList = async () => {
  try {
    const res = await axios.get(`${BASE_URL}/api/v1/compounds/list`)
    if (res.data.status === 'success') {
      compoundList.value = res.data.data
    }
  } catch (err) {
    console.error('获取资产清单失败', err)
  }
}

onMounted(() => {
  fetchCompoundList()
})
</script>

<style>
/* 全局页面样式基础设定 */
body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.app-header { background-color: #1e293b; color: white; display: flex; align-items: center; justify-content: space-between; font-size: 18px; font-weight: bold; }
.app-main { background-color: #f8fafc; min-height: calc(100vh - 60px); padding: 20px; }
</style>