<template>
  <div class="stats-container">
    <div class="stat-card compounds">
      <div class="stat-icon"><i class="fas fa-flask"></i></div>
      <div class="stat-info">
        <h3>Total Compounds</h3>
        <p class="stat-value">{{ compoundCount }}</p>
      </div>
    </div>
    <div class="stat-card articles">
      <div class="stat-icon"><i class="fas fa-file-alt"></i></div>
      <div class="stat-info">
        <h3>Total Articles</h3>
        <p class="stat-value">{{ articleCount }}</p>
      </div>
    </div>
    <div class="stat-card tasks">
      <div class="stat-icon"><i class="fas fa-tasks"></i></div>
      <div class="stat-info">
        <h3>Active Tasks</h3>
        <p class="stat-value">{{ taskCount }}</p>
      </div>
    </div>
    <div class="stat-card accuracy">
      <div class="stat-icon"><i class="fas fa-bullseye"></i></div>
      <div class="stat-info">
        <h3>Avg Confidence</h3>
        <p class="stat-value">{{ avgConfidence }}%</p>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  compoundCount: Number,
  articleCount: Number,
  taskCount: Number,
  avgConfidence: [String, Number]
});
</script>