<script setup lang="ts">
import { computed } from "vue";
import { live, type Point } from "../api/live";
import type { DeviceInfo, GpuSample } from "../api/types";
import { deviceColor, shortName } from "../lib/devices";
import { fmt, gibPair, throttleReasons } from "../lib/format";
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
const temps = computed(() => props.history.map((p) => p.temp));
const utils = computed(() => props.history.map((p) => p.util));
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

    <div v-if="folded" class="line mono">
      <span :class="`lvl-${health.level}`">{{ levelIcon }} {{ fmt(s?.temp_c, 0, "°C") }}</span>
      <span>{{ fmt(s?.power_w, 0, "W") }}</span>
      <span>{{ gibPair(s?.mem_used_mib, memTotal) }}</span>
    </div>

    <template v-else>
      <div class="big mono">
        <span class="temp" :class="`lvl-${health.level}`">
          <span v-if="levelIcon" aria-hidden="true">{{ levelIcon }} </span>{{ fmt(s?.temp_c, 0, "°C") }}
        </span>
        <span class="power">
          {{ fmt(s?.power_w, 0, "W") }}
          <span class="dim" v-if="s?.power_limit_w">/ {{ fmt(s?.power_limit_w, 0) }}</span>
        </span>
      </div>

      <div class="row">
        <span class="label">VRAM</span>
        <span class="mono val">{{ gibPair(s?.mem_used_mib, memTotal) }}</span>
      </div>
      <BarWithOverflow :used="s?.mem_used_mib" :total="memTotal" :color="color" label="VRAM" />

      <dl class="grid mono">
        <div>
          <dt class="label">uso</dt>
          <dd>{{ fmt(s?.util_gpu_pct, 0, "%") }}</dd>
        </div>
        <div>
          <dt class="label">reloj</dt>
          <dd>{{ fmt(s?.clock_sm_mhz, 0, "MHz") }}</dd>
        </div>
        <div>
          <dt class="label">vent.</dt>
          <dd>{{ fmt(s?.fan_pct, 0, "%") }}</dd>
        </div>
        <div>
          <dt class="label">estado</dt>
          <dd>{{ s?.pstate ?? "sin datos" }}</dd>
        </div>
      </dl>

      <div class="sparks">
        <div>
          <span class="label">°C · 2 min</span>
          <Sparkline :values="temps" :min="20" :max="Math.max(limits.crit + 5, 60)" :color="color" label="Temperatura, últimos 2 minutos" />
        </div>
        <div>
          <span class="label">uso · 2 min</span>
          <Sparkline :values="utils" :min="0" :max="100" :color="color" label="Uso de GPU, últimos 2 minutos" />
        </div>
      </div>

      <p v-if="health.reasons.length && !stale" class="reasons mono" :class="`lvl-${health.level}`">
        {{ health.reasons.join(" · ") }}
      </p>
      <p class="limits mono">
        aviso {{ limits.warn }} °C · crítico {{ limits.crit }} °C
        <span class="dim">({{ limits.source }})</span>
      </p>
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
  margin-bottom: 8px;
}
.temp {
  font-size: 24px;
  font-weight: 600;
}
.power {
  font-size: 15px;
}
.dim {
  color: var(--ink-faint);
  font-size: 12px;
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 4px;
}
.val {
  font-size: 12px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px 8px;
  margin: 10px 0 8px;
  font-size: 12px;
}
.grid dt {
  font-size: 9px;
}
.grid dd {
  margin: 0;
  white-space: nowrap;
}
.sparks {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.sparks .label {
  font-size: 9px;
}
.reasons {
  margin: 8px 0 0;
  font-size: 11px;
}
.limits {
  margin: 6px 0 0;
  font-size: 10px;
  color: var(--ink-faint);
}
.lvl-warn {
  color: var(--warn);
}
.lvl-crit {
  color: var(--crit);
}
</style>
