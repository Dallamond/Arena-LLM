<script setup lang="ts">
// Servidores detectados: configuración completa, estado y cambios registrados.
import { computed, onMounted, ref } from "vue";
import { api, hostList, live, now } from "../api/live";
import type { ConfigChange, Endpoint } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import Stamp from "../components/Stamp.vue";
import { deviceColor, shortName } from "../lib/devices";
import { NO_DATA, ago, fmt, fmtDate } from "../lib/format";

const history = ref<ConfigChange[]>([]);
const detecting = ref(false);
const showArgv = ref<Record<number, boolean>>({});
const editing = ref<number | null>(null);
const aliasText = ref("");

onMounted(async () => {
  history.value = await api<ConfigChange[]>("/api/changes?limit=200").catch(() => []);
});

const changes = computed(() => {
  const seen = new Set(history.value.map((c) => c.id));
  return [...live.changes.filter((c) => !seen.has(c.id)), ...history.value];
});

const groups = computed(() =>
  hostList.value.map((h) => ({ host: h, endpoints: live.endpoints[h.id] ?? [] })).filter((g) => g.endpoints.length || true),
);

function changesFor(ep: Endpoint) {
  return changes.value.filter((c) => c.endpoint_id === ep.id).slice(0, 8);
}

async function detect() {
  detecting.value = true;
  await api("/api/endpoints/detect", { method: "POST" }).catch(() => {});
  setTimeout(() => (detecting.value = false), 1500);
}

async function saveAlias(ep: Endpoint) {
  await api(`/api/endpoints/${ep.id}`, { method: "PATCH", body: JSON.stringify({ alias: aliasText.value }) });
  ep.alias = aliasText.value.trim() || null;
  editing.value = null;
}

function gpuOf(hostId: number, deviceId: string) {
  const d = live.hosts[hostId]?.devices.find((x) => x.device_id === deviceId);
  return d ? { name: shortName(d.name), color: deviceColor(d) } : { name: deviceId, color: "var(--ink-dim)" };
}

function val(v: unknown): string {
  if (v === undefined || v === null) return "—";
  if (Array.isArray(v)) return v.join(" · ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const KIND: Record<string, { text: string; tone: "info" | "warn" | "crit" | "dim" }> = {
  nuevo: { text: "nuevo", tone: "info" },
  cambio: { text: "config cambiada", tone: "warn" },
  reinicio: { text: "reinicio", tone: "dim" },
  detenido: { text: "detenido", tone: "crit" },
  vuelve: { text: "vuelve", tone: "info" },
  listo: { text: "cargado", tone: "info" },
};
const STATUS_TONE: Record<string, "info" | "warn" | "crit" | "dim"> = {
  listo: "info",
  cargando: "warn",
  detenido: "dim",
};
</script>

<template>
  <div class="page">
    <div class="head">
      <h2 class="title">Servidores</h2>
      <span class="mono dim small">Arena detecta los <code>llama-server</code> que lanzas; no los arranca ni los para.</span>
      <button class="btn" type="button" :disabled="detecting" @click="detect">{{ detecting ? "Detectando…" : "Detectar ahora" }}</button>
    </div>

    <template v-for="g in groups" :key="g.host.id">
      <h3 class="label host">Equipo · {{ g.host.name }}</h3>
      <div v-if="!g.endpoints.length" class="empty">
        <p>Ningún servidor detectado en este equipo.</p>
        <p class="mono dim">Lanza <code>llama-server</code>; aparece aquí en unos 5 segundos con su configuración.</p>
      </div>
      <BlueprintCard
        v-for="ep in g.endpoints"
        :key="ep.id"
        :fig="`:${ep.base_url.split(':').pop()}`"
        :title="ep.alias || ep.snapshot?.model_file || ep.base_url"
        class="ep"
        :class="{ 'ep--off': ep.status === 'detenido' }"
      >
        <template #actions>
          <Stamp :text="ep.status" :tone="STATUS_TONE[ep.status] ?? 'crit'" />
          <RouterLink v-if="ep.status === 'listo'" class="btn btn--primary" :to="{ path: '/calidad', query: { endpoint: ep.id } }">▶ Probar</RouterLink>
        </template>

        <div class="cols">
          <dl class="mono kv">
            <div><dt>modelo</dt><dd>{{ ep.snapshot?.derived?.model_path ?? ep.snapshot?.model_path ?? NO_DATA }}</dd></div>
            <div><dt>cuantización</dt><dd>{{ ep.snapshot?.derived?.model_ftype ?? NO_DATA }}</dd></div>
            <div>
              <dt>contexto</dt>
              <dd>
                {{ fmt(ep.snapshot?.derived?.n_ctx_slot) }} por slot × {{ fmt(ep.snapshot?.derived?.total_slots) }} slots
                <span class="dim">(total {{ fmt(ep.snapshot?.derived?.n_ctx_total) }})</span>
              </dd>
            </div>
            <div>
              <dt>slots ocupados</dt>
              <dd>{{ ep.snapshot?.derived?.slots_busy ?? NO_DATA }}</dd>
            </div>
            <div><dt>build</dt><dd>{{ ep.snapshot?.derived?.build_info ?? NO_DATA }}</dd></div>
            <div>
              <dt>GPU</dt>
              <dd>
                <span v-for="u in ep.snapshot?.devices ?? []" :key="u.device_id" :style="{ color: gpuOf(g.host.id, u.device_id).color }">
                  ■ {{ gpuOf(g.host.id, u.device_id).name }}
                </span>
                <span v-if="!ep.snapshot?.devices?.length" class="dim">sin asociar (no se pudo leer qué GPU usa)</span>
              </dd>
            </div>
            <div><dt>url</dt><dd>{{ ep.base_url }}<span v-if="ep.snapshot?.port_source === 'default'" class="dim"> (puerto por defecto)</span></dd></div>
            <div><dt>pid · arranque</dt><dd>{{ ep.snapshot?.pid ?? "?" }} · {{ ep.snapshot?.started_at?.replace("T", " ").slice(0, 19) ?? NO_DATA }}</dd></div>
            <div><dt>visto</dt><dd>{{ ago(now - ep.last_seen_at) }}</dd></div>
            <div>
              <dt>alias</dt>
              <dd>
                <template v-if="editing === ep.id">
                  <input v-model="aliasText" class="alias" type="text" maxlength="60" @keyup.enter="saveAlias(ep)" />
                  <button class="btn tiny" type="button" @click="saveAlias(ep)">Guardar</button>
                </template>
                <template v-else>
                  {{ ep.alias ?? "—" }}
                  <button class="btn tiny" type="button" @click="(editing = ep.id), (aliasText = ep.alias ?? '')">Editar</button>
                </template>
              </dd>
            </div>
          </dl>

          <div>
            <h4 class="label">Flags detectados</h4>
            <div class="flags mono">
              <span v-for="(v, k) in ep.snapshot?.flags ?? {}" :key="k" class="flag" v-show="k !== 'model'">{{ k }} <b>{{ val(v) }}</b></span>
              <span v-for="(v, k) in ep.snapshot?.unknown ?? {}" :key="'u' + k" class="flag flag--unknown" title="Flag no reconocido: se guarda tal cual">
                {{ k }} <b>{{ val(v) }}</b> ?
              </span>
            </div>
            <button class="btn tiny" type="button" :aria-expanded="!!showArgv[ep.id]" @click="showArgv[ep.id] = !showArgv[ep.id]">
              {{ showArgv[ep.id] ? "Ocultar" : "Ver" }} línea de comandos
            </button>
            <pre v-if="showArgv[ep.id]" class="argv mono">{{ (ep.snapshot?.argv ?? []).join(" ") }}</pre>

            <h4 class="label hist">Cambios de configuración</h4>
            <ul class="changes mono">
              <li v-for="c in changesFor(ep)" :key="c.id">
                <span class="dim">{{ fmtDate(c.t, true) }}</span>
                <Stamp :text="KIND[c.kind]?.text ?? c.kind" :tone="KIND[c.kind]?.tone ?? 'dim'" :tilt="0" />
                <span v-if="c.diff" class="diff">
                  <span v-for="(d, k) in c.diff" :key="k">{{ k }}: {{ val(d[0]) }} → <b>{{ val(d[1]) }}</b></span>
                </span>
              </li>
              <li v-if="!changesFor(ep).length" class="dim">Sin cambios registrados.</li>
            </ul>
          </div>
        </div>
      </BlueprintCard>
    </template>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.head .btn {
  margin-left: auto;
}
.title {
  font-size: 18px;
}
.host {
  margin: 18px 0 10px;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 11px;
}
.empty {
  border: 1px dashed var(--line-strong);
  padding: 18px;
}
.empty p {
  margin: 0 0 6px;
}
.ep {
  margin-bottom: 16px;
}
.ep--off {
  opacity: 0.6;
}
.cols {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) minmax(300px, 1fr);
  gap: 22px;
}
@media (max-width: 1200px) {
  .cols {
    grid-template-columns: 1fr;
  }
}
.kv {
  margin: 0;
  font-size: 12px;
}
.kv div {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 10px;
  padding: 3px 0;
  border-bottom: 1px dotted var(--line);
}
.kv dt {
  color: var(--ink-dim);
}
.kv dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.flags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 6px 0 8px;
}
.flag {
  border: 1px solid var(--line);
  padding: 1px 6px;
  font-size: 11px;
  color: var(--ink-dim);
}
.flag b {
  color: var(--ink);
  font-weight: 600;
}
.flag--unknown {
  border-style: dashed;
}
.argv {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 11px;
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 8px;
}
.hist {
  margin-top: 14px;
}
.changes {
  list-style: none;
  padding: 0;
  margin: 6px 0 0;
  font-size: 11px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.changes li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  flex-wrap: wrap;
}
.diff {
  display: flex;
  flex-direction: column;
}
.btn.tiny {
  padding: 1px 8px;
  font-size: 11px;
  margin-left: 6px;
}
.alias {
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 2px 6px;
  font-family: var(--font-mono);
  font-size: 12px;
}
code {
  font-family: var(--font-mono);
}
</style>
