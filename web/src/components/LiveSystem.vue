<script setup lang="ts">
// Panel en vivo de CPU y RAM: cifras grandes y gráficas de los últimos 2 minutos.
import { computed } from "vue";
import { HISTORY_POINTS, type Point } from "../api/live";
import type { CpuSample, DeviceInfo, RamSample } from "../api/types";
import { shortName } from "../lib/devices";
import { fmt, gibPair, isNum } from "../lib/format";
import BarWithOverflow from "./BarWithOverflow.vue";
import BlueprintCard from "./BlueprintCard.vue";
import LineChart, { type ChartSeries } from "./LineChart.vue";
import Stamp from "./Stamp.vue";

const props = defineProps<{
  cpu: DeviceInfo | null;
  cpuSample: CpuSample | undefined;
  cpuHistory: Point[];
  ram: RamSample | null | undefined;
  ramHistory: Point[];
  stale: boolean;
}>();

const WINDOW = HISTORY_POINTS;
function points(h: Point[], pick: (p: Point) => number | null) {
  const last = h.length ? h[h.length - 1].t : 0;
  return h.map((p) => ({ x: Math.max(0, WINDOW - (last - p.t)), y: pick(p) }));
}
const xFormat = (v: number) => (v >= WINDOW - 0.5 ? "ahora" : `−${Math.round(WINDOW - v)} s`);
const big = (v: number | null | undefined) => (isNum(v) ? fmt(v, 0) : "sin datos");
const gib = (mib: number | null | undefined) => (isNum(mib) ? mib / 1024 : null);

const cpuSeries = computed<ChartSeries[]>(() => [
  { id: "c", label: "CPU", color: "var(--dev-cpu)", points: points(props.cpuHistory, (p) => p.util) },
]);
const ramSeries = computed<ChartSeries[]>(() => [
  { id: "r", label: "RAM", color: "var(--dev-ram)", points: points(props.ramHistory, (p) => gib(p.mem)) },
]);
const ramMax = computed(() => gib(props.ram?.total_mib) ?? undefined);
const cpuSub = computed(() => {
  const c = props.cpu;
  if (!c) return "";
  return [c.cores ? `${c.cores} núcleos` : null, c.threads ? `${c.threads} hilos` : null].filter(Boolean).join(" · ");
});
</script>

<template>
  <div class="sys">
    <BlueprintCard v-if="cpu" :class="{ 'is-stale': stale }" :title="shortName(cpu.name) || 'CPU'" color="var(--dev-cpu)">
      <template #actions><Stamp v-if="stale" text="sin datos" tone="dim" /></template>
      <div class="hero">
        <div class="stat">
          <span class="label">Uso</span>
          <span class="num big">{{ big(cpuSample?.util_pct) }}<span v-if="isNum(cpuSample?.util_pct)" class="unit">%</span></span>
          <span class="sub">{{ cpuSub }}</span>
        </div>
        <div class="stat">
          <span class="label">Frecuencia</span>
          <span class="num big">{{ big(cpuSample?.freq_mhz) }}<span v-if="isNum(cpuSample?.freq_mhz)" class="unit">MHz</span></span>
        </div>
      </div>
      <LineChart :height="170" title="Uso de CPU" unit="%" :series="cpuSeries" :y-min="0" :y-max="100" :x-max="WINDOW" :x-format="xFormat" x-name="" area />
    </BlueprintCard>

    <BlueprintCard :class="{ 'is-stale': stale }" title="RAM" color="var(--dev-ram)">
      <template #actions><Stamp v-if="stale" text="sin datos" tone="dim" /></template>
      <div class="hero">
        <div class="stat">
          <span class="label">En uso</span>
          <span class="num big">{{ isNum(ram?.used_mib) ? fmt((ram?.used_mib as number) / 1024, 1) : "sin datos" }}<span v-if="isNum(ram?.used_mib)" class="unit">GiB</span></span>
          <span class="sub">{{ gibPair(ram?.used_mib, ram?.total_mib) }}</span>
        </div>
        <div class="stat">
          <BarWithOverflow :used="ram?.used_mib" :total="ram?.total_mib" color="var(--dev-ram)" label="RAM" :dimension="false" />
        </div>
      </div>
      <LineChart :height="170" title="RAM en uso" unit="GiB" :digits="1" :series="ramSeries" :y-min="0" :y-max="ramMax" :x-max="WINDOW" :x-format="xFormat" x-name="" area />
    </BlueprintCard>
  </div>
</template>

<style scoped>
.sys {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: 20px;
}
.hero {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 28px;
  margin-bottom: 22px;
  align-items: end;
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
</style>
