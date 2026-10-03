<script setup lang="ts">
// Tarjetas de CPU y RAM del equipo.
import { computed } from "vue";
import type { Point } from "../api/live";
import type { CpuSample, DeviceInfo, RamSample } from "../api/types";
import { shortName } from "../lib/devices";
import { fmt, gibPair } from "../lib/format";
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
    <div v-if="folded" class="line mono">
      <span>{{ fmt(cpuSample?.util_pct, 0, "%") }}</span>
      <span>{{ fmt(cpuSample?.freq_mhz, 0, "MHz") }}</span>
    </div>
    <template v-else>
      <div class="big mono">
        <span class="main">{{ fmt(cpuSample?.util_pct, 0, "%") }}</span>
        <span class="sec">{{ fmt(cpuSample?.freq_mhz, 0, "MHz") }}</span>
      </div>
      <p class="sub mono">{{ cpuSub }}</p>
      <span class="label tiny">uso · 2 min</span>
      <Sparkline :values="cpuUtil" :min="0" :max="100" color="var(--dev-cpu)" label="Uso de CPU, últimos 2 minutos" />
    </template>
  </BlueprintCard>

  <BlueprintCard :class="{ 'is-stale': stale }" title="RAM" color="var(--dev-ram)" dense>
    <template #actions><Stamp v-if="stale" text="sin datos" tone="dim" /></template>
    <div v-if="folded" class="line mono">
      <span>{{ gibPair(ram?.used_mib, ram?.total_mib) }}</span>
    </div>
    <template v-else>
      <div class="big mono">
        <span class="main">{{ gibPair(ram?.used_mib, ram?.total_mib) }}</span>
      </div>
      <BarWithOverflow :used="ram?.used_mib" :total="ram?.total_mib" color="var(--dev-ram)" label="RAM" />
      <span class="label tiny">en uso · 2 min</span>
      <Sparkline
        :values="ramUsed"
        :min="0"
        :max="ram?.total_mib ?? undefined"
        color="var(--dev-ram)"
        label="RAM en uso, últimos 2 minutos"
      />
    </template>
  </BlueprintCard>
</template>

<style scoped>
.line {
  display: flex;
  gap: 14px;
  font-size: 12px;
  white-space: nowrap;
}
.big {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.main {
  font-size: 22px;
  font-weight: 600;
}
.sec {
  font-size: 14px;
  color: var(--ink-dim);
}
.sub {
  margin: 0 0 10px;
  font-size: 11px;
  color: var(--ink-dim);
}
.tiny {
  display: block;
  margin-top: 10px;
  font-size: 9px;
}
</style>
