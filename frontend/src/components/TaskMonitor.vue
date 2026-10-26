<template>
  <div class="tasks-section animate-fade-in">
    <div class="section-header">
      <h2><i class="fas fa-tasks"></i> LLM Mining Task Monitor</h2>
      <button class="btn btn-secondary" @click="$emit('refresh-tasks')">
        <i class="fas fa-sync-alt"></i> Refresh Status
      </button>
    </div>

    <div class="tasks-grid">
      <div v-for="task in tasks" :key="task.task_id" class="task-card">
        <div class="task-card-header">
          <span class="task-id">ID: {{ task.task_id.substring(0, 8) }}...</span>
          <span :class="['status-badge', 'status-' + task.status.toLowerCase()]">
            <i v-if="task.status === 'RUNNING'" class="fas fa-spinner fa-spin mr-1"></i>
            {{ task.status }}
          </span>
        </div>
        
        <div class="task-card-body">
          <div class="task-info-item">
            <span class="label">Query:</span>
            <span class="value font-medium">{{ task.query || 'N/A' }}</span>
          </div>
          <div class="task-info-item">
            <span class="label">Progress:</span>
            <span class="value">{{ task.processed_count || 0 }} / {{ task.total_count || 0 }} Articles</span>
          </div>
          
          <div class="progress-container">
            <div 
              class="progress-bar" 
              :style="{ width: calculateProgress(task.processed_count, task.total_count) + '%' }"
            ></div>
          </div>
        </div>

        <div class="task-card-footer">
          <span class="task-time text-xs text-gray">Started: {{ formatTime(task.start_time) }}</span>
        </div>
      </div>

      <div v-if="tasks.length === 0" class="empty-tasks-box">
        <i class="fas fa-inbox fa-2x text-gray"></i>
        <p>No active background mining tasks</p>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  tasks: {
    type: Array,
    required: true
  }
});

defineEmits(['refresh-tasks']);

// 核心计算进度方法
const calculateProgress = (processed, total) => {
  if (!total) return 0;
  return Math.min(Math.round((processed / total) * 100), 100);
};

// 简单格式化时间
const formatTime = (timeStr) => {
  if (!timeStr) return 'N/A';
  try {
    const d = new Date(timeStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (e) {
    return timeStr;
  }
};
</script>