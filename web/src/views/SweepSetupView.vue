<script setup lang="ts">
// Asistente: elegir equipo y GPU, varios modelos y una prueba; Arena arranca cada modelo en cada destino, lo mide,
// lo para y deja los resultados listos para comparar. Solo toca los servidores que lanza él mismo.
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api, gpus, gpuSample, hostList, live } from "../api/live";
import type { Suite, Sweep } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import ModelPicker from "../components/ModelPicker.vue";
import PromptPicker from "../components/PromptPicker.vue";
import Stamp from "../components/Stamp.vue";
import SuiteForm from "../components/SuiteForm.vue";
import { deviceColor, shortName } from "../lib/devices";
import { RUN_STATUS, fmt, fmtDate, isNum } from "../lib/format";
import { splitPrompts } from "../lib/library";
import { initialState, toParams, type FormState } from "../lib/suiteForm";

const MAX_STEPS = 36;
const CTX_PRESETS = [4096, 8192, 16384, 32768, 65536];
const TESTS = ["qa", "codigo", "contexto", "concurrencia", "libre"];
const router = useRouter();

const error = ref<string | null>(null);
const busy = ref(false);
const sweeps = ref<Sweep[]>([]);
const suites = ref<Suite[]>([]);

// 1 · equipo y destinos
const hostId = ref<number | null>(null);
watch(
  hostList,
  (list) => {
    if (hostId.value === null || !list.some((h) => h.id === hostId.value)) hostId.value = list.find((h) => h.status === "online")?.id ?? list[0]?.id ?? null;
  },
  { immediate: true },
);
const host = computed(() => (hostId.value !== null ? (live.hosts[hostId.value] ?? null) : null));
const gpuList = computed(() => gpus(host.value));
const targets = ref<string[]>(["auto"]);
watch(gpuList, (list) => {
  const ids = new Set(["auto", "reparto", ...list.map((g) => g.device_id)]);
  targets.value = targets.value.filter((t) => ids.has(t));
  if (!targets.value.length) targets.value = ["auto"];
});
function toggleTarget(id: string) {
  const cur = new Set(targets.value);
  if (id === "auto") return (targets.value = ["auto"]);
  cur.delete("auto");
  if (!cur.delete(id)) cur.add(id);
  targets.value = cur.size ? [...cur] : ["auto"];
}
function freeGib(id: string): number | null {
  const snap = hostId.value !== null ? live.metrics[hostId.value] : null;
  const s = gpuSample(snap, id);
  return isNum(s?.mem_total_mib) && isNum(s?.mem_used_mib) ? (s.mem_total_mib - s.mem_used_mib) / 1024 : null;
}
const targetName = (t: string) => (t === "auto" ? "Automático" : t === "reparto" ? "Repartido" : shortName(gpuList.value.find((g) => g.device_id === t)?.name ?? t));
const mainTarget = computed(() => (targets.value.length === 1 && !["auto", "reparto"].includes(targets.value[0]) ? targets.value[0] : "auto"));

// 2 · modelos
const models = ref<string[]>([]);
watch(hostId, () => (models.value = []));
const fit = reactive({ ctx: 8192, parallel: 1, kv_type: "f16" });

// 3 · prueba
const testId = ref("qa");
const forms = reactive<Record<string, FormState>>({});
const prompts = ref("");
const promptDefaults = ref<string[]>([]);
const freeOpts = reactive({ max_tokens: 256, repeats: 1 });
const suite = computed(() => suites.value.find((s) => s.id === testId.value) ?? null);
const tests = computed(() => TESTS.map((id) => suites.value.find((s) => s.id === id)).filter((s): s is Suite => !!s));

// 4 · lanzar
const label = ref("");
const loadTimeout = ref(600);
const steps = computed(() => models.value.length * targets.value.length);
const tooMany = computed(() => steps.value > MAX_STEPS);
const canLaunch = computed(
  () => !busy.value && hostId.value !== null && host.value?.status === "online" && models.value.length > 0 && !tooMany.value && (testId.value !== "libre" || splitPrompts(prompts.value).length > 0),
);

const otherServers = computed(() =>
  hostId.value === null ? [] : (live.endpoints[hostId.value] ?? []).filter((e) => e.status === "listo" || e.status === "cargando"),
);

function suiteParams(): Record<string, unknown> {
  if (testId.value === "libre") return { prompts: splitPrompts(prompts.value), max_tokens: freeOpts.max_tokens, repeats: freeOpts.repeats, baseline_s: 3 };
  const s = suite.value;
  if (!s) throw new Error("Elige una prueba");
  return { ...toParams(s, forms[s.id]), baseline_s: s.defaults.baseline_s ?? 3 };
}

async function launch() {
  error.value = null;
  busy.value = true;
  try {
    const sw = await api<Sweep>("/api/sweeps", {
      method: "POST",
      body: JSON.stringify({
        host_id: hostId.value,
        models: models.value,
        targets: targets.value,
        ctx: fit.ctx,
        parallel: fit.parallel,
        kv_type: fit.kv_type,
        suite: testId.value,
        params: suiteParams(),
        label: label.value || null,
        load_timeout_s: loadTimeout.value,
      }),
    });
    router.push(`/asistente/${sw.id}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

onMounted(async () => {
  try {
    suites.value = await api<Suite[]>("/api/suites");
    for (const s of suites.value) if (TESTS.includes(s.id) && s.id !== "libre") forms[s.id] = initialState(s);
    promptDefaults.value = (suites.value.find((s) => s.id === "libre")?.defaults.prompts as string[]) ?? [];
    prompts.value = promptDefaults.value.join("\n---\n");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
  api<Sweep[]>("/api/sweeps?limit=15")
    .then((s) => (sweeps.value = s))
    .catch(() => {});
});
</script>

<template>
  <div class="page">
    <div class="head">
      <h2 class="title">Asistente</h2>
      <span class="dim small">Elige modelos y GPU, una prueba, y Arena los arranca, mide y para uno detrás de otro.</span>
    </div>

    <div v-if="!hostList.length" class="empty">
      <p>Aún no hay ningún equipo registrado.</p>
      <p class="dim">Arranca el agente (<code>python -m agent</code>) y aparecerá aquí.</p>
    </div>

    <template v-else>
      <!-- 1 -->
      <BlueprintCard title="1 · Equipo y GPU">
        <div class="row">
          <label v-if="hostList.length > 1" class="field">
            <span class="label">equipo</span>
            <select v-model="hostId">
              <option v-for="h in hostList" :key="h.id" :value="h.id">{{ h.name }}{{ h.status === "online" ? "" : ` (${h.status})` }}</option>
            </select>
          </label>
          <div class="chips" role="group" aria-label="Destinos">
            <button type="button" class="chip" :class="{ 'chip--on': targets.includes('auto') }" :aria-pressed="targets.includes('auto')" @click="toggleTarget('auto')">
              <span class="chip__name">Automático</span><span class="chip__sub">la que mejor le cabe</span>
            </button>
            <button
              v-for="g in gpuList"
              :key="g.device_id"
              type="button"
              class="chip"
              :class="{ 'chip--on': targets.includes(g.device_id) }"
              :style="{ '--c': deviceColor(g) }"
              :aria-pressed="targets.includes(g.device_id)"
              @click="toggleTarget(g.device_id)"
            >
              <span class="chip__name"><span class="dot" aria-hidden="true" />{{ shortName(g.name) }}</span>
              <span class="chip__sub num2">{{ isNum(freeGib(g.device_id)) ? fmt(freeGib(g.device_id), 1, "GiB libres") : "sin datos" }}</span>
            </button>
            <button v-if="gpuList.length > 1" type="button" class="chip" :class="{ 'chip--on': targets.includes('reparto') }" :aria-pressed="targets.includes('reparto')" @click="toggleTarget('reparto')">
              <span class="chip__name">Repartido</span><span class="chip__sub">entre las GPU</span>
            </button>
          </div>
        </div>
        <p class="dim small">
          Cada modelo se prueba en <b>cada</b> destino marcado ({{ targets.map(targetName).join(" · ") }}). Marcar dos GPU sirve para comparar la misma tarjeta frente a la otra.
        </p>
        <p v-if="otherServers.length" class="warn small">
          ▲ Hay {{ otherServers.length }} servidor{{ otherServers.length > 1 ? "es" : "" }} en marcha en este equipo ({{ otherServers.map((e) => e.alias || e.snapshot?.model_file || e.base_url).join(", ") }}).
          Arena no los toca, pero ocupan memoria y cómputo: lo que no quepa con la memoria libre se salta, y las medidas de velocidad se verán afectadas si están trabajando.
        </p>
      </BlueprintCard>

      <!-- 2 -->
      <BlueprintCard title="2 · Modelos" class="gap">
        <div class="form">
          <label>
            <span class="label">contexto (-c)</span>
            <select v-model.number="fit.ctx"><option v-for="c in CTX_PRESETS" :key="c" :value="c">{{ fmt(c) }}</option></select>
          </label>
          <label><span class="label">slots (-np)</span><input v-model.number="fit.parallel" type="number" min="1" max="64" /></label>
          <label>
            <span class="label">caché KV</span>
            <select v-model="fit.kv_type"><option v-for="k in ['f16', 'q8_0', 'q4_0']" :key="k" :value="k">{{ k }}</option></select>
          </label>
        </div>
        <ModelPicker v-if="hostId !== null" v-model="models" :host-id="hostId" :ctx="fit.ctx" :parallel="fit.parallel" :kv-type="fit.kv_type" :target="mainTarget" />
      </BlueprintCard>

      <!-- 3 -->
      <BlueprintCard title="3 · Qué medir" class="gap">
        <div class="seg" role="radiogroup" aria-label="Prueba">
          <button v-for="t in tests" :key="t.id" type="button" role="radio" class="seg__btn" :aria-checked="testId === t.id" @click="testId = t.id">
            {{ t.id === "libre" ? "Prompts propios" : t.name }}
          </button>
        </div>
        <p v-if="suite && testId !== 'libre'" class="dim small desc">{{ suite.description }}</p>
        <p v-else class="dim small desc">Prompts tuyos: se miden velocidad y TTFT y se guardan las respuestas para leerlas. No hay corrección automática.</p>
        <SuiteForm v-if="suite && testId !== 'libre' && forms[suite.id]" :suite="suite" :model-value="forms[suite.id]" id-prefix="sweep" />
        <template v-else-if="testId === 'libre'">
          <PromptPicker v-model="prompts" :defaults="promptDefaults" @max-tokens="(n) => (freeOpts.max_tokens = n)" />
          <div class="form">
            <label><span class="label">tokens máximos</span><input v-model.number="freeOpts.max_tokens" type="number" min="1" max="131072" /></label>
            <label><span class="label">repeticiones</span><input v-model.number="freeOpts.repeats" type="number" min="1" max="100" /></label>
          </div>
        </template>
      </BlueprintCard>

      <!-- 4 -->
      <BlueprintCard title="4 · Revisar y lanzar" class="gap">
        <div class="summary">
          <div class="stat"><span class="label">modelos</span><b class="num big">{{ models.length }}</b></div>
          <div class="stat"><span class="label">destinos</span><b class="num big">{{ targets.length }}</b></div>
          <div class="stat">
            <span class="label">pasos</span>
            <b class="num big" :class="{ warn: tooMany }">{{ steps }}</b>
            <span class="dim small">cada uno: arrancar, medir, parar</span>
          </div>
        </div>
        <div class="form">
          <label class="wide"><span class="label">etiqueta (opcional)</span><input v-model="label" type="text" maxlength="80" placeholder="p. ej. 7B–14B en la 3060 y la M40" /></label>
          <label>
            <span class="label">espera máx. de carga (s)</span>
            <input v-model.number="loadTimeout" type="number" min="30" max="3600" />
          </label>
        </div>
        <p v-if="tooMany" class="warn small">▲ Máximo {{ MAX_STEPS }} pasos por barrido: quita modelos o destinos.</p>
        <p class="dim small">
          Arena lanza <code>llama-server</code> en <code>127.0.0.1</code> con los parámetros calculados para cada paso y lo para al terminar. Si algo no cabe con la memoria libre en ese momento,
          el paso se salta y el barrido sigue. Puedes cancelar en cualquier momento.
        </p>
        <button class="btn btn--primary" type="button" :disabled="!canLaunch" @click="launch">
          ▶ Lanzar el barrido ({{ steps }} {{ steps === 1 ? "paso" : "pasos" }})
        </button>
        <p v-if="host && host.status !== 'online'" class="warn small">▲ El agente de este equipo no está en línea.</p>
        <p v-if="error" class="error mono" role="alert">✕ {{ error }}</p>
      </BlueprintCard>

      <BlueprintCard v-if="sweeps.length" title="Barridos recientes" class="gap">
        <table class="tbl mono">
          <tbody>
            <tr v-for="s in sweeps" :key="s.id">
              <td><RouterLink :to="`/asistente/${s.id}`">#{{ s.id }}</RouterLink></td>
              <td>{{ fmtDate(s.created_at) }}</td>
              <td class="sans">{{ s.label ?? "" }}</td>
              <td>{{ s.params.models.length }} modelos × {{ s.params.targets.length }} destinos · {{ s.params.suite }}</td>
              <td><Stamp :text="`${RUN_STATUS[s.status]?.icon} ${RUN_STATUS[s.status]?.text ?? s.status}`" :tone="RUN_STATUS[s.status]?.tone ?? 'dim'" :tilt="0" /></td>
            </tr>
          </tbody>
        </table>
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
  font-size: 12px;
}
.warn {
  color: var(--warn);
}
.error {
  color: var(--crit-ink);
  margin: 10px 0 0;
}
.gap {
  margin-top: 18px;
}
.empty {
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  padding: 18px;
}
.row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  margin-bottom: 8px;
}
.field,
.form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}
.chip {
  --c: var(--ink-dim);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  padding: 8px 16px;
  border: 1.5px solid transparent;
  border-radius: var(--radius-sm);
  background: var(--panel);
  cursor: pointer;
  text-align: left;
}
.chip:hover {
  background: var(--panel-raised);
}
.chip--on {
  border-color: var(--c);
  background: var(--panel-raised);
}
.chip__name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
}
.chip__sub {
  font-size: 12px;
  color: var(--ink-faint);
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--c);
}
.num2 {
  font-variant-numeric: tabular-nums;
}
.form {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  margin-bottom: 14px;
}
.form .wide {
  flex: 1 1 320px;
}
.seg {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.seg__btn {
  padding: 7px 16px;
  border: 1.5px solid transparent;
  border-radius: 999px;
  background: var(--panel);
  color: var(--ink);
  font: inherit;
  cursor: pointer;
}
.seg__btn[aria-checked="true"] {
  border-color: var(--accent);
  background: var(--panel-raised);
  font-weight: 600;
}
.desc {
  margin: 0 0 12px;
}
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.stat {
  display: flex;
  flex-direction: column;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg);
}
.big {
  font-size: 30px;
}
.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.tbl td {
  padding: 5px 10px;
  border-bottom: 1px solid var(--line);
}
.sans {
  font-family: var(--font-sans, inherit);
}
code {
  font-family: var(--font-mono);
}
</style>
