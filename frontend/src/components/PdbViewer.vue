
<template>
  <div class="molecule-viewer-box" v-loading="loading">
    <div class="viewer-header">
      <span>3D STRUCTURE (条目 #{{ compoundId }})</span>
    </div>
    
    <div class="canvas-wrapper">
      <div :id="viewerUniqueId" class="mol-canvas"></div>
    </div>

    <div class="viewer-footer">
      <el-button size="small" type="info" plain @click="resetView">重置视角</el-button>
      <el-button size="small" type="success" plain @click="switchStyle('stick')">球棍</el-button>
      <el-button size="small" type="warning" plain @click="switchStyle('sphere')">空间充填</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, onBeforeUnmount, nextTick } from 'vue'
import axios from 'axios'

const props = defineProps({
  compoundId: { type: Number, required: true },
  compoundName: { type: String, required: true },
  casNumber: { type: String, default: null },
  smiles: { type: String, default: null }
})

const viewerUniqueId = `mol-viewer-${props.compoundId}`
const loading = ref(false)
let viewer = null

function get3Dmol() {
  if (window && window.$3Dmol) return window.$3Dmol
  if (window && window['3Dmol']) return window['3Dmol']
  return null
}

onMounted(() => {
  nextTick(() => {
    initMoleculeViewer()
  })
})

onBeforeUnmount(() => {
  if (viewer) {
    viewer.clear()
    viewer = null
  }
})

watch(
  [() => props.casNumber, () => props.compoundName, () => props.smiles],
  () => {
    nextTick(() => {
      initMoleculeViewer()
    })
  },
  { deep: true }
)

const initMoleculeViewer = async () => {
  const $3Dmol = get3Dmol()
  const container = document.getElementById(viewerUniqueId)
  
  if (!container || !$3Dmol) {
    if (container) container.innerHTML = `<div style="color:#909399;text-align:center;padding-top:100px;font-size:12px;background:#fff;height:100%;">3D 组件加载中...</div>`
    return
  }

  container.innerHTML = ""

  // ==============================================
  // 3Dmol 初始化防错 + jQuery 兼容层
  // ==============================================
  try {
    // 构造 3Dmol 能识别的兼容对象（无 jQuery 也能正常运行）
    const jqueryElement = window.$ ? window.$(container) : {
      0: container,
      length: 1,
      append: (child) => {
        if (child instanceof HTMLElement) container.appendChild(child);
        else if (child.get && child.get(0)) container.appendChild(child.get(0));
        return jqueryElement;
      },
      html: (htmlStr) => { container.innerHTML = htmlStr; return jqueryElement; },
      css: (name, val) => { container.style[name] = val; return jqueryElement; },
      width: () => container.clientWidth,
      height: () => container.clientHeight
    };

    // 创建 viewer
    viewer = $3Dmol.createViewer(jqueryElement, {
      defaultcolors: $3Dmol.rasmolElementColors
    });

    console.log(`3D 挂载成功 条目 #${props.compoundId} 初始化完成`);
  } catch (err) {
    console.error("3Dmol  viewer 创建失败:", err);
    showErrorMessage(container);
    loading.value = false;
    return;
  }

  let urlsToTry = []
  const rawName = props.compoundName ? props.compoundName.trim() : ""
  
  // ==========================================================
  // 3D 结构
  // ==========================================================
  if (rawName) {
    const normName = rawName.toUpperCase().replace(/[\s+_-]/g, '')
    
    // ABT263 3D 备用药名
    if (normName === 'ABT263') {
      urlsToTry.push({ type: '3d', url: `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/Navitoclax/SDF?record_type=3d` })
    }
    // Procyanidin C1 静态 CID 链路
    if (normName === 'PROCYANIDINC1' || props.casNumber === '37064-30-5') {
      urlsToTry.push({ type: '3d', url: `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/112555/SDF?record_type=3d` })
    }
  }

  // 基础 3D 名字/CAS 通路
  if (rawName) {
    urlsToTry.push({ type: '3d', url: `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/${encodeURIComponent(rawName)}/SDF?record_type=3d` })
  }
  if (props.casNumber && props.casNumber.trim()) {
    urlsToTry.push({ type: '3d', url: `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/${encodeURIComponent(props.casNumber.trim())}/SDF?record_type=3d` })
  }

  // ==========================================================
  //  2D 平铺构象自适应降级
  // ==========================================================
  if (rawName) {
    const normName = rawName.toUpperCase().replace(/[\s+_-]/g, '')
    if (normName === 'ABT263') {
      urlsToTry.push({ type: '2d', url: `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/Navitoclax/SDF` })
      urlsToTry.push({ type: '2d', url: `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/5284534/SDF` })
    }
    urlsToTry.push({ type: '2d', url: `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/${encodeURIComponent(rawName)}/SDF` })
  }
  if (props.casNumber && props.casNumber.trim()) {
    urlsToTry.push({ type: '2d', url: `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/${encodeURIComponent(props.casNumber.trim())}/SDF` })
  }

  if (urlsToTry.length === 0) {
    showErrorMessage(container)
    loading.value = false
    return
  }

  loading.value = true
  let success = false

  // 开始全自适应轮询
  for (let item of urlsToTry) {
    try {
      console.log(`3Dmol 尝试 类型: ${item.type}, URL: ${item.url}`)
      const res = await axios.get(item.url, { timeout: 8000 })
      
      if (res.data && !res.data.includes("Fault") && res.data.length > 150) { 
        viewer.addModel(res.data, "sdf")
        
        if (item.type === '2d') {
          console.log(`3Dmol 降级成功 2D → 3D 构象生成`)
          viewer.setStyle({}, { stick: { radius: 0.22, colorscheme: "Jmol" } })
        } else {
          viewer.setStyle({}, { stick: { radius: 0.2, colorscheme: "Jmol" } })
        }
        
        viewer.zoomTo()
        viewer.render()
        
        setTimeout(() => {
          if (viewer) {
            viewer.resize()
            viewer.render()
          }
        }, 300)
        
        success = true
        console.log(`3Dmol 渲染成功`)
        break 
      }
    } catch (err) {
      console.warn(`3Dmol 降级 该通路失败，继续尝试`)
    }
  }

  loading.value = false
  if (!success) showErrorMessage(container)
}

const showErrorMessage = (container) => {
  if (container) {
    container.innerHTML = `<div style="color:#909399;text-align:center;padding-top:100px;font-size:12px;background:#fff;height:100%;">未匹配到PubChem小分子模型<br/>已留空立体视窗</div>`
  }
}

const resetView = () => { 
  if (viewer) {
    viewer.zoomTo() 
    viewer.render()
  }
}

const switchStyle = (styleType) => {
  if (!viewer) return
  viewer.setStyle({}, {})
  
  if (styleType === 'stick') {
    viewer.setStyle({}, { stick: { radius: 0.2 }, sphere: { scale: 0.4 } })
  } else if (styleType === 'sphere') {
    viewer.setStyle({}, { sphere: {} })
  }
  
  viewer.render()
}
</script>

<style scoped>
.molecule-viewer-box {width: 320px; background: #f8f9fa; border-right: 1px solid #e4e7ed; display: flex; flex-direction: column;}

.viewer-header {
  background: #eef1f6;
  padding: 8px;
  font-size: 11px;
  font-weight: bold;
  color: #4a5568;
  text-align: center;
  letter-spacing: 0.5px;
}

.canvas-wrapper {
  flex: 1;
  width: 320px;
  min-height: 280px;
  position: relative;
  background-color: #ffffff;
}

.mol-canvas {
  width: 100%;
  height: 100%;
  position: absolute;
  top: 0;
  left: 0;
}

.viewer-footer {
  padding: 8px;
  background: #eef1f6;
  display: flex;
  justify-content: space-around;
  border-top: 1px solid #e4e7ed;
}
</style>