<script setup lang="ts">
// Tarjetas de CPU y RAM del equipo.
import { computed } from "vue";
import type { Point } from "../api/live";
import type { CpuSample, DeviceInfo, RamSample } from "../api/types";
import { shortName } from "../lib/devices";
import { fmt, gibPair, isNum } from "../lib/format";
import BarWithOverflow from "./BarWithOverflow.vue";
import BlueprintCard from "./BlueprintCard.vue";
import Sparkline from "./Sparkline.vue";
import Stamp from "./Stamp.vue";

const props = defineProps<{
  cpu: DeviceInfo | null;
  cpuSample: CpuSample | undefined;
  cpuHistory: Point[];
  ram: RamSample | null | undefined;
  ramHistory: Point[];
  stale: boolean;
  folded?: boolean;
}>();

const big = (v: number | null | undefined) => (isNum(v) ? fmt(v, 0) : "sin datos");
const cpuUtil = computed(() => props.cpuHistory.map((p) => p.util));
const ramUsed = computed(() => props.ramHistory.map((p) => p.mem));
const cpuSub = computed(() => {
  const c = props.cpu;
  if (!c) return "";
  const parts = [c.cores ? `${c.cores} núcleos` : null, c.threads ? `${c.threads} hilos` : null].filter(Boolean);
  return parts.join(" · ");
});
</script>

<template>
  <BlueprintCard v-if="cpu" :class="{ 'is-stale': stale }" :title="shortName(cpu.name) || 'CPU'" color="var(--dev-cpu)" dense>
    <template #actions><Stamp v-if="stale" text="sin datos" tone="dim" /></template>
    <div v-if="folded" class="line">
      <span>{{ fmt(cpuSample?.util_pct, 0, "%") }}</span>
      <span>{{ fmt(cpuSample?.freq_mhz, 0, "MHz") }}</span>
    </div>
    <template v-else>
      <div class="hero">
        <div class="stat">
          <span class="label">Uso</span>
          <span class="num big">{{ big(cpuSample?.util_pct) }}<span v-if="isNum(cpuSample?.util_pct)" class="unit">%</span></span>
        </div>
        <div class="stat">
          <span class="label">Frecuencia</span>
          <span class="num big">{{ big(cpuSample?.freq_mhz) }}<span v-if="isNum(cpuSample?.freq_mhz)" class="unit">MHz</span></span>
        </div>
      </div>
      <Sparkline :values="cpuUtil" :min="0" :max="100" color="var(--dev-cpu)" :height="34" label="Uso de CPU, últimos 2 minutos" />
      <p class="sub">{{ cpuSub }}</p>
    </template>
  </BlueprintCard>

  <BlueprintCard :class="{ 'is-stale': stale }" title="RAM" color="var(--dev-ram)" dense>
    <template #actions><Stamp v-if="stale" text="sin datos" tone="dim" /></template>
    <div v-if="folded" class="line">
      <span>{{ gibPair(ram?.used_mib, ram?.total_mib) }}</span>
    </div>
    <template v-else>
      <div class="hero">
        <div class="stat">
          <span class="label">En uso</span>
          <span class="num big">{{ isNum(ram?.used_mib) ? fmt((ram?.used_mib as number) / 1024, 1) : "sin datos" }}<span v-if="isNum(ram?.used_mib)" class="unit">GiB</span></span>
        </div>
        <div class="stat">
          <span class="label">Total</span>
          <span class="num big dimmed">{{ isNum(ram?.total_mib) ? fmt((ram?.total_mib as number) / 1024, 1) : "sin datos" }}<span v-if="isNum(ram?.total_mib)" class="unit">GiB</span></span>
        </div>
      </div>
      <BarWithOverflow :used="ram?.used_mib" :total="ram?.total_mib" color="var(--dev-ram)" label="RAM" :dimension="false" />
      <Sparkline
        class="spark"
        :values="ramUsed"
        :min="0"
        :max="ram?.total_mib ?? undefined"
        color="var(--dev-ram)"
        :height="34"
        label="RAM en uso, últimos 2 minutos"
      />
    </template>
  </BlueprintCard>
</template>

<style scoped>
.line {
  display: flex;
  gap: 14px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.hero {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 16px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.big {
  font-size: 30px;
  white-space: nowrap;
}
.dimmed {
  color: var(--ink-dim);
}
.spark {
  margin-top: 14px;
}
.sub {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--ink-dim);
}
</style>
