<script setup lang="ts">
// Franja del equipo: siempre visible, una tarjeta por dispositivo detectado.
import { computed, ref, watch } from "vue";
import { cpu, cpuSample, currentHost, currentSnapshot, gpus, gpuSample, historyKey, live, staleness } from "../api/live";
import { ago } from "../lib/format";
import GpuCard from "./GpuCard.vue";
import Stamp from "./Stamp.vue";
import SystemCards from "./SystemCards.vue";

const FOLD_KEY = "arena.stripFolded";
const STALE_AFTER_S = 5;

function readFold(): boolean {
  try {
    return localStorage.getItem(FOLD_KEY) === "1";
  } catch {
    return false;
  }
}

const folded = ref(readFold());
watch(folded, (v) => {
  try {
    localStorage.setItem(FOLD_KEY, v ? "1" : "0");
  } catch {
    /* sin almacenamiento */
  }
});

const host = currentHost;
const snap = currentSnapshot;
const gpuList = computed(() => gpus(host.value));
const cpuDev = computed(() => cpu(host.value));
const stale = computed(
  () => !host.value || host.value.status !== "online" || staleness.value === null || staleness.value > STALE_AFTER_S,
);
const hist = (id: string) => (host.value ? live.history[historyKey(host.value.id, id)] ?? [] : []);
const statusText = computed(() => {
  const h = host.value;
  if (!h) return "";
  const last = staleness.value === null ? "nunca" : ago(staleness.value);
  return {
    connecting: "Conectando con el agente…",
    online: "",
    offline: `Agente sin respuesta · último dato ${last}`,
    unauthorized: "El agente rechaza la conexión: token ausente o incorrecto",
    error: `Error del agente · último dato ${last}`,
  }[h.status];
});
</script>

<template>
  <section class="strip" :class="{ 'strip--folded': folded }" aria-label="Estado del equipo">
    <header class="strip__head">
      <h2 class="label">
        Equipo<span v-if="host"> · {{ host.name }}</span>
      </h2>
      <Stamp v-if="host?.simulated" :text="`simulado: ${host.simulated}`" tone="info" />
      <span v-if="statusText" class="strip__status mono" role="status">
        <span aria-hidden="true">{{ host?.status === "connecting" ? "◌" : "▲" }}</span> {{ statusText }}
        <span v-if="host?.error && host.status !== 'connecting'" class="dim">({{ host.error }})</span>
      </span>
      <button class="btn strip__fold" type="button" :aria-expanded="!folded" @click="folded = !folded">
        {{ folded ? "Desplegar" : "Plegar" }}
      </button>
    </header>

    <p v-if="!host" class="empty">
      No hay ningún equipo registrado. Arranca el servidor con <code>--agent http://127.0.0.1:9100</code>.
    </p>

    <div v-else class="strip__cards">
      <GpuCard
        v-for="d in gpuList"
        :key="d.device_id"
        :device="d"
        :sample="gpuSample(snap, d.device_id)"
        :history="hist(d.device_id)"
        :stale="stale"
        :folded="folded"
      />
      <SystemCards
        :cpu="cpuDev"
        :cpu-sample="cpuDev ? cpuSample(snap, cpuDev.device_id) : undefined"
        :cpu-history="cpuDev ? hist(cpuDev.device_id) : []"
        :ram="snap?.ram"
        :ram-history="hist('ram')"
        :stale="stale"
        :folded="folded"
      />
      <p v-if="!gpuList.length && host.status === 'online'" class="nogpu">
        Sin GPU detectada en este equipo: solo CPU y RAM.
      </p>
    </div>
  </section>
</template>

<style scoped>
.strip {
  padding: 12px var(--gap) 14px;
  border-bottom: 1px solid var(--line);
  background: rgba(10, 17, 28, 0.85);
  backdrop-filter: blur(2px);
}
.strip__head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.strip__status {
  font-size: 12px;
  color: var(--warn);
}
.strip__fold {
  margin-left: auto;
  padding: 3px 10px;
  font-size: 11px;
}
.strip__cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}
.strip--folded .strip__cards {
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}
.empty,
.nogpu {
  color: var(--ink-dim);
  font-size: 12px;
  margin: 0;
}
.nogpu {
  align-self: center;
}
.dim {
  color: var(--ink-faint);
}
</style>
