<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api, hostList, live, runList } from "../api/live";
import type { Appearance, DeviceInfo, ThresholdOverrides } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import Stamp from "../components/Stamp.vue";
import StatusChip from "../components/StatusChip.vue";
import { ACCENTS, SCALES, normalize, readCached, save } from "../lib/appearance";
import { deviceColor, shortName } from "../lib/devices";
import { thresholdsFor } from "../lib/thresholds";

const route = useRoute();
const SECTIONS = [
  { id: "apariencia", label: "Apariencia" },
  { id: "equipos", label: "Equipos" },
  { id: "umbrales", label: "Umbrales" },
  { id: "datos", label: "Datos" },
];
const section = computed(() => (SECTIONS.some((s) => s.id === route.params.section) ? String(route.params.section) : "apariencia"));

// --- Apariencia ---------------------------------------------------------------
const look = reactive<Appearance>(normalize(live.appearance ?? readCached()));
watch(
  () => live.appearance,
  (a) => a && Object.assign(look, normalize(a)),
);
const syncState = ref<"ok" | "saving" | "error">("ok");
async function persist() {
  syncState.value = "saving";
  try {
    await save({ ...look });
    syncState.value = "ok";
  } catch {
    syncState.value = "error";
  }
}
const customAccent = computed(() => !ACCENTS.some((a) => a.value.toLowerCase() === look.accent.toLowerCase()));

// --- Equipos --------------------------------------------------------------------
const newHost = reactive({ agent_url: "http://127.0.0.1:9100", name: "", token: "" });
const hostError = ref<string | null>(null);
async function addHost() {
  hostError.value = null;
  try {
    await api("/api/hosts", {
      method: "POST",
      body: JSON.stringify({ agent_url: newHost.agent_url, name: newHost.name || null, token: newHost.token || null }),
    });
    newHost.name = "";
    newHost.token = "";
  } catch (e) {
    hostError.value = e instanceof Error ? e.message : String(e);
  }
}
async function removeHost(id: number) {
  hostError.value = null;
  try {
    await api(`/api/hosts/${id}`, { method: "DELETE" });
  } catch (e) {
    hostError.value = e instanceof Error ? e.message : String(e);
  }
}

// --- Umbrales -------------------------------------------------------------------
const gpus = computed<(DeviceInfo & { hostName: string })[]>(() =>
  hostList.value.flatMap((h) => h.devices.filter((d) => d.kind === "gpu").map((d) => ({ ...d, hostName: h.name }))),
);
const draft = reactive<Record<string, { warn: string; crit: string }>>({});
watch(
  [gpus, () => live.thresholds],
  () => {
    for (const d of gpus.value) {
      const o = live.thresholds[d.device_id] ?? {};
      draft[d.device_id] = { warn: o.warn?.toString() ?? "", crit: o.crit?.toString() ?? "" };
    }
  },
  { immediate: true, deep: true },
);
const thrState = ref<string | null>(null);
function derived(d: DeviceInfo) {
  return thresholdsFor(d); // sin ajustes: lo que sale del dispositivo o del fabricante
}
async function saveThresholds() {
  const out: ThresholdOverrides = {};
  for (const [id, v] of Object.entries(draft)) {
    const w = v.warn.trim() === "" ? undefined : Number(v.warn);
    const c = v.crit.trim() === "" ? undefined : Number(v.crit);
    if ((w !== undefined && !Number.isFinite(w)) || (c !== undefined && !Number.isFinite(c))) {
      thrState.value = "✕ Valores no numéricos";
      return;
    }
    if (w !== undefined && c !== undefined && w >= c) {
      thrState.value = "✕ El aviso debe ser menor que el aborto";
      return;
    }
    if (w !== undefined || c !== undefined) out[id] = { warn: w, crit: c };
  }
  try {
    await api("/api/settings/thresholds", { method: "PUT", body: JSON.stringify(out) });
    live.thresholds = out;
    thrState.value = "● Guardado";
  } catch (e) {
    thrState.value = "✕ " + (e instanceof Error ? e.message : String(e));
  }
}
function resetThreshold(id: string) {
  draft[id] = { warn: "", crit: "" };
}
</script>

<template>
  <div class="page settings">
    <h2 class="title">Ajustes</h2>
    <div class="layout">
      <nav class="subnav" aria-label="Secciones de ajustes">
        <RouterLink v-for="s in SECTIONS" :key="s.id" :to="`/ajustes/${s.id}`" class="subnav__link" :class="{ active: section === s.id }">
          {{ s.label }}
        </RouterLink>
      </nav>

      <div class="body">
        <!-- APARIENCIA -->
        <BlueprintCard v-if="section === 'apariencia'" title="APARIENCIA">
          <template #actions>
            <StatusChip
              label="estado"
              :state="syncState === 'ok' ? 'ok' : syncState === 'saving' ? 'pending' : 'crit'"
              :text="syncState === 'ok' ? 'sincronizado' : syncState === 'saving' ? 'guardando' : 'sin guardar'"
            />
          </template>

          <div class="row">
            <div class="row__text">
              <h3>Color de acento</h3>
              <p>Botones, enlaces, selección y la gráfica de velocidad. Los colores de las GPU no cambian: cada tarjeta conserva el suyo.</p>
            </div>
            <div class="row__control">
              <div class="swatches" role="radiogroup" aria-label="Color de acento">
                <label v-for="a in ACCENTS" :key="a.id" class="swatch" :title="a.label">
                  <input v-model="look.accent" type="radio" name="accent" :value="a.value" class="sr-only" @change="persist" />
                  <span class="swatch__chip" :class="{ on: look.accent.toLowerCase() === a.value }" :style="{ background: a.value }" />
                  <span class="mono swatch__name">{{ a.label }}</span>
                </label>
                <label class="swatch" title="Personalizado">
                  <input v-model="look.accent" type="color" class="color" aria-label="Color personalizado" @change="persist" />
                  <span class="mono swatch__name">{{ customAccent ? look.accent : "Otro…" }}</span>
                </label>
              </div>
            </div>
          </div>

          <div class="row">
            <div class="row__text">
              <h3>Contraste</h3>
              <p>"Alto" aclara los textos secundarios y las líneas, y quita el efecto croquis. Más fácil de leer.</p>
            </div>
            <div class="row__control seg" role="radiogroup" aria-label="Contraste">
              <label><input v-model="look.contrast" type="radio" value="normal" @change="persist" /> Normal</label>
              <label><input v-model="look.contrast" type="radio" value="alto" @change="persist" /> Alto</label>
            </div>
          </div>

          <div class="row">
            <div class="row__text">
              <h3>Tamaño de la interfaz</h3>
              <p>Agranda todo (texto, cifras y gráficas). Útil en pantallas grandes o lejos del monitor.</p>
            </div>
            <div class="row__control seg" role="radiogroup" aria-label="Tamaño">
              <label v-for="s in SCALES" :key="s.value">
                <input v-model="look.scale" type="radio" :value="s.value" @change="persist" /> {{ s.label }} <span class="dim">{{ Math.round(s.value * 100) }} %</span>
              </label>
            </div>
          </div>

          <div class="row">
            <div class="row__text">
              <h3>Rejilla de fondo</h3>
              <p>La cuadrícula de plano. "Tenue" o "sin rejilla" reducen el ruido visual.</p>
            </div>
            <div class="row__control seg" role="radiogroup" aria-label="Rejilla">
              <label><input v-model="look.grid" type="radio" value="normal" @change="persist" /> Normal</label>
              <label><input v-model="look.grid" type="radio" value="tenue" @change="persist" /> Tenue</label>
              <label><input v-model="look.grid" type="radio" value="off" @change="persist" /> Sin rejilla</label>
            </div>
          </div>

          <div class="row">
            <div class="row__text">
              <h3>Efecto croquis</h3>
              <p>Trazo ligeramente irregular en ejes y medidores. Nunca afecta al texto ni a los datos. Se apaga solo con "reducir movimiento" del sistema.</p>
            </div>
            <div class="row__control">
              <label class="check"><input v-model="look.sketch" type="checkbox" @change="persist" /> Activado</label>
            </div>
          </div>
        </BlueprintCard>

        <!-- EQUIPOS -->
        <BlueprintCard v-if="section === 'equipos'" title="EQUIPOS (AGENTES)">
          <p class="hint">Cada equipo con GPUs ejecuta un agente. Fuera de localhost el agente exige token.</p>
          <p v-if="hostError" class="err mono">✕ {{ hostError }}</p>
          <table class="tbl mono">
            <thead><tr><th>equipo</th><th>agente</th><th>estado</th><th>token</th><th></th></tr></thead>
            <tbody>
              <tr v-for="h in hostList" :key="h.id">
                <td>{{ h.name }} <Stamp v-if="h.simulated" :text="`simulado · ${h.simulated}`" :tilt="0" /></td>
                <td>{{ h.agent_url }}</td>
                <td>{{ h.status }}<span v-if="h.error" class="dim"> — {{ h.error }}</span></td>
                <td>{{ h.has_token ? "sí" : "no" }}</td>
                <td><button class="btn tiny" type="button" @click="removeHost(h.id)">Quitar</button></td>
              </tr>
            </tbody>
          </table>
          <h3 class="sub">Añadir equipo</h3>
          <div class="form">
            <label><span class="label">URL del agente</span><input v-model="newHost.agent_url" type="url" /></label>
            <label><span class="label">nombre (opcional)</span><input v-model="newHost.name" type="text" /></label>
            <label><span class="label">token (si no es localhost)</span><input v-model="newHost.token" type="password" autocomplete="off" /></label>
            <button class="btn btn--primary" type="button" @click="addHost">Añadir</button>
          </div>
        </BlueprintCard>

        <!-- UMBRALES -->
        <BlueprintCard v-if="section === 'umbrales'" title="UMBRALES TÉRMICOS POR DISPOSITIVO">
          <p class="hint">
            Por defecto se calculan con la temperatura de <i>slowdown</i> que reporta cada GPU (aviso = slowdown − 10 °C, aborto = slowdown − 5 °C).
            Si la GPU no la reporta, se usan valores del fabricante. Aquí puedes fijarlos a mano; vacío = automático.
            Al llegar al <b>aborto</b> durante una prueba, la prueba se detiene sola.
          </p>
          <p v-if="!gpus.length" class="dim">No hay GPU detectadas.</p>
          <table v-else class="tbl mono">
            <thead><tr><th>dispositivo</th><th>equipo</th><th>slowdown</th><th>automático</th><th>aviso °C</th><th>aborto °C</th><th></th></tr></thead>
            <tbody>
              <tr v-for="d in gpus" :key="d.device_id">
                <td :style="{ color: deviceColor(d) }">■ {{ shortName(d.name) }}</td>
                <td>{{ d.hostName }}</td>
                <td>{{ d.temp_slowdown_c ?? "sin datos" }}</td>
                <td class="dim">{{ derived(d).warn }} / {{ derived(d).crit }} ({{ derived(d).source }})</td>
                <td><input v-model="draft[d.device_id].warn" class="num" type="number" :placeholder="String(derived(d).warn)" :aria-label="`Aviso ${d.name}`" /></td>
                <td><input v-model="draft[d.device_id].crit" class="num" type="number" :placeholder="String(derived(d).crit)" :aria-label="`Aborto ${d.name}`" /></td>
                <td><button class="btn tiny" type="button" @click="resetThreshold(d.device_id)">Automático</button></td>
              </tr>
            </tbody>
          </table>
          <div class="actions">
            <button class="btn btn--primary" type="button" @click="saveThresholds">Guardar umbrales</button>
            <span v-if="thrState" class="mono" :class="thrState.startsWith('✕') ? 'err' : 'ok'">{{ thrState }}</span>
          </div>
        </BlueprintCard>

        <!-- DATOS -->
        <BlueprintCard v-if="section === 'datos'" title="DATOS">
          <dl class="kv mono">
            <div><dt>runs guardados</dt><dd>{{ runList.length }}</dd></div>
            <div><dt>servidores conocidos</dt><dd>{{ Object.values(live.endpoints).flat().length }}</dd></div>
            <div><dt>base de datos</dt><dd>carpeta <code>data/</code> del proyecto, o la de <code>ARENA_DATA_DIR</code> (fuera de git y Syncthing)</dd></div>
          </dl>
          <div class="todo"><Stamp text="exportar / importar: F9" tone="dim" /></div>
        </BlueprintCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.title {
  font-size: 20px;
  margin-bottom: 14px;
}
.layout {
  display: grid;
  grid-template-columns: 170px 1fr;
  gap: 18px;
  align-items: start;
}
.subnav {
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--line);
}
.subnav__link {
  padding: 7px 12px;
  color: var(--ink-dim);
  text-decoration: none;
  border-left: 2px solid transparent;
  margin-left: -1px;
}
.subnav__link.active {
  color: var(--ink);
  border-left-color: var(--accent);
  background: rgba(108, 180, 255, 0.06);
}
.row {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(260px, 1.2fr);
  gap: 18px;
  padding: 14px 0;
  border-bottom: 1px dotted var(--line);
}
.row:last-child {
  border-bottom: 0;
}
.row__text h3 {
  font-size: 14px;
  margin-bottom: 4px;
}
.row__text p,
.hint {
  margin: 0;
  color: var(--ink-dim);
  font-size: 12px;
}
.hint {
  margin-bottom: 12px;
}
.row__control {
  display: flex;
  align-items: center;
}
.seg {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.seg label,
.check {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  cursor: pointer;
}
.swatches {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.swatch {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}
.swatch__chip {
  width: 28px;
  height: 28px;
  border: 2px solid transparent;
  outline: 1px solid var(--line);
}
.swatch__chip.on {
  border-color: var(--bg);
  outline: 2px solid var(--ink);
}
.swatch input:focus-visible + .swatch__chip {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.swatch__name {
  font-size: 10px;
  color: var(--ink-dim);
}
.color {
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--line);
  background: none;
}
.dim {
  color: var(--ink-faint);
}
.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.tbl th {
  text-align: left;
  font-weight: 400;
  color: var(--ink-faint);
  font-size: 10px;
  text-transform: uppercase;
  border-bottom: 1px solid var(--line);
  padding: 4px 6px;
}
.tbl td {
  padding: 5px 6px;
  border-bottom: 1px dotted var(--line);
}
.num {
  width: 80px;
}
input[type="number"],
input[type="text"],
input[type="url"],
input[type="password"] {
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 4px 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink);
}
.sub {
  font-size: 13px;
  margin: 18px 0 8px;
}
.form {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  flex-wrap: wrap;
}
.form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.actions {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-top: 14px;
}
.err {
  color: var(--crit);
}
.ok {
  color: var(--ok);
}
.btn.tiny {
  padding: 1px 8px;
  font-size: 11px;
}
.kv {
  margin: 0 0 12px;
  font-size: 12px;
}
.kv div {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 10px;
  padding: 4px 0;
  border-bottom: 1px dotted var(--line);
}
.kv dt {
  color: var(--ink-dim);
}
.kv dd {
  margin: 0;
}
code {
  font-family: var(--font-mono);
}
@media (max-width: 1100px) {
  .layout {
    grid-template-columns: 1fr;
  }
  .subnav {
    flex-direction: row;
    border-left: 0;
    border-bottom: 1px solid var(--line);
  }
  .row {
    grid-template-columns: 1fr;
  }
}
</style>
