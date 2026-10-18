<script setup lang="ts">
// Seguimiento de un barrido del asistente: pasos con su estado, enlace a cada run y botón para comparar.
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api, gpus, live } from "../api/live";
import type { RunStatus, SweepDetail, SweepStep, SweepStepState } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import Stamp from "../components/Stamp.vue";
import { shortName } from "../lib/devices";
import { NO_DATA, RUN_STATUS, fmt, fmtDate, fmtDuration, isNum, suiteLabel } from "../lib/format";

const props = defineProps<{ id: string }>();
const router = useRouter();
const sid = computed(() => Number(props.id));
const sweep = ref<SweepDetail | null>(null);
const error = ref<string | null>(null);
const busy = ref(false);
const now = ref(Date.now() / 1000);
const clock = window.setInterval(() => (now.value = Date.now() / 1000), 1000);

async function load() {
  try {
    sweep.value = await api<SweepDetail>(`/api/sweeps/${sid.value}`);
    error.value = null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}
let poll: number | undefined;
onMounted(() => {
  load();
  poll = window.setInterval(() => {
    if (running.value) load();
  }, 2000);
});
onBeforeUnmount(() => {
  window.clearInterval(poll);
  window.clearInterval(clock);
});
watch(sid, load);
// El estado llega también por SSE: al cambiar un paso se recarga el detalle (con los runs)
watch(
  () => live.sweeps[sid.value]?.steps.map((s) => s.state).join(),
  () => load(),
);

const status = computed<RunStatus>(() => live.sweeps[sid.value]?.status ?? sweep.value?.status ?? "running");
const running = computed(() => status.value === "running" || status.value === "pending");
const steps = computed(() => (live.sweeps[sid.value]?.steps ?? sweep.value?.steps ?? []) as SweepStep[]);
const host = computed(() => (sweep.value ? (live.hosts[sweep.value.params.host_id] ?? null) : null));
const gpuName = (target: string) => {
  if (target === "auto") return "Automático";
  if (target === "reparto") return "Repartido entre GPU";
  return shortName(gpus(host.value).find((g) => g.device_id === target)?.name ?? target);
};

const STATE: Record<SweepStepState, { icon: string; text: string; tone: "info" | "warn" | "crit" | "dim" }> = {
  pendiente: { icon: "◌", text: "pendiente", tone: "dim" },
  comprobando: { icon: "◌", text: "comprobando encaje", tone: "info" },
  arrancando: { icon: "◐", text: "cargando el modelo", tone: "warn" },
  midiendo: { icon: "▶", text: "midiendo", tone: "info" },
  hecho: { icon: "●", text: "hecho", tone: "info" },
  error: { icon: "✕", text: "error", tone: "crit" },
  "no cabe": { icon: "▲", text: "no cabe", tone: "warn" },
  omitido: { icon: "–", text: "omitido", tone: "dim" },
  detenido: { icon: "■", text: "detenido", tone: "warn" },
};
const done = computed(() => steps.value.filter((s) => ["hecho", "error", "no cabe", "omitido", "detenido"].includes(s.state)).length);
const progress = computed(() => (steps.value.length ? done.value / steps.value.length : 0));
const doneRuns = computed(() => steps.value.filter((s) => s.state === "hecho" && s.run_id).map((s) => s.run_id as number));

function result(s: SweepStep): string {
  const run = sweep.value?.runs[String(s.run_id)];
  const q = run?.summary?.quality;
  if (q) {
    if (q.suite === "concurrencia") return isNum(q.best_tps_aggregate) ? `${fmt(q.best_tps_aggregate, 1)} t/s agregados` : NO_DATA;
    return `${q.correct}/${q.total}${isNum(q.accuracy_pct) ? ` · ${fmt(q.accuracy_pct, 0)} %` : ""}`;
  }
  const tps = run?.summary?.tps_client.median;
  return isNum(tps) ? `${fmt(tps, 1)} t/s` : NO_DATA;
}
function elapsed(s: SweepStep): string {
  if (!s.started_at) return "";
  return fmtDuration((s.finished_at ?? now.value) - s.started_at);
}

async function cancel() {
  busy.value = true;
  try {
    await api(`/api/sweeps/${sid.value}/cancel`, { method: "POST" });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
async function remove() {
  if (!window.confirm("¿Borrar el barrido y todos sus runs?")) return;
  try {
    await api(`/api/sweeps/${sid.value}`, { method: "DELETE" });
    router.push("/asistente");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}
const compareLink = computed(() => `/comparar?runs=${doneRuns.value.join(",")}`);
</script>

<template>
  <div class="page">
    <p v-if="error && !sweep" class="error mono" role="alert">✕ {{ error }}</p>
    <template v-if="sweep">
      <div class="head">
        <div>
          <h2 class="title">Barrido #{{ sweep.id }}<span v-if="sweep.label" class="dim"> · {{ sweep.label }}</span></h2>
          <span class="dim small">
            {{ fmtDate(sweep.created_at) }} · {{ suiteLabel(sweep.params.suite) }} · contexto {{ fmt(sweep.params.fit.ctx) }} × {{ sweep.params.fit.parallel }} slots ·
            {{ host?.name ?? "equipo" }}
          </span>
        </div>
        <div class="actions">
          <Stamp :text="`${RUN_STATUS[status]?.icon} ${RUN_STATUS[status]?.text ?? status}`" :tone="RUN_STATUS[status]?.tone ?? 'dim'" :tilt="0" />
          <button v-if="running" class="btn btn--danger" type="button" :disabled="busy" @click="cancel">■ Cancelar</button>
          <RouterLink v-if="doneRuns.length" class="btn btn--primary" :to="compareLink">
            {{ doneRuns.length > 1 ? `Comparar los ${doneRuns.length} resultados` : "Ver el resultado" }}
          </RouterLink>
          <RouterLink class="btn" to="/asistente">Nuevo barrido</RouterLink>
          <button v-if="!running" class="btn" type="button" @click="remove">Borrar</button>
        </div>
      </div>

      <p v-if="sweep.error" class="warn" role="alert">▲ {{ sweep.error }}</p>

      <div class="progress" role="progressbar" :aria-valuenow="Math.round(progress * 100)" aria-valuemin="0" aria-valuemax="100" :aria-label="`${done} de ${steps.length} pasos`">
        <div :style="{ width: progress * 100 + '%' }" />
      </div>
      <p class="dim small">{{ done }} de {{ steps.length }} pasos</p>

      <BlueprintCard title="Pasos">
        <div class="scroll">
          <table class="steps">
            <thead>
              <tr><th>#</th><th>modelo</th><th>destino</th><th>estado</th><th>resultado</th><th>tiempo</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in steps" :key="s.i" :class="{ now: ['arrancando', 'midiendo', 'comprobando'].includes(s.state) }">
                <td class="mono">{{ s.i + 1 }}</td>
                <td class="name">{{ s.model_name }}</td>
                <td>
                  {{ gpuName(s.target) }}
                  <span v-if="s.option" class="dim small"><br />{{ s.option }}<template v-if="s.port"> · :{{ s.port }}</template></span>
                </td>
                <td>
                  <Stamp :text="`${STATE[s.state].icon} ${STATE[s.state].text}`" :tone="STATE[s.state].tone" :tilt="0" />
                  <span v-if="s.message" class="msg small">{{ s.message }}</span>
                </td>
                <td class="mono">
                  <template v-if="s.run_id"><RouterLink :to="`/pruebas/${s.run_id}`">{{ result(s) }}</RouterLink></template>
                  <template v-else>—</template>
                </td>
                <td class="mono dim">{{ elapsed(s) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
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
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 12px;
}
.warn {
  color: var(--warn);
}
.error {
  color: var(--crit);
}
.progress {
  height: 8px;
  border-radius: 999px;
  background: var(--panel);
  overflow: hidden;
}
.progress div {
  height: 100%;
  background: var(--accent);
  transition: width 0.4s;
}
.scroll {
  overflow-x: auto;
}
.steps {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.steps th {
  text-align: left;
  font-weight: 500;
  color: var(--ink-dim);
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
}
.steps td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  vertical-align: top;
}
.steps tr.now {
  background: color-mix(in srgb, var(--accent) 7%, transparent);
}
.name {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.msg {
  display: block;
  margin-top: 4px;
  color: var(--ink-dim);
  max-width: 420px;
  overflow-wrap: anywhere;
}
</style>
