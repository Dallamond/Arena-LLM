<script setup lang="ts">
// Minigráfica SVG. Los huecos (null) cortan la línea: no se interpola lo que no se midió.
import { computed } from "vue";
import { isNum } from "../lib/format";

const props = withDefaults(
  defineProps<{
    values: (number | null)[];
    min?: number;
    max?: number;
    color?: string;
    height?: number;
    capacity?: number; // nº de puntos del eje X (para que no se estire al arrancar)
    label?: string;
  }>(),
  { color: "var(--accent)", height: 28, capacity: 120, label: "tendencia" },
);

const W = 120;

const bounds = computed(() => {
  const nums = props.values.filter(isNum);
  const lo = props.min ?? (nums.length ? Math.min(...nums) : 0);
  let hi = props.max ?? (nums.length ? Math.max(...nums) : 1);
  if (hi - lo < 1e-9) hi = lo + 1;
  return { lo, hi };
});

const paths = computed(() => {
  const { lo, hi } = bounds.value;
  const n = props.capacity;
  const offset = Math.max(0, n - props.values.length);
  const segs: string[] = [];
  let cur = "";
  props.values.forEach((v, i) => {
    if (!isNum(v)) {
      if (cur) segs.push(cur);
      cur = "";
      return;
    }
    const x = ((offset + i) / Math.max(1, n - 1)) * W;
    const y = props.height - 2 - ((v - lo) / (hi - lo)) * (props.height - 4);
    cur += `${cur ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  });
  if (cur) segs.push(cur);
  return segs;
});
</script>

<template>
  <svg
    class="spark"
    :viewBox="`0 0 ${W} ${height}`"
    preserveAspectRatio="none"
    :height="height"
    role="img"
    :aria-label="label"
  >
    <line class="axis" x1="0" :y1="height - 0.5" :x2="W" :y2="height - 0.5" />
    <path v-for="(d, i) in paths" :key="i" :d="d" :stroke="color" class="line" />
  </svg>
</template>

<style scoped>
.spark {
  display: block;
  width: 100%;
}
.axis {
  stroke: var(--line);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.line {
  fill: none;
  stroke-width: 1.5;
  vector-effect: non-scaling-stroke;
  stroke-linejoin: round;
}
</style>
