<script setup lang="ts">
// Comparar runs: insignia de comparabilidad, veredictos, métricas, gráficas superpuestas,
// diff de configuración, respuestas por prompt y exportación (Markdown para el vault, CSV, JSON).
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, refreshRuns, runList } from "../api/live";
import type { CompareResponse } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import LineChart, { type ChartSeries } from "../components/LineChart.vue";
import ResponsesMatrix from "../components/ResponsesMatrix.vue";
import Stamp from "../components/Stamp.vue";
import { toCsv, toMarkdown, visibleMetrics } from "../lib/compare";
import { scoreboardPng } from "../lib/scoreboardImage";
import { NO_DATA, RUN_STATUS, fmt, fmtDate, suiteLabel } from "../lib/format";

const MAX = 12;
const route = useRoute();
const router = useRouter();
const data = ref<CompareResponse | null>(null);
const error = ref<string | null>(null);
const loading = ref(false);
const onlyDiff = ref(true);
const copied = ref(false);

const ids = computed<number[]>(() =>
  String(route.query.runs ?? "")
    .split(",")
    .map(Number)
    .filter((n) => Number.isInteger(n) && n > 0),
);

async function load() {
  error.value = null;
  if (!ids.value.length) {
    data.value = null;
    return;
  }
  loading.value = true;
  try {
    data.value = await api<CompareResponse>(`/api/compare?runs=${ids.value.join(",")}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
watch(ids, load);
onMounted(() => {
  load();
  refreshRuns().catch(() => {});
});

const setIds = (list: number[]) => router.replace({ query: list.length ? { runs: list.join(",") } : {} });
const removeRun = (id: number) => setIds(ids.value.filter((x) => x !== id));
const addId = ref<number | "">("");
function addRun() {
  if (addId.value !== "" && !ids.value.includes(addId.value)) setIds([...ids.value, addId.value]);
  addId.value = "";
}
const candidates = computed(() => runList.value.filter((r) => !ids.value.includes(r.id) && r.status !== "running"));

// Selección en la pantalla vacía
const picked = ref<number[]>([]);

const color = (i: number) => `var(--dev-${(i % 6) + 1})`;
const LEVEL_TONE: Record<string, "info" | "warn" | "crit"> = { si: "info", parcial: "warn", no: "crit" };
const LEVEL_ICON: Record<string, string> = { si: "✓", parcial: "◐", no: "✕" };

function val(v: unknown, digits = 1, unit = ""): string {
  if (typeof v === "number") return fmt(v, Number.isInteger(v) ? 0 : digits, unit);
  if (v === null || v === undefined || v === "") return NO_DATA;
  if (Array.isArray(v)) return v.length ? v.join(", ") : NO_DATA;
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

const KEY_LABEL: Record<string, string> = {
  equipo: "equipo",
  gpus: "GPU",
  modelo: "modelo",
  cuantizacion: "cuantización",
  build: "build",
  ctx_por_slot: "contexto por slot",
  slots: "slots",
};
const keyLabel = (k: string) => KEY_LABEL[k] ?? k.replace(/^param:/, "").replace(/^flag:/, "-");
const diffRows = computed(() => (data.value?.config_diff ?? []).filter((r) => !onlyDiff.value || !r.same));

function chart(key: "tps" | "temp" | "power"): ChartSeries[] {
  return (data.value?.series ?? []).map((s, i) => ({
    id: String(data.value!.runs[i].id),
    label: `#${data.value!.runs[i].id}${key !== "tps" && s.device ? ` · ${s.device}` : ""}`,
    color: color(i),
    points: s[key].map((p) => ({ x: p.t, y: p.v })),
  }));
}
const hasSeries = (key: "tps" | "temp" | "power") => (data.value?.series ?? []).some((s) => s[key].length > 1);

// --- pestañas ---------------------------------------------------------------
type Tab = "resumen" | "prompts" | "metricas" | "graficas";
const TABS: { id: Tab; label: string }[] = [
  { id: "resumen", label: "Resumen" },
  { id: "prompts", label: "Prompts" },
  { id: "metricas", label: "Métricas" },
  { id: "graficas", label: "Gráficas" },
];
const tab = ref<Tab>("resumen");
function onTabKey(e: KeyboardEvent) {
  const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
  if (!d) return;
  const i = TABS.findIndex((t) => t.id === tab.value);
  tab.value = TABS[(i + d + TABS.length) % TABS.length].id;
  (e.currentTarget as HTMLElement).querySelector<HTMLElement>('[aria-selected="true"]')?.focus();
  e.preventDefault();
}

// Resumen: solo lo crítico (velocidad, latencia, temperatura, potencia, energía)
const SUMMARY_KEYS = ["tps", "ttft", "pp", "degradation", "temp_max", "throttling", "power_mean", "vram_peak", "tokens_per_wh"];
// Métricas normalizadas (por GiB de VRAM, por W, por ktok): opcionales, se recuerda la elección
const NORM_KEY = "arena.compareNormalized";
const normalized = ref(false);
try {
  normalized.value = localStorage.getItem(NORM_KEY) === "1";
} catch {
  /* sin almacenamiento: se queda apagado */
}
watch(normalized, (v) => {
  try {
    localStorage.setItem(NORM_KEY, v ? "1" : "0");
  } catch {
    /* solo se pierde la preferencia */
  }
});
const shownMetrics = computed(() => (data.value ? visibleMetrics(data.value, normalized.value) : []));
const summaryMetrics = computed(() => (data.value?.metrics ?? []).filter((m) => SUMMARY_KEYS.includes(m.key)));

// --- visor de gráficas --------------------------------------------------------
type SeriesKey = "tps" | "temp" | "power";
const CHARTS: { key: SeriesKey; title: string; unit: string; digits: number }[] = [
  { key: "tps", title: "Velocidad", unit: "t/s", digits: 1 },
  { key: "temp", title: "Temperatura (GPU del run)", unit: "°C", digits: 0 },
  { key: "power", title: "Potencia de placa (GPU del run)", unit: "W", digits: 0 },
];
const viz = ref({
  shown: { tps: true, temp: true, power: true } as Record<SeriesKey, boolean>,
  layout: "superpuestas" as "superpuestas" | "separadas",
  height: 260,
  fromZero: false,
  area: false,
  dots: false,
});
const hiddenRuns = ref<number[]>([]);
const toggleRun = (id: number) =>
  (hiddenRuns.value = hiddenRuns.value.includes(id) ? hiddenRuns.value.filter((x) => x !== id) : [...hiddenRuns.value, id]);
const visibleCharts = computed(() => CHARTS.filter((c) => viz.value.shown[c.key] && hasSeries(c.key)));
const visibleSeries = (key: SeriesKey) => chart(key).filter((s) => !hiddenRuns.value.includes(Number(s.id)));
const columns = computed(() =>
  (data.value?.runs ?? []).map((r, i) => ({ title: r.title, sub: r.label, color: color(i) })),
);

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
const imageNote = ref<string | null>(null);
async function scoreboardImage(action: "download" | "copy", hd = false) {
  if (!data.value) return;
  imageNote.value = null;
  try {
    const blob = await scoreboardPng(data.value, { normalized: normalized.value, ...(hd ? { width: 1920, height: 1080 } : {}) });
    if (action === "copy") {
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      imageNote.value = "✓ Imagen copiada";
    } else {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `marcador-${stamp()}.png`;
      a.click();
      URL.revokeObjectURL(url);
    }
  } catch (e) {
    imageNote.value = e instanceof Error ? e.message : String(e);
  }
}
const stamp = () => new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
async function copyMarkdown() {
  if (!data.value) return;
  try {
    await navigator.clipboard.writeText(toMarkdown(data.value, new Date(), normalized.value));
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 2000);
  } catch {
    download(`comparacion-${stamp()}.md`, toMarkdown(data.value, new Date(), normalized.value), "text/markdown");
  }
}
</script>

<template>
  <div class="page">
    <div class="head">
      <h2 class="title">Comparar</h2>
      <span class="dim small">Hasta {{ MAX }} runs. Se eligen en el Historial, en una batalla o aquí.</span>
    </div>

    <!-- Vacío: elegir runs -->
    <BlueprintCard v-if="!ids.length" title="Elige qué comparar">
      <p class="dim small">
        Marca dos o más runs (o uno solo, para leer sus respuestas). También puedes marcarlos en el
        <RouterLink to="/historial">Historial</RouterLink> o abrir una <RouterLink to="/batalla">batalla</RouterLink> y pulsar «Ver en Comparar».
      </p>
      <div class="pick">
        <label v-for="r in candidates.slice(0, 40)" :key="r.id" class="pick__row">
          <input v-model="picked" type="checkbox" :value="r.id" :disabled="!picked.includes(r.id) && picked.length >= MAX" />
          <span class="mono">#{{ r.id }}</span>
          <span>{{ suiteLabel(r.suite) }}</span>
          <span class="dim">{{ r.label ?? "" }}</span>
          <span class="dim mono">{{ fmtDate(r.started_at ?? r.created_at) }}</span>
        </label>
        <p v-if="!candidates.length" class="dim">Todavía no hay runs terminados.</p>
      </div>
      <button class="btn btn--primary" type="button" :disabled="!picked.length" @click="setIds(picked)">Comparar ({{ picked.length }})</button>
    </BlueprintCard>

    <p v-if="error" class="error mono" role="alert">✕ {{ error }}</p>
    <p v-if="loading && !data" class="dim">Cargando…</p>

    <template v-if="data && ids.length">
      <!-- Runs elegidos -->
      <div class="chips">
        <span v-for="(r, i) in data.runs" :key="r.id" class="chip" :style="{ borderColor: color(i) }">
          <span class="swatch" :style="{ background: color(i) }" aria-hidden="true" />
          <RouterLink :to="`/pruebas/${r.id}`" class="mono">{{ r.title }}</RouterLink>
          <span v-if="r.label" class="dim small">{{ r.label }}</span>
          <span v-if="r.status !== 'done'" class="warn small">{{ RUN_STATUS[r.status]?.text ?? r.status }}</span>
          <button type="button" class="x" :aria-label="`Quitar el run #${r.id}`" @click="removeRun(r.id)">×</button>
        </span>
        <span v-if="ids.length < MAX" class="add">
          <select v-model="addId" aria-label="Añadir un run">
            <option value="">＋ añadir run…</option>
            <option v-for="r in candidates" :key="r.id" :value="r.id">#{{ r.id }} · {{ suiteLabel(r.suite) }}{{ r.label ? ` · ${r.label}` : "" }}</option>
          </select>
          <button class="btn tiny" type="button" :disabled="addId === ''" @click="addRun">Añadir</button>
        </span>
      </div>

      <!-- Insignia de comparabilidad -->
      <div v-if="data.comparability.level" class="badge" :class="`badge--${data.comparability.level}`">
        <Stamp
          :text="`${LEVEL_ICON[data.comparability.level]} ${data.comparability.label}`"
          :tone="LEVEL_TONE[data.comparability.level]"
          :tilt="0"
        />
        <span class="small">
          {{ data.comparability.changes.length ? `Cambia: ${data.comparability.changes.join(", ")}` : "Misma configuración y misma prueba" }}
        </span>
        <ul v-if="data.comparability.reasons.length" class="reasons small">
          <li v-for="r in data.comparability.reasons" :key="r">{{ r }}</li>
        </ul>
      </div>

      <!-- Pestañas -->
      <div class="tabs" role="tablist" aria-label="Apartados de la comparación" @keydown="onTabKey">
        <button
          v-for="t in TABS"
          :id="`tab-${t.id}`"
          :key="t.id"
          role="tab"
          type="button"
          class="tab"
          :aria-selected="tab === t.id"
          :aria-controls="`panel-${t.id}`"
          :tabindex="tab === t.id ? 0 : -1"
          @click="tab = t.id"
        >
          {{ t.label }}
          <span v-if="t.id === 'prompts'" class="count">{{ data.items.length }}</span>
        </button>
      </div>

      <!-- RESUMEN -->
      <section v-show="tab === 'resumen'" id="panel-resumen" role="tabpanel" aria-labelledby="tab-resumen">
        <div v-if="data.verdicts.length" class="verdicts">
          <BlueprintCard v-for="v in data.verdicts" :key="v.key" dense :title="v.title">
            <div class="verdict__run" :style="{ color: color(v.run_index) }">■ {{ data.runs[v.run_index].title }}</div>
            <div class="big mono">
              {{ fmt(v.value, v.key === "ttft" ? 2 : v.key === "tps" ? 1 : 0, data.metrics.find((m) => m.key === v.key)?.unit ?? "") }}
            </div>
            <div class="dim small">
              {{ v.margin_pct !== null ? `${fmt(v.margin_pct, 0, "%")} mejor que el segundo` : "" }}
            </div>
          </BlueprintCard>
        </div>

        <BlueprintCard title="Datos principales" class="gap">
          <div class="scroll">
            <table class="tbl mono">
              <thead>
                <tr>
                  <th>métrica</th>
                  <th v-for="(r, i) in data.runs" :key="r.id"><span class="swatch" :style="{ background: color(i) }" aria-hidden="true" /> #{{ r.id }}{{ r.side ? ` · ${r.side}` : "" }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in summaryMetrics" :key="m.key">
                  <td class="sans">{{ m.label }}</td>
                  <td v-for="(v, i) in m.values" :key="i" :class="{ best: m.best.includes(i) }">
                    {{ fmt(v, m.digits, m.unit) }}<span v-if="m.best.includes(i)" class="best__mark" title="Mejor valor"> ▲</span>
                  </td>
                </tr>
                <tr v-if="!summaryMetrics.length">
                  <td :colspan="data.runs.length + 1" class="dim sans">Estos runs no tienen métricas comparables.</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="dim small">▲ = mejor valor. Todas las métricas están en la pestaña «Métricas».</p>
        </BlueprintCard>
      </section>

      <!-- PROMPTS -->
      <section v-show="tab === 'prompts'" id="panel-prompts" role="tabpanel" aria-labelledby="tab-prompts">
        <BlueprintCard v-if="data.items.length" :title="`Respuestas por prompt (${data.items.length})`">
          <ResponsesMatrix :rows="data.items" :columns="columns" />
        </BlueprintCard>
        <p v-else class="dim">Estos runs no tienen prompts que comparar.</p>
      </section>

      <!-- MÉTRICAS -->
      <section v-show="tab === 'metricas'" id="panel-metricas" role="tabpanel" aria-labelledby="tab-metricas">
        <BlueprintCard title="Todas las métricas">
          <template #actions>
            <label class="check small"><input v-model="normalized" type="checkbox" /> normalizar (por GiB, por W, por ktok)</label>
          </template>
          <div class="scroll">
            <table class="tbl mono">
              <thead>
                <tr>
                  <th>métrica</th>
                  <th v-for="(r, i) in data.runs" :key="r.id"><span class="swatch" :style="{ background: color(i) }" aria-hidden="true" /> #{{ r.id }}{{ r.side ? ` · ${r.side}` : "" }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in shownMetrics" :key="m.key">
                  <td class="sans">{{ m.label }}<Stamp v-if="m.estimated" text="ESTIMADO" tone="dim" :tilt="0" class="est" /><span v-if="m.better" class="dim"> ({{ m.better === "high" ? "más es mejor" : "menos es mejor" }})</span></td>
                  <td v-for="(v, i) in m.values" :key="i" :class="{ best: m.best.includes(i) }">
                    {{ fmt(v, m.digits, m.unit) }}<span v-if="m.best.includes(i)" class="best__mark" title="Mejor valor"> ▲</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="dim small">▲ = mejor valor. Temperatura, potencia y energía solo de las GPU de cada run (ESTIMADO en la potencia: es la de placa).</p>
        </BlueprintCard>

        <BlueprintCard title="Configuración" class="gap">
          <template #actions>
            <label class="check small"><input v-model="onlyDiff" type="checkbox" /> solo lo que cambia</label>
          </template>
          <div class="scroll">
            <table class="tbl mono">
              <thead>
                <tr>
                  <th>clave</th>
                  <th v-for="(r, i) in data.runs" :key="r.id"><span class="swatch" :style="{ background: color(i) }" aria-hidden="true" /> #{{ r.id }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in diffRows" :key="row.key" :class="{ changed: !row.same }">
                  <td class="sans">{{ keyLabel(row.key) }}<span v-if="!row.same" class="warn" title="Cambia entre runs"> ≠</span></td>
                  <td v-for="(v, i) in row.values" :key="i">{{ val(v) }}</td>
                </tr>
                <tr v-if="!diffRows.length">
                  <td :colspan="data.runs.length + 1" class="dim sans">Ninguna diferencia de configuración.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </BlueprintCard>
      </section>

      <!-- GRÁFICAS: visor con opciones -->
      <section v-show="tab === 'graficas'" id="panel-graficas" role="tabpanel" aria-labelledby="tab-graficas">
        <BlueprintCard title="Visor de gráficas (desde el inicio de la carga)">
          <div class="viz">
            <fieldset class="viz__group">
              <legend>Magnitud</legend>
              <label v-for="c in CHARTS" :key="c.key" class="check small" :class="{ dim: !hasSeries(c.key) }">
                <input v-model="viz.shown[c.key]" type="checkbox" :disabled="!hasSeries(c.key)" /> {{ c.title.split(" (")[0] }}
              </label>
            </fieldset>
            <fieldset class="viz__group">
              <legend>Disposición</legend>
              <label class="check small"><input v-model="viz.layout" type="radio" value="superpuestas" /> Runs superpuestos</label>
              <label class="check small"><input v-model="viz.layout" type="radio" value="separadas" /> Una gráfica por run</label>
            </fieldset>
            <fieldset class="viz__group">
              <legend>Runs</legend>
              <label v-for="(r, i) in data.runs" :key="r.id" class="check small">
                <input type="checkbox" :checked="!hiddenRuns.includes(r.id)" @change="toggleRun(r.id)" />
                <span class="swatch" :style="{ background: color(i) }" aria-hidden="true" /> #{{ r.id }}
              </label>
            </fieldset>
            <fieldset class="viz__group">
              <legend>Aspecto</legend>
              <label class="check small"><input v-model="viz.fromZero" type="checkbox" /> Eje Y desde 0</label>
              <label class="check small"><input v-model="viz.area" type="checkbox" /> Relleno bajo la línea</label>
              <label class="check small"><input v-model="viz.dots" type="checkbox" /> Marcar puntos</label>
              <label class="check small">
                Alto
                <input v-model.number="viz.height" type="range" min="160" max="560" step="20" aria-label="Alto de las gráficas" />
                <span class="mono">{{ viz.height }}px</span>
              </label>
            </fieldset>
          </div>
        </BlueprintCard>

        <p v-if="!visibleCharts.length" class="dim gap">No hay series que mostrar con esta selección.</p>
        <template v-for="c in visibleCharts" :key="c.key">
          <BlueprintCard v-if="viz.layout === 'superpuestas'" :title="c.title" class="gap">
            <LineChart
              :title="c.title"
              :unit="c.unit"
              :series="visibleSeries(c.key)"
              :digits="c.digits"
              :height="viz.height"
              :y-min="viz.fromZero ? 0 : undefined"
              :area="viz.area"
              :dots="viz.dots"
            />
          </BlueprintCard>
          <BlueprintCard v-else :title="c.title" class="gap">
            <div class="charts">
              <LineChart
                v-for="s in visibleSeries(c.key)"
                :key="s.id"
                :title="s.label"
                :unit="c.unit"
                :series="[s]"
                :digits="c.digits"
                :height="viz.height"
                :y-min="viz.fromZero ? 0 : undefined"
                :area="viz.area"
                :dots="viz.dots"
              />
            </div>
          </BlueprintCard>
        </template>
      </section>

      <!-- Exportar -->
      <BlueprintCard title="Exportar" class="gap">
        <div class="exports">
          <button class="btn" type="button" @click="copyMarkdown">{{ copied ? "✓ Copiado" : "Copiar Markdown para el vault" }}</button>
          <button class="btn" type="button" @click="download(`comparacion-${stamp()}.md`, toMarkdown(data!, new Date(), normalized), 'text/markdown')">Descargar .md</button>
          <button class="btn" type="button" @click="download(`comparacion-${stamp()}.csv`, toCsv(data!, normalized), 'text/csv')">Descargar CSV</button>
          <button class="btn" type="button" @click="scoreboardImage('download')">Imagen del marcador (PNG)</button>
          <button class="btn" type="button" @click="scoreboardImage('download', true)">PNG 1920×1080</button>
          <button class="btn" type="button" @click="scoreboardImage('copy')">Copiar imagen</button>
          <button class="btn" type="button" @click="download(`comparacion-${stamp()}.json`, JSON.stringify(data, null, 2), 'application/json')">
            Descargar JSON
          </button>
        </div>
        <p v-if="imageNote" class="small mono" role="status">{{ imageNote }}</p>
        <p class="dim small">El Markdown lleva frontmatter YAML (tipo proyecto) y las respuestas completas: se pega tal cual en el vault.</p>
      </BlueprintCard>
    </template>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: baseline;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.title {
  font-size: 20px;
  margin: 0;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 11px;
}
.warn {
  color: var(--warn);
}
.error {
  color: var(--crit);
  border: 1px dashed var(--crit);
  padding: 8px 10px;
}
.gap {
  margin-top: 18px;
}
.pick {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 420px;
  overflow-y: auto;
  margin: 10px 0 12px;
}
.pick__row {
  display: grid;
  grid-template-columns: 20px 50px 170px 1fr 120px;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  padding: 3px 4px;
  border-bottom: 1px dotted var(--line);
  cursor: pointer;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 14px;
}
.chip {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  border: 1px solid var(--line);
  border-left-width: 3px;
  padding: 3px 4px 3px 8px;
  font-size: 12px;
  background: var(--panel);
}
.swatch {
  display: inline-block;
  width: 9px;
  height: 9px;
}
.x {
  background: none;
  border: none;
  color: var(--ink-dim);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}
.x:focus-visible {
  outline: 2px solid var(--accent);
}
.add {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}
select {
  background: var(--bg);
  border: 1px solid var(--line);
  color: var(--ink);
  font-size: 12px;
  padding: 3px 6px;
  max-width: 320px;
}
.badge {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  align-items: center;
  border: 1px dashed var(--line-strong);
  padding: 10px 12px;
}
.badge--parcial {
  border-color: var(--warn);
}
.badge--no {
  border-color: var(--crit);
}
.reasons {
  flex-basis: 100%;
  margin: 2px 0 0;
  padding-left: 18px;
  color: var(--ink-dim);
}
.verdicts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
  margin-top: 18px;
}
.verdict__run {
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.big {
  font-size: 26px;
  margin: 4px 0;
}
.scroll {
  overflow-x: auto;
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
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--line);
  padding: 4px 8px;
  white-space: nowrap;
}
.tbl td {
  padding: 4px 8px;
  border-bottom: 1px dotted var(--line);
  overflow-wrap: anywhere;
}
.tbl .sans {
  font-family: var(--font-sans);
  color: var(--ink-dim);
}
.best {
  color: var(--ok);
  font-weight: 600;
}
.best__mark {
  font-size: 10px;
}
.changed td:not(:first-child) {
  color: var(--ink);
}
.charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 18px;
}
.check {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}
.exports {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.btn.tiny {
  padding: 1px 8px;
  font-size: 11px;
}
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--line);
  margin-top: 18px;
  overflow-x: auto;
}
.tab {
  background: none;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  color: var(--ink-dim);
  padding: 8px 16px;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  gap: 8px;
  align-items: baseline;
  white-space: nowrap;
  transition: color 0.15s, background 0.15s;
}
.tab:hover {
  color: var(--ink);
  background: rgba(255, 255, 255, 0.05);
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
  border-radius: 999px;
  padding: 0 6px;
}
[role="tabpanel"] {
  margin-top: 18px;
}
.viz {
  display: flex;
  flex-wrap: wrap;
  gap: 14px 28px;
}
.viz__group {
  border: 0;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.viz__group legend {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
  padding: 0 0 4px;
}
</style>
