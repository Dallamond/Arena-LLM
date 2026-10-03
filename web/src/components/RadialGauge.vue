<script setup lang="ts">
// Medidor radial de 270°. Sin dato: anillo discontinuo y "sin datos".
import { computed } from "vue";
import { isNum } from "../lib/format";

const props = withDefaults(
  defineProps<{
    value: number | null | undefined; // 0..1
    label: string;
    readout: string; // cifra principal ya formateada
    sub?: string;
    tag?: string; // etiqueta pequeña (CUDA, RAM, 12 HILOS)
    color?: string;
    level?: "ok" | "warn" | "crit" | "unknown";
  }>(),
  { color: "var(--accent)", level: "ok" },
);

const R = 42;
const C = 2 * Math.PI * R;
const ARC = 0.75; // 270°
const dash = computed(() => {
  const v = isNum(props.value) ? Math.min(1, Math.max(0, props.value)) : 0;
  return `${(C * ARC * v).toFixed(2)} ${C.toFixed(2)}`;
});
const stroke = computed(() =>
  props.level === "crit" ? "var(--crit)" : props.level === "warn" ? "var(--warn)" : props.color,
);
</script>

<template>
  <figure class="gauge" :aria-label="`${label}: ${readout}`">
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <circle
        class="track sketch"
        :class="{ 'track--nodata': !isNum(value) }"
        cx="50"
        cy="50"
        :r="R"
        :stroke-dasharray="`${(C * ARC).toFixed(2)} ${C.toFixed(2)}`"
        transform="rotate(135 50 50)"
      />
      <circle
        v-if="isNum(value)"
        class="val"
        cx="50"
        cy="50"
        :r="R"
        :stroke="stroke"
        :stroke-dasharray="dash"
        transform="rotate(135 50 50)"
      />
    </svg>
    <div class="center">
      <span class="readout mono">{{ readout }}</span>
      <span v-if="tag" class="label tag">{{ tag }}</span>
    </div>
    <figcaption>
      <span class="label">{{ label }}</span>
      <span v-if="sub" class="sub mono">
        <span v-if="level === 'warn'" aria-hidden="true">▲ </span>
        <span v-else-if="level === 'crit'" aria-hidden="true">✕ </span>{{ sub }}
      </span>
    </figcaption>
  </figure>
</template>

<style scoped>
.gauge {
  position: relative;
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 128px;
}
svg {
  width: 112px;
  height: 112px;
}
.track {
  fill: none;
  stroke: var(--line);
  stroke-width: 6;
}
.track--nodata {
  stroke-dasharray: 3 4 !important;
}
.val {
  fill: none;
  stroke-width: 6;
  stroke-linecap: butt;
  transition: stroke-dasharray 0.5s ease;
}
.center {
  position: absolute;
  top: 34px;
  width: 112px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.readout {
  font-size: 16px;
  font-weight: 600;
}
.tag {
  font-size: 9px;
}
figcaption {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: -10px;
  gap: 2px;
  text-align: center;
}
.sub {
  font-size: 11px;
  color: var(--ink-dim);
}
</style>
