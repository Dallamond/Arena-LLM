<script setup lang="ts">
// Barra de memoria: lo ocupado va sólido, lo que se desborda a RAM va rayado,
// y debajo la línea de cota con la capacidad (├──── 12,0 GiB ────┤).
import { computed } from "vue";
import { fmt, isNum } from "../lib/format";

const props = withDefaults(
  defineProps<{
    used: number | null | undefined; // MiB
    total: number | null | undefined; // MiB
    overflow?: number | null; // MiB que no caben (se dibuja rayado tras la barra)
    color?: string;
    label?: string; // texto accesible
    dimension?: boolean;
    thin?: boolean;
  }>(),
  { overflow: null, color: "var(--accent)", label: "memoria", dimension: true, thin: false },
);

const valid = computed(() => isNum(props.used) && isNum(props.total) && (props.total as number) > 0);
const scale = computed(() => {
  if (!valid.value) return 1;
  const t = props.total as number;
  return t + (isNum(props.overflow) ? props.overflow : 0);
});
const usedPct = computed(() => (valid.value ? (Math.min(props.used as number, props.total as number) / scale.value) * 100 : 0));
const totalPct = computed(() => (valid.value ? ((props.total as number) / scale.value) * 100 : 100));
const overPct = computed(() => (valid.value && isNum(props.overflow) ? (props.overflow / scale.value) * 100 : 0));
const capacity = computed(() => (isNum(props.total) ? `${fmt(props.total / 1024, 1)} GiB` : "sin datos"));
const ariaText = computed(() =>
  valid.value
    ? `${props.label}: ${fmt((props.used as number) / 1024, 1)} de ${capacity.value}` +
      (overPct.value ? `, ${fmt((props.overflow as number) / 1024, 1)} GiB desbordados a RAM` : "")
    : `${props.label}: sin datos`,
);
</script>

<template>
  <div class="bwo" :class="{ 'bwo--thin': thin }" role="img" :aria-label="ariaText" :style="{ '--bar-color': color }">
    <div class="bwo__track" :class="{ 'bwo__track--nodata': !valid }">
      <div class="bwo__cap" :style="{ width: totalPct + '%' }">
        <div class="bwo__used" :style="{ width: (usedPct / totalPct) * 100 + '%' }" />
      </div>
      <div v-if="overPct" class="bwo__over" :style="{ width: overPct + '%' }" />
    </div>
    <div v-if="dimension" class="bwo__dim mono" aria-hidden="true">
      <span class="tick" /><span class="rule" /><span class="dim-label">{{ capacity }}</span><span class="rule" /><span
        class="tick"
      />
    </div>
  </div>
</template>

<style scoped>
.bwo__track {
  display: flex;
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--panel-raised);
}
.bwo--thin .bwo__track {
  height: 5px;
}
.bwo__track--nodata {
  background: repeating-linear-gradient(90deg, var(--line) 0 4px, transparent 4px 8px);
}
.bwo__cap {
  height: 100%;
}
.bwo__used {
  height: 100%;
  border-radius: 999px;
  background: var(--bar-color);
  transition: width 0.4s ease;
}
.bwo__over {
  height: 100%;
  background: repeating-linear-gradient(-45deg, var(--dev-ram) 0 2px, transparent 2px 6px);
}
.bwo__dim {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  font-size: 11px;
  color: var(--ink-faint);
}
.tick {
  width: 1px;
  height: 6px;
  background: var(--ink-faint);
}
.rule {
  flex: 1;
  height: 1px;
  background: var(--line-strong);
}
.dim-label {
  white-space: nowrap;
}
</style>
