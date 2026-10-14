<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { cpu, cpuSample, currentHost, currentSnapshot, gpus, gpuSample, historyKey, live, staleness } from "../api/live";
import type { DetectedServer, ServersResponse } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import LiveGpu from "../components/LiveGpu.vue";
import LiveSystem from "../components/LiveSystem.vue";
import Stamp from "../components/Stamp.vue";
import StatusChip from "../components/StatusChip.vue";
import { deviceColor, shortName } from "../lib/devices";
import { ago, fmt, gib } from "../lib/format";

const host = currentHost;
const snap = currentSnapshot;
const gpuList = computed(() => gpus(host.value));
const cpuDev = computed(() => cpu(host.value));
const STALE_AFTER_S = 5;
const stale = computed(
  () => !host.value || host.value.status !== "online" || staleness.value === null || staleness.value > STALE_AFTER_S,
);
const hist = (id: string) => (host.value ? live.history[historyKey(host.value.id, id)] ?? [] : []);

// --- servidores detectados (el agente cachea 2 s; aquí se piden cada 5 s)
const SERVERS_EVERY_MS = 5000;
const servers = ref<DetectedServer[] | null>(null);
const serversError = ref<string | null>(null);
const serversAt = ref<number | null>(null);
const loading = ref(false);
let timer: number | undefined;

/** `manual`: lo pidió el usuario (se muestra "Detectando…"); el refresco periódico es silencioso. */
async function loadServers(manual = false) {
  const h = host.value;
  if (!h || h.status !== "online") return;
  if (manual) loading.value = true;
  try {
    const r = await fetch(`/api/hosts/${h.id}/servers`);
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail ?? `HTTP ${r.status}`);
    const data = body as ServersResponse;
    servers.value = data.servers;
    const errs = Object.entries(data.errors);
    serversError.value = errs.length ? errs.map(([k, v]) => `${k}: ${v}`).join(" · ") : null;
    serversAt.value = Date.now() / 1000;
  } catch (e) {
    serversError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadServers();
  timer = window.setInterval(() => loadServers(), SERVERS_EVERY_MS);
});
onBeforeUnmount(() => window.clearInterval(timer));
// Clave de texto: solo se vuelve a detectar si cambia el equipo o su estado
// (un array nuevo dispararía el watch con cada evento del equipo).
watch(
  () => `${host.value?.id}|${host.value?.status}`,
  () => {
    servers.value = null;
    loadServers();
  },
);

function gpuName(id: string): { name: string; color: string } | null {
  const d = host.value?.devices.find((x) => x.device_id === id);
  return d ? { name: shortName(d.name), color: deviceColor(d) } : null;
}

function flagText(v: unknown): string {
  if (v === undefined || v === null) return "—";
  if (Array.isArray(v)) return v.join(" · ");
  return String(v);
}

const expanded = ref<Record<number, boolean>>({});
</script>

<template>
  <div class="page">
    <div class="page__head">
      <h2 class="page__title">Panel</h2>
      <StatusChip
        label="en vivo"
        :state="host?.status === 'online' ? 'ok' : 'off'"
        :text="host?.status === 'online' ? `cada ${fmt(snap?.interval_s ?? 1, 0)} s` : 'detenido'"
      />
    </div>

    <div v-if="!host" class="empty">
      <p>Ningún equipo registrado.</p>
      <p class="dim">Arranca el agente y el servidor con <code>scripts\start-server.bat --agent http://127.0.0.1:9100</code></p>
    </div>

    <template v-else>
      <!-- En vivo: cifras grandes y gráficas de los últimos 2 minutos -->
      <div class="live">
        <LiveGpu
          v-for="d in gpuList"
          :key="d.device_id"
          :device="d"
          :sample="gpuSample(snap, d.device_id)"
          :history="hist(d.device_id)"
          :stale="stale"
        />
        <LiveSystem
          :cpu="cpuDev"
          :cpu-sample="cpuDev ? cpuSample(snap, cpuDev.device_id) : undefined"
          :cpu-history="cpuDev ? hist(cpuDev.device_id) : []"
          :ram="snap?.ram"
          :ram-history="hist('ram')"
          :stale="stale"
        />
        <p v-if="!gpuList.length && host.status === 'online'" class="dim">Sin GPU detectada en este equipo: solo CPU y RAM.</p>
      </div>

      <!-- Servidores detectados -->
      <BlueprintCard title="Servidores detectados" class="gap">
        <template #actions>
          <span v-if="serversAt" class="dim small">{{ ago(Date.now() / 1000 - serversAt) }}</span>
          <button class="btn" type="button" :disabled="loading || host.status !== 'online'" @click="loadServers(true)">
            {{ loading ? "Detectando…" : "Detectar ahora" }}
          </button>
        </template>

        <p v-if="serversError" class="error mono" role="alert">▲ {{ serversError }}</p>

        <div v-if="host.status !== 'online'" class="empty">
          <p>El agente no responde: no se pueden detectar servidores.</p>
          <p class="dim">Último dato {{ staleness === null ? "nunca" : ago(staleness) }}.</p>
        </div>
        <div v-else-if="servers && !servers.length" class="empty">
          <p>Ningún servidor detectado.</p>
          <p class="dim">Lanza <code>llama-server</code> como siempre; Arena lo detecta solo en unos segundos.</p>
          <button class="btn btn--primary" type="button" @click="loadServers(true)">Detectar ahora</button>
        </div>
        <ul v-else-if="servers" class="servers">
          <li v-for="s in servers" :key="s.pid" class="server">
            <div class="server__head mono">
              <span class="server__port">:{{ s.port ?? "?" }}</span>
              <span v-if="s.port_source === 'default'" class="dim small">(puerto por defecto)</span>
              <span class="server__model">{{ s.model_file ?? s.flags.hf_repo ?? "modelo sin identificar" }}</span>
              <span v-for="u in s.devices" :key="u.device_id" class="server__gpu" :style="{ color: gpuName(u.device_id)?.color }">
                ■ {{ gpuName(u.device_id)?.name ?? u.device_id }}
              </span>
              <Stamp v-if="!s.devices.length" text="gpu sin asociar" tone="dim" />
            </div>
            <dl class="flags mono">
              <div><dt class="label">ctx</dt><dd>{{ flagText(s.flags.ctx) }}</dd></div>
              <div><dt class="label">-ngl</dt><dd>{{ flagText(s.flags.ngl) }}</dd></div>
              <div><dt class="label">slots</dt><dd>{{ flagText(s.flags.parallel) }}</dd></div>
              <div><dt class="label">-fa</dt><dd>{{ flagText(s.flags.flash_attn) }}</dd></div>
              <div><dt class="label">-ts</dt><dd>{{ flagText(s.flags.tensor_split) }}</dd></div>
              <div><dt class="label">KV</dt><dd>{{ flagText(s.flags.cache_type_k) }}/{{ flagText(s.flags.cache_type_v) }}</dd></div>
              <div><dt class="label">pid</dt><dd>{{ s.pid }}</dd></div>
            </dl>
            <button class="btn small-btn" type="button" :aria-expanded="!!expanded[s.pid]" @click="expanded[s.pid] = !expanded[s.pid]">
              {{ expanded[s.pid] ? "Ocultar línea de comandos" : "Ver línea de comandos" }}
            </button>
            <pre v-if="expanded[s.pid]" class="argv mono">{{ s.argv.join(" ") }}</pre>
            <p v-if="Object.keys(s.unknown).length" class="dim small">
              Flags no reconocidos (guardados tal cual): {{ Object.keys(s.unknown).join(", ") }}
            </p>
          </li>
        </ul>
        <p v-else class="dim">Detectando…</p>
      </BlueprintCard>

      <!-- Ficha del equipo -->
      <BlueprintCard :title="host.host?.hostname ?? host.name" class="gap">
        <template #actions>
          <Stamp v-if="host.simulated" :text="`simulado · ${host.simulated}`" />
        </template>
        <dl class="specs mono">
          <div><dt class="label">sistema</dt><dd>{{ host.host?.os_version ?? "sin datos" }}</dd></div>
          <div><dt class="label">cpu</dt><dd>{{ host.host?.cpu_model ?? "sin datos" }}</dd></div>
          <div>
            <dt class="label">núcleos / hilos</dt>
            <dd>{{ host.host?.cpu_cores ?? "sin datos" }} / {{ host.host?.cpu_threads ?? "sin datos" }}</dd>
          </div>
          <div><dt class="label">ram</dt><dd>{{ gib(host.host?.ram_total_mib) }}</dd></div>
          <div v-for="d in gpuList" :key="d.device_id">
            <dt class="label" :style="{ color: deviceColor(d) }">gpu {{ d.index ?? "" }}</dt>
            <dd>
              {{ d.name ?? "sin datos" }} · {{ gib(d.memory_total_mib, 0) }} · driver {{ d.driver ?? "sin datos" }}
              <span v-if="d.driver_model"> · {{ d.driver_model }}</span>
              <span v-if="d.compute_capability"> · CC {{ d.compute_capability }}</span>
            </dd>
          </div>
          <div>
            <dt class="label">agente</dt>
            <dd>{{ host.agent_url }} · v{{ host.agent_version ?? "?" }} · {{ host.providers.join(", ") }}</dd>
          </div>
        </dl>
      </BlueprintCard>
    </template>
  </div>
</template>

<style scoped>
.page__head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.page__title {
  font-size: 28px;
  letter-spacing: -0.02em;
}
.gap {
  margin-top: 20px;
}
.specs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 8px 24px;
  margin: 0;
  font-size: 12px;
}
.specs dd {
  margin: 2px 0 0;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.live {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.empty {
  border: 1px dashed var(--line-strong);
  padding: 22px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.empty p {
  margin: 0;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 11px;
}
.error {
  color: var(--warn);
  font-size: 12px;
}
.servers {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.server {
  border: 1px solid var(--line);
  padding: 10px 12px;
  background: var(--panel-raised);
}
.server__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px;
  font-size: 13px;
}
.server__port {
  color: var(--accent);
  font-weight: 600;
}
.server__model {
  color: var(--ink);
}
.flags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 18px;
  margin: 8px 0;
  font-size: 12px;
}
.flags dd {
  margin: 0;
}
.small-btn {
  padding: 2px 8px;
  font-size: 11px;
}
.argv {
  margin: 8px 0 0;
  padding: 8px;
  background: var(--bg);
  border: 1px solid var(--line);
  font-size: 11px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
code {
  font-family: var(--font-mono);
  color: var(--ink);
}
</style>
