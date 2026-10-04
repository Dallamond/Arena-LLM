<script setup lang="ts">
// Un run: vista en vivo mientras corre y resultado completo al terminar.
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api, live, onEvent, serverNow } from "../api/live";
import type { BenchRow, DeviceInfo, LibraryPrompt, PromptLibrary, RunDetail, Sample, Snapshot, TpsPoint } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import LineChart, { type ChartBand, type ChartLine, type ChartMarker, type ChartSeries } from "../components/LineChart.vue";
import ResponsesMatrix from "../components/ResponsesMatrix.vue";
import Stamp from "../components/Stamp.vue";
import { deviceColor, shortName } from "../lib/devices";
import { NO_DATA, RUN_STATUS, fmt, fmtDate, fmtDuration, gib, isNum, suiteLabel } from "../lib/format";
import { itemsToRows } from "../lib/compare";
import { findByText } from "../lib/library";

const props = defineProps<{ id: string }>();
const router = useRouter();
const runId = computed(() => Number(props.id));

const detail = ref<RunDetail | null>(null);
const loadError = ref<string | null>(null);
const liveTps = ref<TpsPoint[]>([]);
const liveSamples = ref<Sample[]>([]);
const liveRows = ref<BenchRow[]>([]);
const busy = ref(false);
const expanded = ref<Record<number, boolean>>({});

// Respuestas de referencia de la biblioteca de prompts (se buscan por el texto del prompt)
const libraryPrompts = ref<LibraryPrompt[]>([]);
const libEntry = (prompt: string | null | undefined) => (prompt ? findByText(prompt, libraryPrompts.value) : undefined);

async function load() {
  try {
    detail.value = await api<RunDetail>(`/api/runs/${runId.value}`);
    liveTps.value = [];
    liveSamples.value = [];
    liveRows.value = [];
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
  api<PromptLibrary>("/api/prompts")
    .then((lib) => (libraryPrompts.value = lib.prompts))
    .catch(() => (libraryPrompts.value = []));
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
    onEvent("bench_row", (r: BenchRow & { run: number }) => {
      if (r.run === runId.value && !(detail.value?.bench_rows ?? []).some((x) => x.idx === r.idx)) liveRows.value.push(r);
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

// --- llama-bench -----------------------------------------------------------
interface BenchSnapshot {
  engine: string;
  exe: string | null;
  version: string | null;
  simulated: boolean | null;
  model: Record<string, unknown>;
  model_file: string;
  devices: { device_id: string; bench_name: string }[];
  cpu_only: boolean;
  spec: Record<string, unknown>;
}
const SWEEP_OF: Record<string, string> = { "bench-cpu": "threads", "bench-ngl": "n_gpu_layers", "bench-ts": "tensor_split" };
const SWEEP_UNIT: Record<string, { unit: string; name: string; label: string }> = {
  threads: { unit: "hilos", name: "hilos", label: "hilos" },
  n_gpu_layers: { unit: "capas", name: "-ngl", label: "capas en GPU" },
  tensor_split: { unit: "", name: "-ts", label: "reparto -ts" },
};
const isBench = computed(() => run.value?.kind === "bench");
const responseRows = computed(() => (detail.value?.items.length ? itemsToRows(detail.value.items) : []));
const benchRows = computed<BenchRow[]>(() => [...(detail.value?.bench_rows ?? []), ...liveRows.value]);
const benchSnap = computed(() => (isBench.value ? (detail.value?.servers_snapshot as unknown as BenchSnapshot | null) : null));
const sweepKey = computed<string | null>(() => run.value?.summary?.bench?.sweep ?? SWEEP_OF[run.value?.suite ?? ""] ?? null);
const sweepInfo = computed(() => (sweepKey.value ? SWEEP_UNIT[sweepKey.value] : null));
const numericSweep = computed(() => sweepKey.value === "threads" || sweepKey.value === "n_gpu_layers");

function benchSeries(test: string, color: string, label: string): ChartSeries {
  return {
    id: test,
    label,
    color,
    points: benchRows.value
      .filter((r) => r.test === test && isNum(r.derived.sweep))
      .map((r) => ({ x: r.derived.sweep as number, y: r.t_s_mean })),
  };
}
const tgCurve = computed(() => [benchSeries("tg", "var(--accent)", "generación")]);
const ppCurve = computed(() => [benchSeries("pp", "var(--dev-ram)", "prompt")]);
const sweepRange = computed(() => {
  const xs = benchRows.value.map((r) => r.derived.sweep).filter(isNum);
  return xs.length ? { min: Math.min(...xs), max: Math.max(...xs) } : { min: 0, max: 1 };
});
/** Barras para barridos no numéricos (reparto -ts) o sin barrido. */
const benchBars = computed(() =>
  benchRows.value.map((r) => ({
    test: r.test,
    key: `${r.test}-${r.idx}`,
    label: `${r.test}${r.test === "tg" ? r.n_gen : r.n_prompt}${r.derived.sweep !== null && r.derived.sweep !== undefined ? " · " + r.derived.sweep : ""}`,
    t_s: r.t_s_mean,
    std: r.t_s_std,
  })),
);
function barMax(test: string): number {
  return Math.max(1, ...benchRows.value.filter((r) => r.test === test).map((r) => r.t_s_mean ?? 0));
}
function maxOf(test: string): number | null {
  const v = benchRows.value.filter((r) => r.test === test).map((r) => r.t_s_mean).filter(isNum);
  return v.length ? Math.max(...v) : null;
}
const bestTg = computed(() => run.value?.summary?.bench?.best_tg?.t_s ?? maxOf("tg"));
const bestPp = computed(() => run.value?.summary?.bench?.best_pp?.t_s ?? maxOf("pp"));

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
  if (!r || (r.endpoint_id === null && r.kind !== "bench")) return;
  busy.value = true;
  try {
    const created =
      r.kind === "bench"
        ? await api<{ id: number }>("/api/bench", {
            method: "POST",
            body: JSON.stringify({ suite: r.suite, host_id: r.host_pk, label: r.label, params: r.params }),
          })
        : await api<{ id: number }>("/api/runs", {
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
    <p v-if="!run && !loadError" class="dim">Cargando…</p>

    <template v-if="run">
      <!-- Cabecera -->
      <div class="head">
        <div>
          <h2 class="title">
            Run #{{ run.id }} · {{ suiteLabel(run.suite) }}
            <span v-if="run.label" class="dim">— {{ run.label }}</span>
          </h2>
          <p v-if="run.battle_id" class="small battle-link">
            <RouterLink :to="`/batalla/${run.battle_id}`">⚔ Lado {{ run.side }} de la batalla #{{ run.battle_id }}</RouterLink>
          </p>
          <p class="dim small">
            {{ fmtDate(run.started_at, true) }} · {{ snap?.model_file ?? "modelo sin identificar" }} ·
            {{ isBench ? (benchSnap?.simulated ? "llama-bench simulado" : "llama-bench") : snap?.base_url }} ·
            suite v{{ run.suite_version }} ({{ run.suite_hash }})
          </p>
        </div>
        <div class="actions">
          <Stamp :text="`${status.icon} ${status.text}`" :tone="status.tone" />
          <button v-if="running" class="btn" type="button" :disabled="busy" @click="stop">■ Detener</button>
          <template v-else>
            <button class="btn btn--primary" type="button" :disabled="busy" @click="repeat">↻ Repetir</button>
            <RouterLink v-if="!isBench" class="btn" :to="`/comparar?runs=${run.id}`">Comparar…</RouterLink>
            <button class="btn" type="button" :disabled="busy" @click="remove">Borrar</button>
          </template>
        </div>
      </div>

      <p v-if="run.abort_reason" class="abort mono" role="alert">✕ Abortado por temperatura: {{ run.abort_reason }}</p>
      <p v-if="run.error" class="error mono" role="alert">✕ {{ run.error }}</p>

      <!-- Cifras grandes -->
      <div class="stats">
        <BlueprintCard dense title="Fase">
          <div class="big mono">{{ running ? (lv?.phase ?? "preparando") : status.text }}</div>
          <div class="dim small">{{ fmtDuration(elapsed) }}<span v-if="xMax"> de {{ fmtDuration(xMax) }}</span></div>
          <div v-if="progress !== null" class="progress" role="progressbar" :aria-valuenow="Math.round(progress * 100)" aria-valuemin="0" aria-valuemax="100">
            <div :style="{ width: progress * 100 + '%' }" />
          </div>
        </BlueprintCard>
        <template v-if="isBench">
          <BlueprintCard dense title="Generación (tg)">
            <div class="big mono">{{ fmt(bestTg, 1, "t/s") }}</div>
            <div class="dim small">la mejor del barrido</div>
          </BlueprintCard>
          <BlueprintCard dense title="Procesado de prompt (pp)">
            <div class="big mono">{{ fmt(bestPp, 0, "t/s") }}</div>
            <div class="dim small">{{ fmt(running ? lv?.bench_rows : benchRows.length, 0) }} filas de llama-bench</div>
          </BlueprintCard>
        </template>
        <BlueprintCard v-else dense title="Velocidad (t/s)">
          <div class="big mono">{{ running ? fmt(lastTps, 1) : fmt(sum?.tps_aggregate.median ?? sum?.tps_client.median, 1) }}</div>
          <div class="dim small">{{ running ? "agregado, último segundo" : "mediana (agregado)" }}</div>
        </BlueprintCard>
        <BlueprintCard v-if="!isBench" dense title="Tokens">
          <div class="big mono">{{ fmt(running ? lv?.tokens : sum?.completion_tokens, 0) }}</div>
          <div class="dim small">
            {{ fmt(running ? lv?.requests_done : sum?.requests, 0) }} peticiones
            <span v-if="(running ? lv?.requests_error : sum?.requests_error)" class="warn">
              · ▲ {{ running ? lv?.requests_error : sum?.requests_error }} con error
            </span>
            <span v-if="!running && sum?.requests_cut" class="dim"> · {{ sum.requests_cut }} cortada al terminar</span>
          </div>
        </BlueprintCard>
        <BlueprintCard v-for="id in gpuIds" :key="id" dense :title="devLabel(id)" :color="devColor(id)">
          <div class="big mono">
            {{ fmt(running ? lv?.max_temp?.[id] : sum?.devices[id]?.temp_max_c, 0, "°C") }}
          </div>
          <div class="dim small">máx · aborto a {{ watched[id].crit }} °C ({{ watched[id].source }})</div>
        </BlueprintCard>
      </div>

      <!-- Gráficas -->
      <BlueprintCard title="Telemetría del run" class="gap">
        <div class="charts">
          <LineChart v-if="!isBench" title="Velocidad" unit="t/s" :digits="1" :series="tpsSeries" :bands="bands" :markers="markers" :x-max="xMax" :y-min="0" />
          <LineChart title="Temperatura" unit="°C" :series="tempSeries" :bands="bands" :lines="tempLines" :markers="markers" :x-max="xMax" />
          <LineChart title="Potencia de placa" unit="W" :series="powerSeries" :bands="bands" :markers="markers" :x-max="xMax" :y-min="0" />
          <LineChart title="Reloj SM" unit="MHz" :series="clockSeries" :bands="bands" :markers="markers" :x-max="xMax" :y-min="0" />
        </div>
        <p class="mono dim small note">La potencia es la de placa que reporta el driver, no la del enchufe.</p>
      </BlueprintCard>

      <!-- llama-bench: curva y filas -->
      <BlueprintCard v-if="isBench" :title="numericSweep && sweepInfo ? `t/s frente a ${sweepInfo.label}` : 'Resultados de llama-bench'" class="gap">
        <div v-if="!benchRows.length" class="dim">{{ running ? "Esperando la primera fila (llama-bench carga el modelo)…" : NO_DATA }}</div>
        <div v-else-if="numericSweep && sweepInfo" class="charts">
          <LineChart
            title="Generación (tg)"
            unit="t/s"
            :digits="1"
            :series="tgCurve"
            :y-min="0"
            :x-min="sweepRange.min"
            :x-max="sweepRange.max"
            :x-unit="sweepInfo.unit"
            :x-name="sweepInfo.name"
            dots
          />
          <LineChart
            title="Procesado de prompt (pp)"
            unit="t/s"
            :series="ppCurve"
            :y-min="0"
            :x-min="sweepRange.min"
            :x-max="sweepRange.max"
            :x-unit="sweepInfo.unit"
            :x-name="sweepInfo.name"
            dots
          />
        </div>
        <div v-else class="bars mono">
          <div v-for="b in benchBars" :key="b.key" class="bar">
            <span class="bar__label">{{ b.label }}</span>
            <span class="bar__track">
              <span class="bar__fill" :class="`bar__fill--${b.test}`" :style="{ width: ((b.t_s ?? 0) / barMax(b.test)) * 100 + '%' }" />
            </span>
            <span class="bar__val">{{ fmt(b.t_s, b.test === "tg" ? 1 : 0) }} ± {{ fmt(b.std, 1) }} t/s</span>
          </div>
        </div>
        <div v-if="benchRows.length" class="scroll gap"><table class="items mono">
          <thead>
            <tr>
              <th>prueba</th>
              <th v-if="sweepInfo">{{ sweepInfo.label }}</th>
              <th>t/s</th>
              <th>± desv.</th>
              <th>rep.</th>
              <th>% capas en GPU</th>
              <th>ancho de banda ef.</th>
              <th>dispositivos</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in benchRows" :key="r.idx">
              <td>{{ r.test }}{{ r.test === "tg" ? r.n_gen : r.test === "pp" ? r.n_prompt : `${r.n_prompt}+${r.n_gen}` }}</td>
              <td v-if="sweepInfo">{{ r.derived.sweep ?? NO_DATA }}</td>
              <td>{{ fmt(r.t_s_mean, r.test === "tg" ? 2 : 1) }}</td>
              <td>{{ fmt(r.t_s_std, 2) }}</td>
              <td>{{ fmt(r.reps) }}</td>
              <td>{{ fmt(r.derived.layers_pct, 0, "%") }}</td>
              <td>
                <template v-if="isNum(r.derived.bandwidth_gbs)">{{ fmt(r.derived.bandwidth_gbs, 0, "GB/s") }} <span class="dim">ESTIMADO</span></template>
                <template v-else>{{ r.test === "tg" ? NO_DATA : "—" }}</template>
              </td>
              <td>{{ r.params.devices ?? "—" }}</td>
            </tr>
          </tbody>
        </table></div>
        <p class="mono dim small note">
          Ancho de banda efectivo ≈ tamaño del modelo × t/s de generación: aproximación para modelos densos (no se calcula en MoE).
          llama.cpp cuenta la capa de salida como una más en -ngl.
        </p>
      </BlueprintCard>

      <!-- Respuesta en vivo -->
      <BlueprintCard v-if="running && !isBench" title="Respuesta en streaming" class="gap">
        <pre class="stream mono" aria-live="off">{{ lv?.text || "…" }}</pre>
      </BlueprintCard>

      <!-- Resumen -->
      <BlueprintCard v-if="sum && !running" title="Resumen" class="gap">
        <div class="summary">
          <section v-if="!isBench">
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
          <section v-if="!isBench">
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
            <p v-else class="dim">{{ NO_DATA }}</p>
          </section>
        </div>
      </BlueprintCard>

      <!-- Configuración guardada con el run -->
      <BlueprintCard title="Configuración guardada con el run" class="gap">
        <div class="config mono">
          <div v-if="isBench && benchSnap">
            <h3 class="label">llama-bench</h3>
            <p>{{ benchSnap.simulated ? "simulado" : benchSnap.exe }}</p>
            <p class="dim">versión {{ benchSnap.version ?? NO_DATA }} · {{ sum?.bench?.build?.backends ?? "" }}</p>
            <p>{{ benchSnap.model.path }}</p>
            <p class="dim">
              {{ benchSnap.model.architecture ?? "?" }} · {{ benchSnap.model.file_type ?? "?" }} · {{ benchSnap.model.block_count ?? "?" }} capas ·
              cabecera {{ String(benchSnap.model.header_sha256 ?? "").slice(0, 12) }}
            </p>
            <p class="flags">
              <span v-for="(v, k) in benchSnap.spec" v-show="k !== 'model'" :key="k" class="flag">{{ k }}={{ Array.isArray(v) ? v.join(",") : v }}</span>
            </p>
          </div>
          <div v-else>
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
      <BlueprintCard v-if="detail?.items.length" :title="`Peticiones (${detail.items.length})`" class="gap">
        <div class="scroll"><table class="items mono">
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
                <td>{{ it.name }}<span v-if="libEntry(it.prompt)" class="dim"> · {{ libEntry(it.prompt)?.titulo }}</span></td>
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
                  <template v-if="libEntry(it.prompt)?.respuesta">
                    <h4 class="label">Respuesta de referencia <span class="dim">(biblioteca · compárala tú: no hay corrección automática)</span></h4>
                    <pre class="ref">{{ libEntry(it.prompt)?.respuesta }}</pre>
                  </template>
                </td>
              </tr>
            </template>
          </tbody>
        </table></div>
      </BlueprintCard>

      <!-- Lectura de todas las respuestas -->
      <BlueprintCard v-if="responseRows.length && !running" :title="`Respuestas (${responseRows.length})`" class="gap">
        <p class="dim small intro">
          Todas las respuestas una debajo de otra, con la de referencia cuando el prompt es de la biblioteca. Para revisar si
          redacta bien o comete errores.
        </p>
        <ResponsesMatrix :rows="responseRows" :columns="[{ title: snap?.model_file ?? 'run' }]" :start-collapsed="run.suite === 'estres'" />
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
  font-size: 20px;
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
.scroll {
  overflow-x: auto;
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
.bars {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}
.bar {
  display: grid;
  grid-template-columns: minmax(120px, 200px) 1fr 150px;
  gap: 10px;
  align-items: center;
}
.bar__track {
  height: 10px;
  border: 1px solid var(--line);
}
.bar__fill {
  display: block;
  height: 100%;
}
.bar__fill--tg {
  background: var(--accent);
}
.bar__fill--pp,
.bar__fill--pg {
  background: var(--dev-ram);
}
.bar__val {
  text-align: right;
}
.detail pre.ref {
  border-left: 2px solid var(--accent);
  padding-left: 8px;
}
.battle-link {
  margin: 2px 0 0;
}
.intro {
  margin: 0 0 10px;
}
.btn.tiny {
  padding: 1px 8px;
  font-size: 11px;
}
</style>
