<script setup lang="ts">
import { computed } from "vue";
import { live, type Point } from "../api/live";
import type { DeviceInfo, GpuSample } from "../api/types";
import { deviceColor, shortName } from "../lib/devices";
import { fmt, gibPair, isNum, throttleReasons } from "../lib/format";
import { gpuHealth, thresholdsFor } from "../lib/thresholds";
import BarWithOverflow from "./BarWithOverflow.vue";
import BlueprintCard from "./BlueprintCard.vue";
import Sparkline from "./Sparkline.vue";
import Stamp from "./Stamp.vue";

const props = defineProps<{
  device: DeviceInfo;
  sample: GpuSample | undefined;
  history: Point[];
  stale: boolean;
  folded?: boolean;
}>();

const color = computed(() => deviceColor(props.device));
const health = computed(() => gpuHealth(props.device, props.sample, live.thresholds));
const limits = computed(() => thresholdsFor(props.device, live.thresholds));
const s = computed(() => props.sample);
const memTotal = computed(() => s.value?.mem_total_mib ?? props.device.memory_total_mib);
const throttling = computed(() => throttleReasons(s.value?.throttle));
const utils = computed(() => props.history.map((p) => p.util));
/** Cifra grande sin unidad (la unidad se pinta aparte, más pequeña). */
const big = (v: number | null | undefined) => (isNum(v) ? fmt(v, 0) : "sin datos");
const levelIcon = computed(() => (health.value.level === "crit" ? "✕" : health.value.level === "warn" ? "▲" : ""));
</script>

<template>
  <BlueprintCard
    :class="{ 'is-stale': stale }"
    :title="shortName(device.name)"
    :color="color"
    :level="stale ? 'unknown' : health.level === 'unknown' ? undefined : health.level"
    dense
  >
    <template #actions>
      <Stamp v-if="stale" text="sin datos" tone="dim" />
      <Stamp v-else-if="health.level === 'crit'" text="crítico" tone="crit" />
      <Stamp v-else-if="throttling.length" text="throttling" tone="warn" />
    </template>

    <div v-if="folded" class="line">
      <span :class="`lvl-${health.level}`">{{ levelIcon }} {{ fmt(s?.temp_c, 0, '°C') }}</span>
      <span>{{ fmt(s?.power_w, 0, 'W') }}</span>
      <span>{{ gibPair(s?.mem_used_mib, memTotal) }}</span>
    </div>

    <template v-else>
      <div class="hero">
        <div class="stat">
          <span class="label">Temperatura</span>
          <span class="num big" :class="`lvl-${health.level}`">
            <span v-if="levelIcon" aria-hidden="true">{{ levelIcon }} </span>{{ big(s?.temp_c) }}<span v-if="isNum(s?.temp_c)" class="unit">°C</span>
          </span>
        </div>
        <div class="stat">
          <span class="label">Potencia</span>
          <span class="num big">{{ big(s?.power_w) }}<span v-if="isNum(s?.power_w)" class="unit">W</span></span>
          <span v-if="s?.power_limit_w" class="sub">de {{ fmt(s?.power_limit_w, 0, 'W') }}</span>
        </div>
        <div class="stat">
          <span class="label">Uso</span>
          <span class="num big">{{ big(s?.util_gpu_pct) }}<span v-if="isNum(s?.util_gpu_pct)" class="unit">%</span></span>
        </div>
      </div>

      <div class="vram">
        <span class="label">VRAM</span>
        <span class="num val">{{ gibPair(s?.mem_used_mib, memTotal) }}</span>
      </div>
      <BarWithOverflow :used="s?.mem_used_mib" :total="memTotal" :color="color" label="VRAM" :dimension="false" />

      <Sparkline class="spark" :values="utils" :min="0" :max="100" :color="color" :height="34" label="Uso de GPU, últimos 2 minutos" />

      <p class="extra">
        {{ fmt(s?.clock_sm_mhz, 0, 'MHz') }} · vent. {{ fmt(s?.fan_pct, 0, '%') }} · {{ s?.pstate ?? 'sin datos' }}
      </p>
      <p v-if="health.reasons.length && !stale" class="reasons" :class="`lvl-${health.level}`">
        {{ health.reasons.join(' · ') }}
      </p>
      <p class="limits">aviso {{ limits.warn }} °C · crítico {{ limits.crit }} °C <span>({{ limits.source }})</span></p>
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
  grid-template-columns: repeat(3, 1fr);
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
.sub {
  font-size: 11px;
  color: var(--ink-faint);
}
.vram {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 6px;
}
.val {
  font-size: 13px;
  font-weight: 500;
}
.spark {
  margin-top: 14px;
}
.extra {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--ink-dim);
  font-variant-numeric: tabular-nums;
}
.reasons {
  margin: 6px 0 0;
  font-size: 12px;
}
.limits {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--ink-faint);
}
.lvl-warn {
  color: var(--warn);
}
.lvl-crit {
  color: var(--crit);
}
</style>
