<script setup lang="ts">
// Panel en vivo de una GPU: cifras grandes arriba y tres gráficas de los últimos 2 minutos.
import { computed } from "vue";
import { HISTORY_POINTS, live, type Point } from "../api/live";
import type { DeviceInfo, GpuSample } from "../api/types";
import { deviceColor, shortName } from "../lib/devices";
import { fmt, gibPair, isNum, throttleReasons } from "../lib/format";
import { gpuHealth, thresholdsFor } from "../lib/thresholds";
import BarWithOverflow from "./BarWithOverflow.vue";
import BlueprintCard from "./BlueprintCard.vue";
import LineChart, { type ChartLine, type ChartSeries } from "./LineChart.vue";
import Stamp from "./Stamp.vue";

const props = defineProps<{
  device: DeviceInfo;
  sample: GpuSample | undefined;
  history: Point[];
  stale: boolean;
}>();

const color = computed(() => deviceColor(props.device));
const health = computed(() => gpuHealth(props.device, props.sample, live.thresholds));
const limits = computed(() => thresholdsFor(props.device, live.thresholds));
const s = computed(() => props.sample);
const memTotal = computed(() => s.value?.mem_total_mib ?? props.device.memory_total_mib);
const throttling = computed(() => throttleReasons(s.value?.throttle));
const levelIcon = computed(() => (health.value.level === "crit" ? "✕ " : health.value.level === "warn" ? "▲ " : ""));
const big = (v: number | null | undefined) => (isNum(v) ? fmt(v, 0) : "sin datos");

/** Eje X: segundos dentro de la ventana de 2 min; el máximo es "ahora". */
const WINDOW = HISTORY_POINTS;
function points(pick: (p: Point) => number | null) {
  const h = props.history;
  const last = h.length ? h[h.length - 1].t : 0;
  return h.map((p) => ({ x: Math.max(0, WINDOW - (last - p.t)), y: pick(p) }));
}
const xFormat = (v: number) => (v >= WINDOW - 0.5 ? "ahora" : `−${Math.round(WINDOW - v)} s`);

const tempSeries = computed<ChartSeries[]>(() => [{ id: "t", label: "Temperatura", color: color.value, points: points((p) => p.temp) }]);
const tempLines = computed<ChartLine[]>(() => [
  { y: limits.value.crit, label: `crítico ${limits.value.crit} °C`, color: "var(--crit)" },
]);
const powerSeries = computed<ChartSeries[]>(() => [{ id: "p", label: "Potencia", color: color.value, points: points((p) => p.power) }]);
const powerLines = computed<ChartLine[]>(() => {
  const lim = s.value?.power_limit_w;
  return isNum(lim) ? [{ y: lim, label: "límite", color: "var(--ink-faint)" }] : [];
});
const useSeries = computed<ChartSeries[]>(() => [
  { id: "u", label: "Uso GPU", color: color.value, points: points((p) => p.util) },
  {
    id: "m",
    label: "VRAM",
    color: "var(--ink-dim)",
    dash: true,
    points: points((p) => (isNum(p.mem) && isNum(memTotal.value) && memTotal.value > 0 ? (p.mem / memTotal.value) * 100 : null)),
  },
]);
</script>

<template>
  <BlueprintCard
    :class="{ 'is-stale': stale }"
    :title="shortName(device.name)"
    :color="color"
    :level="stale ? 'unknown' : health.level === 'unknown' ? undefined : health.level"
  >
    <template #actions>
      <Stamp v-if="stale" text="sin datos" tone="dim" />
      <Stamp v-else-if="health.level === 'crit'" text="crítico" tone="crit" />
      <Stamp v-else-if="throttling.length" :text="`throttling · ${throttling.join(', ')}`" tone="warn" />
      <Stamp v-else-if="health.level === 'warn'" text="aviso" tone="warn" />
    </template>

    <div class="hero">
      <div class="stat">
        <span class="label">Temperatura</span>
        <span class="num big" :class="`lvl-${health.level}`">
          {{ levelIcon }}{{ big(s?.temp_c) }}<span v-if="isNum(s?.temp_c)" class="unit">°C</span>
        </span>
      </div>
      <div class="stat">
        <span class="label">Potencia</span>
        <span class="num big">{{ big(s?.power_w) }}<span v-if="isNum(s?.power_w)" class="unit">W</span></span>
        <span v-if="isNum(s?.power_limit_w)" class="sub">de {{ fmt(s?.power_limit_w, 0, "W") }}</span>
      </div>
      <div class="stat">
        <span class="label">Uso GPU</span>
        <span class="num big">{{ big(s?.util_gpu_pct) }}<span v-if="isNum(s?.util_gpu_pct)" class="unit">%</span></span>
        <span class="sub">{{ fmt(s?.clock_sm_mhz, 0, "MHz") }}</span>
      </div>
      <div class="stat">
        <span class="label">VRAM</span>
        <span class="num big">{{ isNum(s?.mem_used_mib) ? fmt((s?.mem_used_mib as number) / 1024, 1) : "sin datos" }}<span v-if="isNum(s?.mem_used_mib)" class="unit">GiB</span></span>
        <span class="sub">{{ gibPair(s?.mem_used_mib, memTotal) }}</span>
        <BarWithOverflow :used="s?.mem_used_mib" :total="memTotal" :color="color" label="VRAM" :dimension="false" thin />
      </div>
    </div>

    <p v-if="health.reasons.length && !stale" class="reasons" :class="`lvl-${health.level}`">{{ health.reasons.join(" · ") }}</p>

    <div class="charts">
      <LineChart title="Temperatura" :height="170" unit="°C" :series="tempSeries" :lines="tempLines" :y-min="20" :y-max="limits.crit + 5" :x-max="WINDOW" :x-format="xFormat" x-name="" area />
      <LineChart title="Potencia" :height="170" unit="W" :series="powerSeries" :lines="powerLines" :y-min="0" :x-max="WINDOW" :x-format="xFormat" x-name="" area />
      <LineChart title="Uso de GPU y VRAM" :height="170" unit="%" :series="useSeries" :y-min="0" :y-max="100" :x-max="WINDOW" :x-format="xFormat" x-name="" area />
    </div>
    <p class="foot">Últimos 2 minutos · aviso {{ limits.warn }} °C, crítico {{ limits.crit }} °C ({{ limits.source }})</p>
  </BlueprintCard>
</template>

<style scoped>
.hero {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 16px 28px;
  margin-bottom: 22px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.big {
  font-size: 44px;
  white-space: nowrap;
}
.sub {
  font-size: 12px;
  color: var(--ink-faint);
  font-variant-numeric: tabular-nums;
}
.stat :deep(.bwo) {
  margin-top: 4px;
}
.charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 22px 32px;
}
.reasons {
  margin: -8px 0 16px;
  font-size: 13px;
}
.foot {
  margin: 16px 0 0;
  font-size: 12px;
  color: var(--ink-faint);
}
.lvl-warn {
  color: var(--warn);
}
.lvl-crit {
  color: var(--crit);
}
</style>
