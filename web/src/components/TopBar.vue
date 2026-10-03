<script setup lang="ts">
import { computed } from "vue";
import { currentHost, currentSnapshot, gpus, gpuSample, hostList, live, selectHost } from "../api/live";
import { gpuHealth } from "../lib/thresholds";
import StatusChip from "./StatusChip.vue";

const host = currentHost;

const agentChip = computed(() => {
  const h = host.value;
  if (!h) return { state: "off" as const, text: "sin equipos", title: "" };
  const map = {
    connecting: { state: "pending" as const, text: "conectando" },
    online: { state: "ok" as const, text: "conectado" },
    offline: { state: "crit" as const, text: "sin respuesta" },
    unauthorized: { state: "crit" as const, text: "sin permiso" },
    error: { state: "warn" as const, text: "error" },
  };
  return { ...map[h.status], title: `${h.agent_url}${h.error ? " — " + h.error : ""}` };
});

const serverChip = computed(() =>
  live.connection === "open"
    ? { state: "ok" as const, text: "conectado" }
    : live.connection === "connecting"
      ? { state: "pending" as const, text: "conectando" }
      : { state: "crit" as const, text: "sin respuesta" },
);

const warnings = computed(() => {
  if (host.value?.status !== "online") return 0; // con datos viejos no se avisa de nada
  const snap = currentSnapshot.value;
  return gpus(host.value).filter((d) => {
    const lvl = gpuHealth(d, gpuSample(snap, d.device_id)).level;
    return lvl === "warn" || lvl === "crit";
  }).length;
});

function onSelect(e: Event) {
  selectHost(Number((e.target as HTMLSelectElement).value));
}
</script>

<template>
  <header class="topbar">
    <div class="topbar__left">
      <StatusChip label="agente" :state="agentChip.state" :text="agentChip.text" :title="agentChip.title" />
      <StatusChip label="servidor" :state="serverChip.state" :text="serverChip.text" />
      <label v-if="hostList.length > 1" class="hostsel mono">
        <span class="label">equipo</span>
        <select :value="host?.id" @change="onSelect">
          <option v-for="h in hostList" :key="h.id" :value="h.id">{{ h.name }}</option>
        </select>
      </label>
    </div>
    <h1 class="topbar__title mono">ARENA&nbsp;LLM</h1>
    <div class="topbar__right">
      <StatusChip
        v-if="warnings"
        label="avisos"
        :state="'warn'"
        :text="`${warnings} ${warnings === 1 ? 'dispositivo' : 'dispositivos'}`"
      />
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 12px;
  height: var(--topbar-h);
  padding: 0 var(--gap);
  border-bottom: 1px solid var(--line);
  background: var(--panel);
  position: sticky;
  top: 0;
  z-index: 10;
}
.topbar__left,
.topbar__right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.topbar__right {
  justify-content: flex-end;
}
.topbar__title {
  font-size: 14px;
  letter-spacing: 0.3em;
  color: var(--ink);
}
.hostsel {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.hostsel select {
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 2px 6px;
  font-size: 12px;
}
@media (max-width: 1180px) {
  .topbar {
    grid-template-columns: 1fr auto;
  }
  .topbar__title {
    display: none;
  }
}
</style>
