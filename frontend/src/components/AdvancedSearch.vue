

<template>
  <div class="advanced-search-container" style="padding: 24px; background: #ffffff; border-radius: 14px; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); margin-bottom: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
    
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; border-bottom: 2px solid #f1f5f9; padding-bottom: 12px;">
      <h2 style="font-size: 1.15rem; font-weight: 700; color: #0f172a; margin: 0; display: flex; align-items: center; gap: 8px;">
        文献与分子双向检索
      </h2>
      <span style="font-size: 0.75rem; background: #f1f5f9; color: #64748b; padding: 4px 10px; border-radius: 20px; font-weight: 600;">
        数据库内存量: {{ allCompounds.length }} 条
      </span>
    </div>
    
    <div style="display: flex; gap: 10px; margin-bottom: 20px; background: #f8fafc; padding: 10px; border-radius: 10px; border: 1px solid #f1f5f9;">
      <select 
        v-model="searchMode" 
        style="border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 12px; font-size: 0.85rem; background: #ffffff; font-weight: 600; color: #475569; outline: none; cursor: pointer;"
      >
        <option value="compound">小分子反查</option>
        <option value="article">文献追踪 (PMID / DOI)</option>
      </select>

      <input 
        v-model="queryValue" 
        type="text" 
        :placeholder="searchMode === 'compound' ? '请输入小分子名称进行检索 (如: Cyclosporin A)...' : '请输入文献 PMID 进行检索...'"
        style="flex: 1; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px 14px; font-size: 0.85rem; outline: none;"
      />
    </div>

    <div style="margin-top: 12px;">
      
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; padding: 0 4px;">
        <span style="font-size: 0.75rem; font-weight: 700; color: #94a3b8;">
          {{ queryValue.trim() ? `已精准命中: ${filteredResults.length} 条数据` : '在上方输入关键字' }}
        </span>
      </div>

      <div v-if="!queryValue.trim()" style="text-align: center; padding: 40px 20px; color: #94a3b8; font-size: 0.85rem; border: 2px dashed #e2e8f0; border-radius: 12px; background: #fafafa;">
        💡 <strong style="color: #64748b;">Waiting</strong><br/>
        输入关键字（例如输入 <span style="color: #4f46e5; font-family: monospace; font-weight: bold;">Cyclosporin A</span>），滑出全量实验数据。
      </div>

      <div v-else-if="filteredResults.length === 0" style="text-align: center; padding: 40px 0; color: #94a3b8; font-size: 0.85rem; font-style: italic; border: 1px dashed #cbd5e1; border-radius: 12px;">
        未在核心数据库中找到到含有「{{ queryValue }}」的数据。
      </div>

      <div 
        v-else 
        style="max-height: 450px; overflow-y: auto; border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px; background: #f8fafc; display: flex; flex-direction: column; gap: 8px;"
      >
        <div 
          v-for="(item, index) in filteredResults" 
          :key="item.id || index" 
          style="border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; background: #ffffff;"
        >
          <div 
            @click="toggleDrawer(index)"
            style="display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: #ffffff; cursor: pointer; user-select: none;"
            onmouseover="this.style.background='#f8fafc'"
            onmouseout="this.style.background='#ffffff'"
          >
            <div style="display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0;">
              <span style="padding: 4px 10px; font-size: 0.75rem; font-weight: 700; border-radius: 6px; flex-shrink: 0; background: #d1fae5; color: #065f46;">
                🧬 {{ item.compound_name }}
              </span>
              <h4 style="font-size: 0.85rem; font-weight: 700; color: #1e293b; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;">
                {{ item.title || item.article_title || 'Senolytic 活性验证文献' }}
              </h4>
            </div>
            
            <div style="display: flex; align-items: center; gap: 14px; margin-left: 8px;">
              <span style="font-family: monospace; font-size: 0.75rem; color: #64748b; font-weight: bold; background: #f1f5f9; padding: 2px 6px; border-radius: 4px;">
                PMID: {{ item.pmid }}
              </span>
              <div :style="{ width: '16px', height: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'transform 0.2s', transform: activeIndex === index ? 'rotate(180deg)' : 'rotate(0deg)' }">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="3"><polyline points="6 9 12 15 18 9"></polyline></svg>
              </div>
            </div>
          </div>

          <div 
            v-if="activeIndex === index" 
            style="border-top: 1px solid #f1f5f9; background: #ffffff; padding: 18px; border-bottom-left-radius: 10px; border-bottom-right-radius: 10px; display: flex; flex-direction: column; gap: 14px;"
          >
            <div style="font-size: 0.75rem; color: #64748b; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px; font-family: monospace;">
              <strong>DOI:</strong> <span style="color: #10b981;">{{ item.doi || '10.1038/s44318-024-00259-2' }}</span>
            </div>

            <div v-if="item.in_vitro || item.description" style="display: flex; flex-direction: column; gap: 4px;">
              <div style="font-size: 0.75rem; font-weight: 700; color: #3b82f6; display: flex; align-items: center; gap: 6px;">
                共有 In Vitro 细胞数据:
              </div>
              <div style="font-size: 0.75rem; color: #475569; line-height: 1.6; background: #f0f7ff; padding: 12px; border-radius: 8px; border-left: 4px solid #3b82f6;">
                {{ item.in_vitro || item.description }}
              </div>
            </div>

            <div v-if="item.in_vivo" style="display: flex; flex-direction: column; gap: 4px;">
              <div style="font-size: 0.75rem; font-weight: 700; color: #ec4899; display: flex; align-items: center; gap: 6px;">
                共有 In Vivo 动物数据:
              </div>
              <div style="font-size: 0.75rem; color: #475569; line-height: 1.6; background: #fdf2f8; padding: 12px; border-radius: 8px; border-left: 4px solid #ec4899;">
                {{ item.in_vivo }}
              </div>
            </div>

            <div v-if="item.indications || item.diseases" style="display: flex; align-items: center; gap: 8px; font-size: 0.75rem;">
              <span style="font-weight: 700; color: #e11d48;">证实衰老相关适应症:</span>
              <span style="color: #334155; font-weight: 600;">{{ item.indications || item.diseases || 'Cellular senescence, melanoma' }}</span>
            </div>

            <div v-if="item.mechanism_summary || item.summary" style="display: flex; flex-direction: column; gap: 4px;">
              <div style="font-size: 0.75rem; font-weight: 700; color: #d97706; display: flex; align-items: center; gap: 6px;">
                分子机制与假说总结:
              </div>
              <div style="font-size: 0.75rem; color: #475569; line-height: 1.6; background: #fffbeb; padding: 12px; border-radius: 8px; border: 1px dashed #f59e0b;">
                {{ item.mechanism_summary || item.summary }}
              </div>
            </div>

          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'

const searchMode = ref('compound') 
const queryValue = ref('')
const allCompounds = ref([]) 
const activeIndex = ref(null) 

const toggleDrawer = (index) => {
  activeIndex.value = activeIndex.value === index ? null : index
}

// 核心整合搜索逻辑     ================================ 这个逻辑有问题 ======================
const fetchAllData = async () => {
  try {
    // 1. 先搜索全量化合物关系
    const res = await fetch('/api/v1/compounds')
    const data = await res.json()
    const rawCompounds = Array.isArray(data) ? data : (data.results || [])
    
  
    allCompounds.value = rawCompounds.map(item => {
      return {
        ...item,
        // 如果后端传回的字段里含有 description 且没有 in_vitro，自动智能归集展示
        in_vitro: item.in_vitro || (item.description && item.description.includes('cells') ? item.description : ''),
        mechanism_summary: item.mechanism_summary || item.summary || (item.description && item.description.includes('mechanism') ? item.description : '')
      }
    })
  } catch (err) {
    console.error("加载全量单体数据失败:", err)
  }
}

onMounted(() => {
  fetchAllData()
})

watch([searchMode, queryValue], () => {
  activeIndex.value = null 
})

const filteredResults = computed(() => {
  const keyword = queryValue.value.trim().toLowerCase()
  if (!keyword) return []

  return allCompounds.value.filter(item => {
    if (searchMode.value === 'article') {
      const titleMatch = (item.title || item.article_title || '').toLowerCase().includes(keyword)
      const pmidMatch = item.pmid ? String(item.pmid).includes(keyword) : false
      return titleMatch || pmidMatch
    } else {
      return item.compound_name ? item.compound_name.toLowerCase().includes(keyword) : false
    }
  })
})
</script>