<script setup lang="ts">
// Sello de estado: ESTIMADO, ABORTADO, SIN DATOS, CONFIG CAMBIADA, SIMULADO…
withDefaults(defineProps<{ text: string; tone?: "info" | "warn" | "crit" | "dim"; tilt?: number }>(), {
  tone: "info",
  tilt: -1,
});
</script>

<template>
  <span class="stamp mono" :class="`stamp--${tone}`" :style="{ transform: `rotate(${tilt}deg)` }">{{ text }}</span>
</template>

<style scoped>
.stamp {
  display: inline-block;
  padding: 1px 6px;
  border: 1px dashed currentColor;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  white-space: nowrap;
}
.stamp--info {
  color: var(--accent);
}
.stamp--warn {
  color: var(--warn);
}
.stamp--crit {
  color: var(--crit);
}
.stamp--dim {
  color: var(--ink-faint);
}
@media (prefers-reduced-motion: reduce) {
  .stamp {
    transform: none !important;
  }
}
</style>
