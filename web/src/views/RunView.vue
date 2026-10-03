<script setup lang="ts">
// Un run: vista en vivo mientras corre y resultado completo al terminar.
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api, live, onEvent, serverNow } from "../api/live";
import type { DeviceInfo, RunDetail, Sample, Snapshot, TpsPoint } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import LineChart, { type ChartBand, type ChartLine, type ChartMarker, type ChartSeries } from "../components/LineChart.vue";
import Stamp from "../components/Stamp.vue";
import { deviceColor, shortName } from "../lib/devices";
import { NO_DATA, RUN_STATUS, fmt, fmtDate, fmtDuration, gib, isNum } from "../lib/format";

const props = defineProps<{ id: string }>();
const router = useRouter();
const runId = computed(() => Number(props.id));

const detail = ref<RunDetail | null>(null);
const loadError = ref<string | null>(null);
const liveTps = ref<TpsPoint[]>([]);
const liveSamples = ref<Sample[]>([]);
const busy = ref(false);
const expanded = ref<Record<number, boolean>>({});

async function load() {
  try {
    detail.value = await api<RunDetail>(`/api/runs/${runId.value}`);
    liveTps.value = [];
    liveSamples.value = [];
    loadError.value = null;
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  }
}

const run = computed(() => (detail.value ? { ...detail.value, ...(live.runs[runId.value] ?? {}) } : null));
const running = computed(() => run.value?.status === "running" || run.value?.status === "pending");
const lv = computed(() => live.runLive[runId.value]);

const offs: (() => void)[] = [];
onMounted(() => {
  load();
  offs.push(
    onEvent("run_live", (d: { run: number; t: number; tps?: number; tokens: number }) => {
      if (d.run === runId.value && isNum(d.tps) && running.value && lv.value?.phase === "carga") {
        liveTps.value.push({ t: d.t, tokens: 0, tps: d.tps });
      }
    }),
    onEvent("metrics", (d: { host: number; snapshot: Snapshot }) => {
      const r = run.value;
      if (!r || !running.value || d.host !== r.host_pk) return;
      const t = serverNow();
      const phase = lv.value?.phase ?? "reposo";
      for (const [device_id, data] of Object.entries(d.snapshot.devices)) {
        liveSamples.value.push({ t, phase, device_id, data: data as unknown as Record<string, unknown> });
      }
    }),
    onEvent("run", (r: { id: number; status: string }) => {
      if (r.id === runId.value && r.status !== "running" && r.status !== "pending") load();
    }),
  );
});
onBeforeUnmount(() => offs.forEach((f) => f()));
watch(runId, load);

// --- series de las gráficas ------------------------------------------------
const t0 = computed(() => run.value?.started_at ?? 0);
const allTps = computed(() => [...(detail.value?.tps ?? []), ...liveTps.value]);
const allSamples = computed(() => [...(detail.value?.samples ?? []), ...liveSamples.value]);

const devices = computed<DeviceInfo[]>(() => {
  const host = (run.value?.host_pk ? live.hosts[run.value.host_pk] : null) ?? detail.value?.host_snapshot;
  return (host?.devices ?? []) as DeviceInfo[];
});
const watched = computed(() => detail.value?.host_snapshot?.thresholds ?? {});
const gpuIds = computed(() => Object.keys(watched.value));
function dev(id: string): DeviceInfo | undefined {
  return devices.value.find((d) => d.device_id === id);
}
function devLabel(id: string): string {
  return shortName(dev(id)?.name ?? watched.value[id]?.name ?? id);
}
function devColor(id: string): string {
  const d = dev(id);
  return d ? deviceColor(d) : "var(--accent)";
}

function seriesFor(key: string, scale = 1): ChartSeries[] {
  return gpuIds.value.map((id) => ({
    id,
    label: devLabel(id),
    color: devColor(id),
    points: allSamples.value
      .filter((s) => s.device_id === id)
      .map((s) => {
        const v = s.data[key];
        return { x: s.t - t0.value, y: isNum(v) ? v / scale : null };
      }),
  }));
}

const tpsSeries = computed<ChartSeries[]>(() => [
  {
    id: "tps",
    label: "t/s agregado",
    color: "var(--accent)",
    points: allTps.value.map((p) => ({ x: p.t - t0.value, y: p.tps })),
  },
]);
const tempSeries = computed(() => seriesFor("temp_c"));
const powerSeries = computed(() => seriesFor("power_w"));
const clockSeries = computed(() => seriesFor("clock_sm_mhz"));

const tempLines = computed<ChartLine[]>(() =>
  gpuIds.value.map((id) => ({
    y: watched.value[id].crit,
    label: `aborto ${watched.value[id].crit} °C${gpuIds.value.length > 1 ? " · " + devLabel(id) : ""}`,
    color: "var(--crit)",
  })),
);

const bands = computed<ChartBand[]>(() => {
  const r = run.value;
  if (!r?.started_at) return [];
  const now = running.value ? serverNow() : (r.finished_at ?? serverNow());
  const ls = r.summary?.phases.load_start ?? (lv.value?.load_elapsed_s != null ? lv.value.t - lv.value.load_elapsed_s : null);
  const le = r.summary?.phases.load_end ?? null;
  const out: ChartBand[] = [];
  const s = r.started_at;
  out.push({ from: 0, to: (ls ?? now) - s, label: "reposo" });
  if (ls) out.push({ from: ls - s, to: (le ?? now) - s, label: "carga" });
  if (le && (r.finished_at ?? now) > le + 0.5) out.push({ from: le - s, to: (r.finished_at ?? now) - s, label: "enfriamiento" });
  return out;
});

const markers = computed<ChartMarker[]>(() => {
  const r = run.value;
  if (!r?.abort_reason || !r.summary?.phases.load_end || !r.started_at) return [];
  return [{ x: r.summary.phases.load_end - r.started_at, label: "aborto" }];
});

const xMax = computed(() => {
  const r = run.value;
  if (!r?.started_at) return undefined;
  const p = r.params ?? {};
  if (running.value && r.suite === "estres") {
    return Number(p.baseline_s ?? 0) + Number(p.duration_s ?? 0) + Number(p.cooldown_s ?? 0);
  }
  return undefined;
});

// --- cifras ---------------------------------------------------------------
const elapsed = computed(() => {
  const r = run.value;
  if (!r?.started_at) return null;
  return (running.value ? serverNow() : (r.finished_at ?? r.started_at)) - r.started_at;
});
const progress = computed(() => (xMax.value && elapsed.value ? Math.min(1, elapsed.value / xMax.value) : null));
const status = computed(() => RUN_STATUS[run.value?.status ?? "pending"]);
const lastTps = computed(() => (liveTps.value.length ? liveTps.value[liveTps.value.length - 1].tps : null));
const snap = computed(() => detail.value?.servers_snapshot);
const sum = computed(() => run.value?.summary ?? null);

// --- acciones -------------------------------------------------------------
async function stop() {
  busy.value = true;
  try {
    await api(`/api/runs/${runId.value}/cancel`, { method: "POST" });
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

async function repeat() {
  const r = detail.value;
  if (!r || r.endpoint_id === null) return;
  busy.value = true;
  try {
    const created = await api<{ id: number }>("/api/runs", {
      method: "POST",
      body: JSON.stringify({ suite: r.suite, endpoint_id: r.endpoint_id, label: r.label, params: r.params }),
    });
    router.push(`/pruebas/${created.id}`);
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

async function remove() {
  busy.value = true;
  try {
    await api(`/api/runs/${runId.value}`, { method: "DELETE" });
    delete live.runs[runId.value];
    router.push("/historial");
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

/** Petición cortada al acabar el tiempo o al abortar: no es un error. */
function isCut(err: string | null): boolean {
  return !!err && err.startsWith("Cortada");
}

function m(item: { metrics: Record<string, unknown> | null }, key: string): number | null {
  const v = item.metrics?.[key];
  return isNum(v) ? v : null;
}

const flagList = computed(() => Object.entries(snap.value?.flags ?? {}).filter(([k]) => k !== "model"));
</script>

<template>
  <div class="page">
    <p v-if="loadError" class="error mono" role="alert">▲ {{ loadError }}</p>
    <p v-if="!run && !loadError" class="mono dim">Cargando…</p>

    <template v-if="run">
      <!-- Cabecera -->
      <div class="head">
        <div>
          <h2 class="title">
            Run #{{ run.id }} · {{ run.suite === "estres" ? "Estrés" : "Prompt libre" }}
            <span v-if="run.label" class="dim">— {{ run.label }}</span>
          </h2>
          <p class="mono dim small">
            {{ fmtDate(run.started_at, true) }} · {{ snap?.model_file ?? "modelo sin identificar" }} ·
            {{ snap?.base_url }} · suite v{{ run.suite_version }} ({{ run.suite_hash }})
          </p>
        </div>
        <div class="actions">
          <Stamp :text="`${status.icon} ${status.text}`" :tone="status.tone" />
          <button v-if="running" class="btn" type="button" :disabled="busy" @click="stop">■ Detener</button>
          <template v-else>
            <button class="btn btn--primary" type="button" :disabled="busy" @click="repeat">↻ Repetir</button>
            <button class="btn" type="button" :disabled="busy" @click="remove">Borrar</button>
          </template>
        </div>
      </div>

      <p v-if="run.abort_reason" class="abort mono" role="alert">✕ Abortado por temperatura: {{ run.abort_reason }}</p>
      <p v-if="run.error" class="error mono" role="alert">✕ {{ run.error }}</p>

      <!-- Cifras grandes -->
      <div class="stats">
        <BlueprintCard dense fig="FASE">
          <div class="big mono">{{ running ? (lv?.phase ?? "preparando") : status.text }}</div>
          <div class="mono dim small">{{ fmtDuration(elapsed) }}<span v-if="xMax"> de {{ fmtDuration(xMax) }}</span></div>
          <div v-if="progress !== null" class="progress" role="progressbar" :aria-valuenow="Math.round(progress * 100)" aria-valuemin="0" aria-valuemax="100">
            <div :style="{ width: progress * 100 + '%' }" />
          </div>
        </BlueprintCard>
        <BlueprintCard dense fig="T/S">
          <div class="big mono">{{ running ? fmt(lastTps, 1) : fmt(sum?.tps_aggregate.median ?? sum?.tps_client.median, 1) }}</div>
          <div class="mono dim small">{{ running ? "agregado, último segundo" : "mediana (agregado)" }}</div>
        </BlueprintCard>
        <BlueprintCard dense fig="TOKENS">
          <div class="big mono">{{ fmt(running ? lv?.tokens : sum?.completion_tokens, 0) }}</div>
          <div class="mono dim small">
            {{ fmt(running ? lv?.requests_done : sum?.requests, 0) }} peticiones
            <span v-if="(running ? lv?.requests_error : sum?.requests_error)" class="warn">
              · ▲ {{ running ? lv?.requests_error : sum?.requests_error }} con error
            </span>
            <span v-if="!running && sum?.requests_cut" class="dim"> · {{ sum.requests_cut }} cortada al terminar</span>
          </div>
        </BlueprintCard>
        <BlueprintCard v-for="id in gpuIds" :key="id" dense :fig="devLabel(id)" :color="devColor(id)">
          <div class="big mono">
            {{ fmt(running ? lv?.max_temp?.[id] : sum?.devices[id]?.temp_max_c, 0, "°C") }}
          </div>
          <div class="mono dim small">máx · aborto a {{ watched[id].crit }} °C ({{ watched[id].source }})</div>
        </BlueprintCard>
      </div>

      <!-- Gráficas -->
      <BlueprintCard fig="FIG.30" title="Telemetría del run" class="gap">
        <div class="charts">
          <LineChart title="Velocidad" unit="t/s" :digits="1" :series="tpsSeries" :bands="bands" :markers="markers" :x-max="xMax" :y-min="0" />
          <LineChart title="Temperatura" unit="°C" :series="tempSeries" :bands="bands" :lines="tempLines" :markers="markers" :x-max="xMax" />
          <LineChart title="Potencia de placa" unit="W" :series="powerSeries" :bands="bands" :markers="markers" :x-max="xMax" :y-min="0" />
          <LineChart title="Reloj SM" unit="MHz" :series="clockSeries" :bands="bands" :markers="markers" :x-max="xMax" :y-min="0" />
        </div>
        <p class="mono dim small note">La potencia es la de placa que reporta el driver, no la del enchufe.</p>
      </BlueprintCard>

      <!-- Respuesta en vivo -->
      <BlueprintCard v-if="running" fig="FIG.31" title="Respuesta en streaming" class="gap">
        <pre class="stream mono" aria-live="off">{{ lv?.text || "…" }}</pre>
      </BlueprintCard>

      <!-- Resumen -->
      <BlueprintCard v-if="sum && !running" fig="FIG.32" title="Resumen" class="gap">
        <div class="summary">
          <section>
            <h3 class="label">Velocidad</h3>
            <dl class="mono">
              <div><dt>t/s cliente (mediana)</dt><dd>{{ fmt(sum.tps_client.median, 1) }}</dd></div>
              <div><dt>t/s servidor (mediana)</dt><dd>{{ fmt(sum.tps_server.median, 1) }}</dd></div>
              <div><dt>t/s agregado (media)</dt><dd>{{ fmt(sum.tps_aggregate.mean, 1) }}</dd></div>
              <div><dt>prompt t/s (mediana)</dt><dd>{{ fmt(sum.pp_server.median, 0) }}</dd></div>
              <div><dt>TTFT (mediana)</dt><dd>{{ fmt(sum.ttft_s.median, 2, "s") }}</dd></div>
              <div><dt>t/s cliente p10 · máx</dt><dd>{{ fmt(sum.tps_client.p10, 1) }} · {{ fmt(sum.tps_client.max, 1) }}</dd></div>
              <div>
                <dt>degradación</dt>
                <dd>{{ sum.degradation_pct === null ? "sin datos (run < 30 s)" : fmt(sum.degradation_pct, 1, "%") }}</dd>
              </div>
            </dl>
          </section>
          <section>
            <h3 class="label">Energía <Stamp text="potencia de placa" tone="dim" :tilt="0" /></h3>
            <dl class="mono">
              <div><dt>energía (carga)</dt><dd>{{ fmt(sum.energy_wh, 2, "Wh") }}</dd></div>
              <div><dt>tokens / Wh</dt><dd>{{ fmt(sum.tokens_per_wh, 0) }}</dd></div>
              <div><dt>Wh / 1000 tokens</dt><dd>{{ fmt(sum.wh_per_1000_tokens, 2) }}</dd></div>
              <div><dt>duración de la carga</dt><dd>{{ fmtDuration(sum.duration_s) }}</dd></div>
            </dl>
          </section>
          <section v-for="id in gpuIds" :key="id">
            <h3 class="label" :style="{ color: devColor(id) }">{{ devLabel(id) }}</h3>
            <dl v-if="sum.devices[id]" class="mono">
              <div>
                <dt>temperatura reposo → máx</dt>
                <dd>{{ fmt(sum.devices[id].temp_idle_c, 0) }} → {{ fmt(sum.devices[id].temp_max_c, 0, "°C") }} (+{{ fmt(sum.devices[id].temp_rise_c, 0) }})</dd>
              </div>
              <div>
                <dt>potencia reposo · media · máx</dt>
                <dd>{{ fmt(sum.devices[id].power_idle_w, 0) }} · {{ fmt(sum.devices[id].power_mean_w, 0) }} · {{ fmt(sum.devices[id].power_max_w, 0, "W") }}</dd>
              </div>
              <div><dt>uso medio</dt><dd>{{ fmt(sum.devices[id].util_mean_pct, 0, "%") }}</dd></div>
              <div><dt>VRAM pico</dt><dd>{{ gib(sum.devices[id].vram_peak_mib) }}</dd></div>
              <div v-if="sum.devices.ram"><dt>RAM del equipo (pico)</dt><dd>{{ gib(sum.devices.ram.ram_used_peak_mib) }}</dd></div>
              <div>
                <dt>reloj medio · mínimo</dt>
                <dd>{{ fmt(sum.devices[id].clock_sm_mean_mhz, 0) }} · {{ fmt(sum.devices[id].clock_sm_min_mhz, 0, "MHz") }}</dd>
              </div>
              <div>
                <dt>tiempo con throttling</dt>
                <dd :class="{ warn: (sum.devices[id].throttle_pct ?? 0) > 0 }">{{ fmt(sum.devices[id].throttle_pct, 0, "%") }}</dd>
              </div>
            </dl>
            <p v-else class="mono dim">{{ NO_DATA }}</p>
          </section>
        </div>
      </BlueprintCard>

      <!-- Configuración guardada con el run -->
      <BlueprintCard fig="FIG.33" title="Configuración guardada con el run" class="gap">
        <div class="config mono">
          <div>
            <h3 class="label">Servidor</h3>
            <p>{{ snap?.derived?.model_path ?? snap?.model_path ?? NO_DATA }}</p>
            <p class="dim">
              {{ snap?.derived?.model_ftype ?? "?" }} · ctx {{ fmt(snap?.derived?.n_ctx_slot) }} × {{ fmt(snap?.derived?.total_slots) }} slots ·
              build {{ snap?.derived?.build_info ?? NO_DATA }}
            </p>
            <p class="flags">
              <span v-for="[k, v] in flagList" :key="k" class="flag">{{ k }}={{ Array.isArray(v) ? v.join(",") : v }}</span>
            </p>
          </div>
          <div>
            <h3 class="label">Parámetros</h3>
            <p class="flags">
              <span v-for="(v, k) in run.params ?? {}" :key="k" class="flag" v-show="k !== 'prompts'">
                {{ k }}={{ typeof v === "object" ? JSON.stringify(v) : v }}
              </span>
            </p>
          </div>
        </div>
      </BlueprintCard>

      <!-- Peticiones -->
      <BlueprintCard v-if="detail?.items.length" fig="FIG.34" :title="`Peticiones (${detail.items.length})`" class="gap">
        <table class="items mono">
          <thead>
            <tr>
              <th>#</th>
              <th>nombre</th>
              <th>tokens</th>
              <th>t/s cliente</th>
              <th>t/s servidor</th>
              <th>TTFT</th>
              <th>fin</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="it in detail.items" :key="it.id">
              <tr :class="{ 'row--error': it.error && !isCut(it.error) }">
                <td>{{ it.idx + 1 }}</td>
                <td>{{ it.name }}</td>
                <td>{{ fmt(m(it, "completion_tokens")) }}</td>
                <td>{{ fmt(m(it, "tps_client"), 1) }}</td>
                <td>{{ fmt(m(it, "tps_server"), 1) }}</td>
                <td>{{ fmt(m(it, "ttft_s"), 2, "s") }}</td>
                <td>{{ it.error ? (isCut(it.error) ? "■ cortada" : "✕ error") : (it.metrics?.finish_reason ?? "—") }}</td>
                <td>
                  <button class="btn tiny" type="button" :aria-expanded="!!expanded[it.id]" @click="expanded[it.id] = !expanded[it.id]">
                    {{ expanded[it.id] ? "Ocultar" : "Ver" }}
                  </button>
                </td>
              </tr>
              <tr v-if="expanded[it.id]" class="detail">
                <td colspan="8">
                  <p v-if="it.error" :class="isCut(it.error) ? 'dim' : 'error'">{{ isCut(it.error) ? "■" : "✕" }} {{ it.error }}</p>
                  <h4 class="label">Prompt</h4>
                  <pre>{{ it.prompt }}</pre>
                  <template v-if="it.reasoning">
                    <h4 class="label">Razonamiento</h4>
                    <pre class="dim">{{ it.reasoning }}</pre>
                  </template>
                  <h4 class="label">Respuesta</h4>
                  <pre>{{ it.response || NO_DATA }}</pre>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </BlueprintCard>
    </template>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.title {
  font-size: 18px;
}
.actions {
  display: flex;
  gap: 8px;
  align-items: center;
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
.error,
.abort {
  color: var(--crit);
  font-size: 13px;
  border: 1px dashed var(--crit);
  padding: 8px 10px;
  margin: 0 0 12px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 14px;
}
.big {
  font-size: 24px;
  font-weight: 600;
  margin-bottom: 2px;
}
.progress {
  height: 4px;
  background: var(--line);
  margin-top: 8px;
}
.progress div {
  height: 100%;
  background: var(--accent);
  transition: width 0.8s linear;
}
.gap {
  margin-top: 18px;
}
.charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 18px 22px;
}
.note {
  margin: 8px 0 0;
}
.stream {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: 12px;
  color: var(--ink-dim);
}
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 18px 28px;
}
.summary h3 {
  margin-bottom: 6px;
  display: flex;
  gap: 8px;
  align-items: center;
}
.summary dl {
  margin: 0;
  font-size: 12px;
}
.summary dl div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 3px 0;
  border-bottom: 1px dotted var(--line);
}
.summary dt {
  color: var(--ink-dim);
}
.summary dd {
  margin: 0;
  text-align: right;
}
.config {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
  font-size: 12px;
}
.config p {
  margin: 4px 0;
  overflow-wrap: anywhere;
}
.flags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.flag {
  border: 1px solid var(--line);
  padding: 1px 6px;
  font-size: 11px;
}
.items {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.items th {
  text-align: left;
  font-weight: 400;
  color: var(--ink-faint);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--line);
  padding: 4px 6px;
}
.items td {
  padding: 4px 6px;
  border-bottom: 1px dotted var(--line);
}
.row--error td {
  color: var(--crit);
}
.detail pre {
  white-space: pre-wrap;
  margin: 4px 0 10px;
  font-size: 12px;
  max-height: 300px;
  overflow: auto;
}
.btn.tiny {
  padding: 1px 8px;
  font-size: 11px;
}
</style>
