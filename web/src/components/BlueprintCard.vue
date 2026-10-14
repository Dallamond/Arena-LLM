<script setup lang="ts">
// Tarjeta: fondo suave, borde fino y esquinas redondeadas. El color del dispositivo es un punto junto al título.
defineProps<{
  title?: string;
  color?: string; // color del dispositivo (var CSS)
  level?: "ok" | "warn" | "crit" | "unknown";
  dense?: boolean;
}>();
</script>

<template>
  <section
    class="card"
    :class="[level && `card--${level}`, { 'card--dense': dense }]"
    :style="color ? { '--card-color': color } : undefined"
  >
    <header v-if="title || $slots.actions" class="card__head">
      <h3 class="card__title">
        <span v-if="color" class="card__swatch" aria-hidden="true" />
        <span v-if="title" class="card__name">{{ title }}</span>
      </h3>
      <div class="card__actions"><slot name="actions" /></div>
    </header>
    <slot />
  </section>
</template>

<style scoped>
.card {
  --card-color: var(--line-strong);
  position: relative;
  background: var(--panel);
  border: 1px solid transparent;
  border-radius: var(--radius);
  padding: 18px 20px 20px;
  min-width: 0;
}
.card--dense {
  padding: 14px 16px 16px;
}
.card--warn {
  border-color: color-mix(in srgb, var(--warn) 55%, var(--line));
}
.card--crit {
  border-color: var(--crit);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--crit) 35%, transparent);
}
.card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}
.card__title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-family: var(--font-sans);
  font-size: 14px;
  font-weight: 600;
}
.card__name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--ink);
}
.card__swatch {
  flex-shrink: 0;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--card-color);
}
.card__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
</style>
