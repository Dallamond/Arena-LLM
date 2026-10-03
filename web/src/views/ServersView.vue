<script setup lang="ts">
// Servidores detectados: configuración completa, estado y cambios registrados.
import { computed, onMounted, ref } from "vue";
import { api, hostList, live, now } from "../api/live";
import type { ConfigChange, Endpoint } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import GgufList from "../components/GgufList.vue";
import Stamp from "../components/Stamp.vue";
import { deviceColor, shortName } from "../lib/devices";
import { NO_DATA, ago, fmt, fmtDate } from "../lib/format";

const history = ref<ConfigChange[]>([]);
const detecting = ref(false);
const showArgv = ref<Record<number, boolean>>({});
const editing = ref<number | null>(null);
const aliasText = ref("");
const tab = ref<"running" | "disk">("running");
const diskOpened = ref(false); // la lista de GGUF se monta al abrir la pestaña por primera vez
const diskCount = ref<Record<number, { n: number; bytes: number }>>({});
const diskTotals = computed(() => Object.values(diskCount.value).reduce((a, c) => ({ n: a.n + c.n, bytes: a.bytes + c.bytes }), { n: 0, bytes: 0 }));
const runningCount = computed(() => groups.value.reduce((a, g) => a + g.endpoints.filter((e) => e.status !== "detenido").length, 0));

function openTab(t: "running" | "disk") {
  tab.value = t;
  if (t === "disk") diskOpened.value = true;
}

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
  await patchEndpoint(ep, { alias: aliasText.value });
  editing.value = null;
}

// --- alta manual --------------------------------------------------------------
const adding = ref(false);
const form = ref({ host_id: 0, base_url: "http://127.0.0.1:8080", alias: "", device_ids: [] as string[] });
const formError = ref<string | null>(null);
const saving = ref(false);

function hostGpus(hostId: number) {
  return (live.hosts[hostId]?.devices ?? []).filter((d) => d.kind === "gpu");
}

function openAdd() {
  form.value = { host_id: hostList.value[0]?.id ?? 0, base_url: "http://127.0.0.1:8080", alias: "", device_ids: [] };
  formError.value = null;
  adding.value = true;
}

async function addEndpoint() {
  saving.value = true;
  formError.value = null;
  try {
    const f = form.value;
    await api("/api/endpoints", {
      method: "POST",
      body: JSON.stringify({ ...f, alias: f.alias || null, device_ids: f.device_ids.length ? f.device_ids : null }),
    });
    adding.value = false;
    openTab("running");
  } catch (e) {
    formError.value = (e as Error).message;
  } finally {
    saving.value = false;
  }
}

// --- GPU asociadas a mano y baja -------------------------------------------------
const editingGpus = ref<number | null>(null);
const gpuChoice = ref<string[]>([]);
const actionError = ref<Record<number, string>>({});
const confirmDelete = ref<number | null>(null);

function startGpuEdit(ep: Endpoint) {
  editingGpus.value = ep.id;
  gpuChoice.value = [...(ep.device_ids ?? (ep.snapshot?.devices ?? []).map((d) => d.device_id))];
}

async function patchEndpoint(ep: Endpoint, body: Record<string, unknown>) {
  try {
    await api(`/api/endpoints/${ep.id}`, { method: "PATCH", body: JSON.stringify(body) });
    delete actionError.value[ep.id];
    editingGpus.value = null;
  } catch (e) {
    actionError.value[ep.id] = (e as Error).message;
  }
}

async function removeEndpoint(ep: Endpoint) {
  try {
    await api(`/api/endpoints/${ep.id}`, { method: "DELETE" });
    confirmDelete.value = null;
  } catch (e) {
    actionError.value[ep.id] = (e as Error).message;
  }
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
  manual: { text: "alta manual", tone: "info" },
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
      <span class="dim small">Arena detecta los <code>llama-server</code> que lanzas; no los arranca ni los para.</span>
      <div class="head__actions">
        <button class="btn" type="button" :aria-expanded="adding" @click="adding ? (adding = false) : openAdd()">＋ Añadir a mano</button>
        <button class="btn" type="button" :disabled="detecting" @click="detect">{{ detecting ? "Detectando…" : "Detectar ahora" }}</button>
      </div>
    </div>

    <BlueprintCard v-if="adding" title="Añadir un servidor a mano" class="ep">
      <p class="dim small intro">
        Para un <code>llama-server</code> que Arena no detecta solo (otra máquina sin agente, un contenedor, otro usuario…).
        Se consulta por HTTP cada 5 s; sin línea de comandos, los datos salen de <code>/props</code>. La telemetría es la del equipo elegido.
      </p>
      <form class="addform" @submit.prevent="addEndpoint">
        <label>
          <span class="label">Equipo (telemetría)</span>
          <select v-model.number="form.host_id" @change="form.device_ids = []">
            <option v-for="h in hostList" :key="h.id" :value="h.id">{{ h.name }}</option>
          </select>
        </label>
        <label class="grow">
          <span class="label">URL del servidor</span>
          <input v-model="form.base_url" class="mono" type="text" required placeholder="http://127.0.0.1:8080" />
        </label>
        <label>
          <span class="label">Alias (opcional)</span>
          <input v-model="form.alias" type="text" maxlength="60" />
        </label>
        <fieldset v-if="hostGpus(form.host_id).length" class="gpus">
          <legend class="label">GPU que usa (opcional)</legend>
          <label v-for="d in hostGpus(form.host_id)" :key="d.device_id" class="check">
            <input v-model="form.device_ids" type="checkbox" :value="d.device_id" />
            <span :style="{ color: deviceColor(d) }" aria-hidden="true">■</span> {{ shortName(d.name) }}
          </label>
        </fieldset>
        <div class="formactions">
          <button class="btn btn--primary" type="submit" :disabled="saving || !form.host_id">{{ saving ? "Guardando…" : "Añadir" }}</button>
          <button class="btn" type="button" @click="adding = false">Cancelar</button>
          <span v-if="formError" class="err" role="alert">✕ {{ formError }}</span>
        </div>
      </form>
    </BlueprintCard>

    <div class="tabs" role="tablist">
      <button role="tab" type="button" class="tab" :aria-selected="tab === 'running'" @click="openTab('running')">
        En marcha <span class="count">{{ runningCount }}</span>
      </button>
      <button role="tab" type="button" class="tab" :aria-selected="tab === 'disk'" @click="openTab('disk')">
        GGUF en disco <span class="count">{{ diskOpened ? diskTotals.n : "·" }}</span>
        <span v-if="diskOpened && diskTotals.bytes" class="dim small">{{ fmt(diskTotals.bytes / 1024 ** 3, 1) }} GiB</span>
      </button>
    </div>

    <div v-if="diskOpened" v-show="tab === 'disk'">
      <template v-for="g in groups" :key="g.host.id">
        <h3 class="label host">Equipo · {{ g.host.name }}</h3>
        <GgufList :host-id="g.host.id" @count="(n, bytes) => (diskCount[g.host.id] = { n, bytes })" />
      </template>
    </div>

    <div v-show="tab === 'running'">
    <template v-for="g in groups" :key="g.host.id">
      <h3 class="label host">Equipo · {{ g.host.name }}</h3>
      <div v-if="!g.endpoints.length" class="empty">
        <p>Ningún servidor detectado en este equipo.</p>
        <p class="dim">Lanza <code>llama-server</code>; aparece aquí en unos 5 segundos con su configuración.</p>
      </div>
      <BlueprintCard
        v-for="ep in g.endpoints"
        :key="ep.id"
        :title="`:${ep.base_url.split(':').pop()} · ${ep.alias || ep.snapshot?.model_file || ep.base_url}`"
        class="ep"
        :class="{ 'ep--off': ep.status === 'detenido' }"
      >
        <template #actions>
          <Stamp v-if="ep.manual" text="manual" tone="dim" :tilt="0" />
          <Stamp :text="ep.status" :tone="STATUS_TONE[ep.status] ?? 'crit'" />
          <template v-if="ep.manual || ep.status === 'detenido'">
            <button v-if="confirmDelete !== ep.id" class="btn" type="button" @click="confirmDelete = ep.id">Quitar</button>
            <template v-else>
              <button class="btn btn--danger" type="button" @click="removeEndpoint(ep)">Quitar y borrar su historial</button>
              <button class="btn" type="button" @click="confirmDelete = null">No</button>
            </template>
          </template>
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
                <template v-if="editingGpus === ep.id">
                  <label v-for="d in hostGpus(g.host.id)" :key="d.device_id" class="check">
                    <input v-model="gpuChoice" type="checkbox" :value="d.device_id" />
                    <span :style="{ color: deviceColor(d) }" aria-hidden="true">■</span> {{ shortName(d.name) }}
                  </label>
                  <button class="btn tiny" type="button" @click="patchEndpoint(ep, { device_ids: gpuChoice })">Guardar</button>
                  <button class="btn tiny" type="button" title="Volver a la detección automática" @click="patchEndpoint(ep, { device_ids: null })">
                    Automático
                  </button>
                  <button class="btn tiny" type="button" @click="editingGpus = null">Cancelar</button>
                </template>
                <template v-else>
                  <span v-for="u in ep.snapshot?.devices ?? []" :key="u.device_id" class="gpu" :style="{ color: gpuOf(g.host.id, u.device_id).color }">
                    ■ {{ gpuOf(g.host.id, u.device_id).name }}
                  </span>
                  <span v-if="ep.snapshot?.gpu_link === 'manual'" class="dim">(a mano)</span>
                  <span v-if="!ep.snapshot?.devices?.length" class="dim">sin asociar{{ ep.manual ? "" : " (no se pudo leer qué GPU usa)" }}</span>
                  <button v-if="hostGpus(g.host.id).length" class="btn tiny" type="button" @click="startGpuEdit(ep)">
                    {{ ep.snapshot?.devices?.length ? "Cambiar" : "Asignar" }}
                  </button>
                </template>
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
            <p v-if="actionError[ep.id]" class="err" role="alert">✕ {{ actionError[ep.id] }}</p>
            <h4 class="label">Flags detectados</h4>
            <p v-if="!ep.snapshot || ep.snapshot.source === 'manual'" class="dim small">
              Alta manual: el agente no ve el proceso, así que no hay línea de comandos ni flags. Contexto, slots, modelo y build
              salen de <code>/props</code>.
            </p>
            <div class="flags mono">
              <span v-for="(v, k) in ep.snapshot?.flags ?? {}" :key="k" class="flag" v-show="k !== 'model'">{{ k }} <b>{{ val(v) }}</b></span>
              <span v-for="(v, k) in ep.snapshot?.unknown ?? {}" :key="'u' + k" class="flag flag--unknown" title="Flag no reconocido: se guarda tal cual">
                {{ k }} <b>{{ val(v) }}</b> ?
              </span>
            </div>
            <button v-if="ep.snapshot?.argv" class="btn tiny" type="button" :aria-expanded="!!showArgv[ep.id]" @click="showArgv[ep.id] = !showArgv[ep.id]">
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
.head__actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}
.intro {
  margin: 0 0 12px;
  max-width: 80ch;
}
.addform {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  align-items: flex-end;
}
.addform > label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.addform .grow {
  flex: 1 1 260px;
}
.addform input[type="text"],
.addform select {
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 5px 8px;
}
.gpus {
  border: 1px solid var(--line);
  padding: 4px 10px 8px;
  margin: 0;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-right: 10px;
}
.formactions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-basis: 100%;
}
.err {
  color: var(--crit);
  font-size: 12px;
  margin: 0 0 8px;
}
.btn--danger {
  border-color: var(--crit);
  color: var(--crit);
}
.gpu {
  margin-right: 8px;
}
.title {
  font-size: 20px;
}
.host {
  margin: 18px 0 10px;
}
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--line);
}
.tab {
  background: none;
  border: 1px solid transparent;
  border-bottom: none;
  color: var(--ink-dim);
  padding: 6px 14px;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  gap: 8px;
  align-items: baseline;
}
.tab[aria-selected="true"] {
  color: var(--ink);
  border-color: var(--line);
  background: var(--panel);
  margin-bottom: -1px;
  font-weight: 600;
}
.tab:focus-visible {
  outline: 2px solid var(--accent);
}
.count {
  font-family: var(--font-mono);
  font-size: 11px;
  border: 1px solid var(--line);
  padding: 0 5px;
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
