<template>
  <div class="search-form-section animate-fade-in">
    <div class="section-header">
      <h2><i class="fas fa-search-plus"></i> Launch Advanced PubMed AI Agent</h2>
    </div>

    <form @submit.prevent="handleSubmit" class="advanced-search-form">
      <div class="form-group">
        <label for="search-term">PubMed Search Query (Keywords, Mesh Terms)</label>
        <div class="input-with-icon">
          <i class="fas fa-terminal input-icon"></i>
          <input 
            id="search-term"
            type="text" 
            v-model="formData.term" 
            placeholder="e.g., (senolytics OR quercetin) AND aging" 
            required
          />
        </div>
      </div>

      <div class="form-row">
        <div class="form-group flex-1">
          <label for="max-results">Max Articles to Fetch</label>
          <input 
            id="max-results"
            type="number" 
            v-model.number="formData.maxResults" 
            min="1" 
            max="200"
          />
        </div>

        <div class="form-group flex-1">
          <label for="llm-model">AI Extraction Model</label>
          <select id="llm-model" v-model="formData.model">
            <option value="gpt-4o-mini">GPT-4o Mini (Fast)</option>
            <option value="gpt-4o">GPT-4o (Precise)</option>
            <option value="claude-3-sonnet">Claude 3.5 Sonnet</option>
          </select>
        </div>
      </div>

      <div class="form-options">
        <label class="checkbox-container">
          <input type="checkbox" v-model="formData.useLlm" />
          <span class="checkmark"></span>
          Enable Real-time LLM Compound Extraction
        </label>
        <label class="checkbox-container">
          <input type="checkbox" v-model="formData.forceScrape" />
          <span class="checkmark"></span>
          Bypass Cache (Force New PubMed Scraping)
        </label>
      </div>

      <div class="form-actions">
        <button type="submit" class="btn btn-primary btn-large" :disabled="isSubmitting">
          <i v-if="isSubmitting" class="fas fa-spinner fa-spin mr-2"></i>
          <i v-else class="fas fa-rocket mr-2"></i>
          {{ isSubmitting ? 'Agent Executing...' : 'Start AI Mining Pipeline' }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue';

defineProps({
  isSubmitting: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['search-submit']);

// 组件内聚的表单状态，提交时再一起传给父组件
const formData = ref({
  term: '',
  maxResults: 20,
  model: 'gpt-4o-mini',
  useLlm: true,
  forceScrape: false
});

const handleSubmit = () => {
  // 触发父组件的执行逻辑，并把数据打包丢过去
  emit('search-submit', { ...formData.value });
};
</script>