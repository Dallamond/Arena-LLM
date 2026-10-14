<script setup lang="ts">
// Etiqueta de estado: ESTIMADO, ABORTADO, SIN DATOS, CONFIG CAMBIADA, SIMULADO…
// `tilt` se conserva por compatibilidad con las vistas; ya no inclina nada.
withDefaults(defineProps<{ text: string; tone?: "info" | "warn" | "crit" | "dim"; tilt?: number }>(), {
  tone: "info",
  tilt: 0,
});
</script>

<template>
  <span class="stamp" :class="`stamp--${tone}`">{{ text }}</span>
</template>

<style scoped>
.stamp {
  display: inline-block;
  padding: 1px 9px;
  border-radius: 999px;
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  color: var(--tone);
  background: color-mix(in srgb, var(--tone) 14%, transparent);
}
.stamp--info {
  --tone: var(--accent);
}
.stamp--warn {
  --tone: var(--warn);
}
.stamp--crit {
  --tone: var(--crit);
}
.stamp--dim {
  --tone: var(--ink-dim);
}
</style>
