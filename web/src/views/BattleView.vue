<script setup lang="ts">
// Una batalla: columnas por lado con la respuesta en streaming y cifras grandes; al terminar,
// marcador (veredictos + métricas) y las respuestas de todos los lados prompt a prompt.
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api, live, onEvent } from "../api/live";
import type { BattleDetail, CompareResponse, RunStatus } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import ResponsesMatrix from "../components/ResponsesMatrix.vue";
import Sparkline from "../components/Sparkline.vue";
import Stamp from "../components/Stamp.vue";
import { shortName } from "../lib/devices";
import { NO_DATA, RUN_STATUS, fmt, fmtDate, isNum } from "../lib/format";

const props = defineProps<{ id: string }>();
const router = useRouter();
const bid = computed(() => Number(props.id));
const battle = ref<BattleDetail | null>(null);
const cmp = ref<CompareResponse | null>(null);
const error = ref<string | null>(null);
const busy = ref(false);
const tpsHist = ref<Record<number, number[]>>({});
const ttfts = ref<Record<number, number[]>>({});

const status = computed<RunStatus>(() => live.battles[bid.value]?.status ?? battle.value?.status ?? "running");
const running = computed(() => status.value === "running" || status.value === "pending");
const color = (i: number) => `var(--dev-${(i % 6) + 1})`;

async function load() {
  try {
    battle.value = await api<BattleDetail>(`/api/battles/${bid.value}`);
    error.value = null;
    const ids = battle.value.runs.filter((r) => r && r.status !== "running").map((r) => r!.id);
    if (!running.value && ids.length) cmp.value = await api<CompareResponse>(`/api/compare?runs=${ids.join(",")}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

let timer: number | undefined;
const reload = () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(load, 250);
};
const runIds = computed(() => new Set((battle.value?.sides ?? []).map((s) => s.run_id).filter((x): x is number => x !== null)));
const offs: (() => void)[] = [];
onMounted(() => {
  load();
  offs.push(
    onEvent("battle", (b: { id: number }) => b.id === bid.value && reload()),
    onEvent("run", (r: { id: number; battle_id?: number | null }) => (r.battle_id === bid.value || runIds.value.has(r.id)) && reload()),
    onEvent("run_live", (d: { run: number; tps?: number }) => {
      if (runIds.value.has(d.run) && isNum(d.tps)) (tpsHist.value[d.run] ??= []).push(d.tps);
    }),
    onEvent("run_item", (d: { run: number; metrics?: { ttft_s?: number } }) => {
      if (runIds.value.has(d.run) && isNum(d.metrics?.ttft_s)) (ttfts.value[d.run] ??= []).push(d.metrics!.ttft_s!);
    }),
  );
});
onBeforeUnmount(() => {
  offs.forEach((f) => f());
  window.clearTimeout(timer);
});
watch(bid, () => {
  cmp.value = null;
  load();
});

function median(xs: number[] | undefined): number | null {
  if (!xs?.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

const columns = computed(() =>
  (battle.value?.sides ?? []).map((s, i) => {
    const run = battle.value?.runs[i] ?? null;
    const lv = run ? live.runLive[run.id] : undefined;
    const fresh = run ? live.runs[run.id] : undefined;
    const st = (fresh?.status ?? run?.status ?? (running.value ? "pending" : "cancelled")) as RunStatus;
    const summary = fresh?.summary ?? run?.summary ?? null;
    const snap = run?.servers_snapshot ?? null;
    const host = run?.host_pk ? live.hosts[run.host_pk] : undefined;
    const gpus = (snap?.devices ?? []).map((d) => shortName(host?.devices.find((x) => x.device_id === d.device_id)?.name ?? d.device_id));
    const total = (battle.value?.params?.prompts.length ?? 0) * Number(battle.value?.params?.common?.repeats ?? 1);
    // En marcha: la máxima en vivo; al terminar, la del resumen, solo de las GPU de este lado
    const own = Object.keys(summary?.thresholds ?? {});
    const doneTemps = own.map((d) => summary?.devices?.[d]?.temp_max_c).filter(isNum);
    const maxTemp = lv ? Math.max(...Object.values(lv.max_temp ?? {}), -Infinity) : Math.max(...doneTemps, -Infinity);
    return {
      side: s,
      run,
      st,
      color: color(i),
      title: `Lado ${s.side}`,
      model: snap?.model_file ?? null,
      url: snap?.base_url ?? null,
      gpus: gpus.join(" + "),
      live: st === "running" ? lv : undefined,
      tps: st === "running" ? (lv?.tps ?? null) : (summary?.tps_client?.median ?? null),
      ttft: summary?.ttft_s?.median ?? (run ? median(ttfts.value[run.id]) : null),
      tokens: st === "running" ? (lv?.tokens ?? null) : (summary?.completion_tokens ?? null),
      done: st === "running" ? (lv?.requests_done ?? 0) : (summary?.requests ?? null),
      total,
      temp: isFinite(maxTemp) ? maxTemp : null,
      hist: run ? tpsHist.value[run.id] ?? [] : [],
      params: s.params,
    };
  }),
);

const matrixColumns = computed(() =>
  (cmp.value?.runs ?? []).map((r) => {
    const i = columns.value.findIndex((c) => c.run?.id === r.id);
    return { title: `Lado ${r.side ?? "?"}`, sub: columns.value[i]?.model ?? r.title, color: color(i) };
  }),
);
const compareLink = computed(() => `/comparar?runs=${[...runIds.value].join(",")}`);
const sideOf = (runIndex: number) => {
  const id = cmp.value?.runs[runIndex]?.id;
  return columns.value.find((c) => c.run?.id === id);
};

async function stop() {
  busy.value = true;
  try {
    await api(`/api/battles/${bid.value}/cancel`, { method: "POST" });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
async function repeat() {
  const b = battle.value;
  if (!b?.params) return;
  busy.value = true;
  try {
    const nb = await api<{ id: number }>("/api/battles", {
      method: "POST",
      body: JSON.stringify({
        mode: b.mode,
        label: b.label,
        prompts: b.params.prompts,
        common: b.params.common,
        sides: b.sides.map((s) => ({ endpoint_id: s.endpoint_id, label: s.label, params: s.params })),
      }),
    });
    router.push(`/batalla/${nb.id}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
async function remove() {
  busy.value = true;
  try {
    await api(`/api/battles/${bid.value}`, { method: "DELETE" });
    router.push("/batalla");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
const statusInfo = computed(() => RUN_STATUS[status.value] ?? { text: status.value, tone: "dim", icon: "" });
const paramText = (p: Record<string, unknown>) =>
  Object.entries(p)
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
    .join(" · ") || "parámetros comunes";
</script>

<template>
  <div class="page">
    <p v-if="error" class="error mono" role="alert">✕ {{ error }}</p>
    <p v-if="!battle && !error" class="dim">Cargando…</p>

    <template v-if="battle">
      <div class="head">
        <div>
          <h2 class="title">
            Batalla #{{ battle.id }}<span v-if="battle.label" class="dim"> — {{ battle.label }}</span>
          </h2>
          <p class="dim small">
            {{ fmtDate(battle.created_at, true) }} · {{ battle.sides.length }} lados ·
            {{ battle.mode === "paralelo" ? "en paralelo" : "uno detrás de otro" }} · {{ battle.params?.prompts.length }} prompts ·
            semilla {{ battle.params?.common?.seed ?? 42 }}
          </p>
        </div>
        <div class="actions">
          <Stamp :text="`${statusInfo.icon} ${statusInfo.text}`" :tone="statusInfo.tone" />
          <button v-if="running" class="btn" type="button" :disabled="busy" @click="stop">■ Detener</button>
          <template v-else>
            <RouterLink class="btn btn--primary" :to="compareLink">Ver en Comparar</RouterLink>
            <button class="btn" type="button" :disabled="busy" @click="repeat">↻ Repetir</button>
            <button class="btn" type="button" :disabled="busy" @click="remove">Borrar</button>
          </template>
        </div>
      </div>
      <p v-if="battle.error" class="error mono" role="alert">✕ {{ battle.error }}</p>

      <!-- Columnas por lado -->
      <div class="cols" :style="{ gridTemplateColumns: `repeat(${Math.min(columns.length, 3)}, minmax(0, 1fr))` }">
        <section v-for="c in columns" :key="c.side.side" class="col" :style="{ borderTopColor: c.color }">
          <header class="col__head">
            <div>
              <h3 class="col__title" :style="{ color: c.color }">■ {{ c.title }}<span v-if="c.side.label" class="dim"> · {{ c.side.label }}</span></h3>
              <p class="dim small mono">{{ c.model ?? "—" }} · {{ c.url ?? "" }} · {{ c.gpus || "GPU sin asociar" }}</p>
              <p class="dim small mono">{{ paramText(c.params) }}</p>
            </div>
            <Stamp :text="RUN_STATUS[c.st]?.text ?? c.st" :tone="RUN_STATUS[c.st]?.tone ?? 'dim'" :tilt="0" />
          </header>
          <dl class="nums">
            <div><dt>t/s</dt><dd class="big mono">{{ fmt(c.tps, 1) }}</dd></div>
            <div><dt>TTFT</dt><dd class="big mono">{{ fmt(c.ttft, 2, "s") }}</dd></div>
            <div><dt>tokens</dt><dd class="big mono">{{ fmt(c.tokens) }}</dd></div>
            <div><dt>temp. máx</dt><dd class="big mono">{{ fmt(c.temp, 0, "°C") }}</dd></div>
          </dl>
          <p class="dim small">
            peticiones {{ fmt(c.done) }} / {{ c.total || NO_DATA }}
            <RouterLink v-if="c.run" :to="`/pruebas/${c.run.id}`"> · run #{{ c.run.id }}</RouterLink>
          </p>
          <Sparkline v-if="c.hist.length > 1" :values="c.hist" :color="c.color" :height="34" :capacity="Math.max(60, c.hist.length)" label="t/s en vivo" />
          <pre v-if="c.live" class="stream">{{ c.live.text || "…" }}</pre>
          <p v-else-if="c.st === 'pending'" class="dim small">En espera: va después del lado anterior.</p>
        </section>
      </div>

      <!-- Marcador -->
      <BlueprintCard v-if="cmp && !running" title="Marcador" class="gap">
        <div v-if="cmp.verdicts.length" class="verdicts">
          <div v-for="v in cmp.verdicts" :key="v.key" class="verdict" :style="{ borderColor: sideOf(v.run_index)?.color }">
            <span class="label">{{ v.title }}</span>
            <b :style="{ color: sideOf(v.run_index)?.color }">■ {{ sideOf(v.run_index)?.title ?? cmp.runs[v.run_index].title }}</b>
            <span class="mono">{{ fmt(v.value, v.key === "ttft" ? 2 : v.key === "tps" ? 1 : 0, cmp.metrics.find((m) => m.key === v.key)?.unit ?? "") }}</span>
            <span v-if="v.margin_pct !== null" class="dim small">{{ fmt(v.margin_pct, 0, "%") }} mejor</span>
          </div>
        </div>
        <div class="scroll">
          <table class="tbl mono">
            <thead>
              <tr>
                <th>métrica</th>
                <th v-for="r in cmp.runs" :key="r.id">Lado {{ r.side }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in cmp.metrics" :key="m.key">
                <td class="sans">{{ m.label }}</td>
                <td v-for="(v, i) in m.values" :key="i" :class="{ best: m.best.includes(i) }">
                  {{ fmt(v, m.digits, m.unit) }}<span v-if="m.best.includes(i)"> ▲</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="small cmp-note">
          <Stamp :text="cmp.comparability.label" :tone="cmp.comparability.level === 'si' ? 'info' : cmp.comparability.level === 'parcial' ? 'warn' : 'crit'" :tilt="0" />
          <span class="dim">{{ cmp.comparability.reasons.join(" ") || (cmp.comparability.changes.length ? `Cambia: ${cmp.comparability.changes.join(", ")}.` : "") }}</span>
        </p>
      </BlueprintCard>

      <!-- Respuestas -->
      <BlueprintCard v-if="cmp?.items.length && !running" :title="`Respuestas por prompt (${cmp.items.length})`" class="gap">
        <ResponsesMatrix :rows="cmp.items" :columns="matrixColumns" />
      </BlueprintCard>
    </template>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.title {
  font-size: 20px;
  margin: 0 0 4px;
}
.actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 11px;
}
.error {
  color: var(--crit);
  border: 1px dashed var(--crit);
  padding: 8px 10px;
}
.gap {
  margin-top: 18px;
}
.cols {
  display: grid;
  gap: 14px;
}
@media (max-width: 1100px) {
  .cols {
    grid-template-columns: 1fr !important;
  }
}
.col {
  background: var(--panel);
  border: 1px solid var(--line);
  border-top: 3px solid var(--line-strong);
  padding: 12px 14px;
  min-width: 0;
}
.col__head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: flex-start;
}
.col__head p {
  margin: 2px 0 0;
  overflow-wrap: anywhere;
}
.col__title {
  font-size: 15px;
  margin: 0;
}
.nums {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 12px 0 6px;
}
.nums dt {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-faint);
}
.nums dd {
  margin: 0;
}
.big {
  font-size: 22px;
}
.stream {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.5;
  max-height: 260px;
  overflow-y: auto;
  border-top: 1px dotted var(--line);
  padding-top: 8px;
  margin: 8px 0 0;
}
.verdicts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.verdict {
  display: flex;
  flex-direction: column;
  gap: 2px;
  border: 1px solid var(--line);
  border-left-width: 3px;
  padding: 8px 10px;
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
}
.tbl td {
  padding: 4px 8px;
  border-bottom: 1px dotted var(--line);
}
.tbl .sans {
  font-family: var(--font-sans);
  color: var(--ink-dim);
}
.best {
  color: var(--ok);
  font-weight: 600;
}
.cmp-note {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin: 10px 0 0;
}
</style>
