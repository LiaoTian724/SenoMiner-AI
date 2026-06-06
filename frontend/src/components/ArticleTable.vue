<template>
  <div class="table-section animate-fade-in">
    <div class="section-header">
      <h2><i class="fas fa-file-alt"></i> Extracted Research Articles</h2>
      <div class="action-bar">
        <div class="search-box">
          <i class="fas fa-search search-icon"></i>
          <input 
            type="text" 
            :value="searchQuery" 
            @input="$emit('update:searchQuery', $event.target.value)"
            placeholder="Search articles by title or PMID..." 
          />
        </div>
      </div>
    </div>

    <div class="table-container">
      <table class="data-table">
        <thead>
          <tr>
            <th>PMID</th>
            <th>Title</th>
            <th>Journal / Year</th>
            <th>Matched Compounds</th>
            <th>Confidence</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in articles" :key="item.id">
            <td>
              <a 
                :href="'https://pubmed.ncbi.nlm.nih.gov/' + item.pmid" 
                target="_blank" 
                class="pmid-link"
              >
                {{ item.pmid }} <i class="fas fa-external-link-alt fa-xs"></i>
              </a>
            </td>
            <td class="font-medium max-w-md truncate-2-rows" :title="item.title">
              {{ item.title }}
            </td>
            <td>
              <div class="journal-text">{{ item.journal || 'Unknown' }}</div>
              <div class="text-xs text-gray">{{ item.pub_year || 'N/A' }}</div>
            </td>
            <td>
              <div class="tags-container">
                <span 
                  v-for="comp in splitCompounds(item.matched_compounds)" 
                  :key="comp" 
                  class="badge badge-primary text-xs"
                >
                  {{ comp }}
                </span>
                <span v-if="!item.matched_compounds" class="text-xs text-gray">None</span>
              </div>
            </td>
            <td>
              <div class="confidence-wrapper">
                <span class="confidence-text">{{ ((item.confidence_score || 0) * 100).toFixed(0) }}%</span>
                <div class="confidence-bar-bg">
                  <div class="confidence-bar-fill" :style="{ width: (item.confidence_score || 0) * 100 + '%' }"></div>
                </div>
              </div>
            </td>
            <td>
              <div class="actions-cell">
                <button class="action-btn view" @click="$emit('view-article', item)" title="View Details">
                  <i class="fas fa-eye"></i>
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="articles.length === 0">
            <td colspan="6" class="empty-row">No articles found</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
defineProps({
  articles: {
    type: Array,
    required: true
  },
  searchQuery: {
    type: String,
    default: ''
  }
});

defineEmits(['update:searchQuery', 'view-article']);

// 辅助方法：处理多化合物逗号分隔转换成数组
const splitCompounds = (compoundsStr) => {
  if (!compoundsStr) return [];
  return compoundsStr.split(',').map(s => s.trim()).filter(Boolean);
};
</script>