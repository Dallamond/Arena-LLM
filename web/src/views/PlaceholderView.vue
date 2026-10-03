<script setup lang="ts">
import BlueprintCard from "../components/BlueprintCard.vue";
import Stamp from "../components/Stamp.vue";
import type { NavItem } from "../router";

defineProps<{ item: NavItem }>();
</script>

<template>
  <div class="page">
    <h2 class="page__title">{{ item.label }}</h2>
    <BlueprintCard>
      <div class="todo">
        <Stamp :text="`llega en ${item.phase}`" tone="dim" :tilt="-2" />
        <p>{{ item.summary }}</p>
        <p class="mono dim">Ver docs/HOJA-DE-RUTA.md §8 y docs/GUI-DISENO.md §5.</p>
      </div>
    </BlueprintCard>
  </div>
</template>

<style scoped>
.page__title {
  font-size: 18px;
  margin-bottom: 14px;
}
.todo {
  border: 1px dashed var(--line);
  padding: 28px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}
.todo p {
  margin: 0;
  color: var(--ink-dim);
  max-width: 60ch;
}
.dim {
  font-size: 11px;
  color: var(--ink-faint) !important;
}
</style>
