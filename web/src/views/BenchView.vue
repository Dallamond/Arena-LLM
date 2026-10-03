<script setup lang="ts">
// Rendimiento por componente: el agente lanza llama-bench (F6).
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api, cpu, currentHost, gpus, runList } from "../api/live";
import type { BenchDevicesResponse, ModelFile, ModelsResponse, Suite } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import Stamp from "../components/Stamp.vue";
import { deviceColor, shortName } from "../lib/devices";
import { RUN_STATUS, fmt, fmtDate, gib } from "../lib/format";

const router = useRouter();
const suites = ref<Suite[]>([]);
const suiteId = ref("bench-dispositivo");
const suite = computed(() => suites.value.find((s) => s.id === suiteId.value) ?? null);

const bench = ref<BenchDevicesResponse | null>(null);
const benchError = ref<string | null>(null);
const models = ref<ModelFile[]>([]);
const modelsError = ref<string | null>(null);
const modelPath = ref("");

const error = ref<string | null>(null);
const canForce = ref(false);
const busy = ref(false);

const STANDARD = { n_prompt: "512", n_gen: "128", repetitions: 3 };
const form = reactive({
  ...STANDARD,
  sweep: "",
  flash_attn: "",
  cache_type_k: "",
  cache_type_v: "",
  baseline_s: 5,
  label: "",
});
const isStandard = computed(
  () =>
    form.n_prompt.trim() === STANDARD.n_prompt &&
    form.n_gen.trim() === STANDARD.n_gen &&
    Number(form.repetitions) === STANDARD.repetitions &&
    !form.flash_attn &&
    !form.cache_type_k &&
    !form.cache_type_v,
);

const host = currentHost;
const hostGpus = computed(() => gpus(host.value));
const hostCpu = computed(() => cpu(host.value));
const benchGpus = computed(() => (bench.value?.devices ?? []).filter((d) => d.device_id));
function benchName(id: string): string | undefined {
  return benchGpus.value.find((d) => d.device_id === id)?.name;
}

// Dispositivos elegidos: "cpu" o device_id de GPU
const single = ref<string>("");
const multi = ref<string[]>([]);

async function loadHost() {
  bench.value = null;
  benchError.value = null;
  models.value = [];
  modelsError.value = null;
  const h = host.value;
  if (!h) return;
  try {
    bench.value = await api<BenchDevicesResponse>(`/api/hosts/${h.id}/bench/devices`);
  } catch (e) {
    benchError.value = e instanceof Error ? e.message : String(e);
  }
  try {
    const r = await api<ModelsResponse>(`/api/hosts/${h.id}/models`);
    models.value = r.files.filter((f) => !/mmproj/i.test(f.file) && (f.split_part === null || f.split_part === 1));
    if (!r.model_dirs.length) modelsError.value = "El agente no tiene carpetas de modelos (model_dirs o --models-dir).";
    if (!models.value.some((m) => m.path === modelPath.value)) modelPath.value = models.value[0]?.path ?? "";
  } catch (e) {
    modelsError.value = e instanceof Error ? e.message : String(e);
  }
  const first = hostGpus.value.find((g) => benchName(g.device_id))?.device_id;
  single.value = first ?? "cpu";
  multi.value = first ? [first] : [];
}

watch(() => host.value?.id, loadHost);
watch(suiteId, () => {
  form.sweep = "";
  if (suiteId.value === "bench-ts") multi.value = benchGpus.value.map((d) => d.device_id as string);
  else if (suiteId.value === "bench-ngl" && multi.value.length > 1) multi.value = multi.value.slice(0, 1);
  error.value = null;
  canForce.value = false;
});

onMounted(async () => {
  try {
    suites.value = (await api<Suite[]>("/api/suites")).filter((s) => s.mode === "bench");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
  await loadHost();
});

function ints(text: string, name: string): number[] {
  const vals = text.split(/[,\s]+/).filter(Boolean).map(Number);
  if (!vals.length || vals.some((v) => !Number.isInteger(v) || v < 0)) throw new Error(`${name}: enteros separados por comas`);
  return vals;
}

function deviceIds(): string[] {
  if (suiteId.value === "bench-cpu") return ["cpu"];
  if (suiteId.value === "bench-dispositivo") return [single.value];
  return multi.value;
}

const sweepPlaceholder = computed(() => {
  switch (suite.value?.sweep) {
    case "threads":
      return `automático: 1, 2, mitad, ${host.value?.host?.cpu_cores ?? "núcleos"}, ${host.value?.host?.cpu_threads ?? "hilos"}`;
    case "n_gpu_layers":
      return "automático: 0, ¼, ½, ¾ y todas las capas del modelo";
    case "tensor_split":
      return "automático: 1/1, proporcional a la VRAM, 3/1, 2/1, 1/2, 1/3";
    default:
      return "";
  }
});

async function launch(force = false) {
  const h = host.value;
  if (!h || !suite.value) return;
  error.value = null;
  canForce.value = false;
  busy.value = true;
  try {
    const params: Record<string, unknown> = {
      model: modelPath.value,
      device_ids: deviceIds(),
      n_prompt: ints(form.n_prompt, "tamaño de prompt"),
      n_gen: ints(form.n_gen, "tokens generados"),
      repetitions: Number(form.repetitions),
      baseline_s: Number(form.baseline_s),
    };
    if (form.sweep.trim()) {
      params.sweep =
        suite.value.sweep === "tensor_split"
          ? form.sweep.split(/[,\s]+/).filter(Boolean)
          : ints(form.sweep, suite.value.sweep_label ?? "barrido");
    }
    for (const k of ["flash_attn", "cache_type_k", "cache_type_v"] as const) if (form[k]) params[k] = form[k];
    const run = await api<{ id: number }>("/api/bench", {
      method: "POST",
      body: JSON.stringify({ suite: suite.value.id, host_id: h.id, label: form.label || null, force, params }),
    });
    router.push(`/pruebas/${run.id}`);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    error.value = msg;
    canForce.value = /lanza igualmente/i.test(msg);
  } finally {
    busy.value = false;
  }
}

const recent = computed(() => runList.value.filter((r) => r.kind === "bench").slice(0, 8));
const SUITE_NAMES = computed(() => Object.fromEntries(suites.value.map((s) => [s.id, s.name])));
const canLaunch = computed(
  () =>
    !!host.value &&
    !!bench.value &&
    !!modelPath.value &&
    deviceIds().length > 0 &&
    (suiteId.value !== "bench-ts" || multi.value.length >= 2),
);
</script>

<template>
  <div class="page">
    <h2 class="title">Rendimiento por componente</h2>

    <!-- llama-bench del equipo -->
    <BlueprintCard :title="`llama-bench · ${host?.name ?? 'sin equipo'}`">
      <p v-if="!host" class="dim">No hay ningún equipo registrado.</p>
      <div v-else-if="benchError" class="empty">
        <p class="warn">▲ {{ benchError }}</p>
        <p class="dim small">
          Añade la ruta en la configuración del agente (<code>agent.json</code>: <code>"llama_bench": "…/llama-bench"</code>) o
          arráncalo con <code>--llama-bench</code>. El agente solo ejecuta ese fichero, con una lista cerrada de flags.
        </p>
      </div>
      <div v-else-if="bench" class="benchinfo mono">
        <span>{{ bench.simulated ? "llama-bench simulado" : bench.exe }}</span>
        <span class="dim">versión {{ bench.version ?? "sin datos" }}</span>
        <span v-for="d in bench.devices" :key="d.name" class="dim">
          {{ d.name }} = {{ d.description }} ({{ gib(d.total_mib) }})
        </span>
      </div>
      <p v-else class="dim">Consultando al agente…</p>
    </BlueprintCard>

    <!-- Tipo de prueba -->
    <div class="suites" role="radiogroup" aria-label="Tipo de prueba">
      <label
        v-for="s in suites"
        :key="s.id"
        class="suite"
        :class="{ 'suite--on': s.id === suiteId, 'suite--off': (s.min_gpus ?? 0) > benchGpus.length }"
      >
        <input v-model="suiteId" type="radio" name="suite" :value="s.id" :disabled="(s.min_gpus ?? 0) > benchGpus.length" />
        <span>
          <b>{{ s.name }}</b>
          <span class="dim small block">{{ s.description }}</span>
          <span v-if="(s.min_gpus ?? 0) > benchGpus.length" class="dim small block">Necesita {{ s.min_gpus }} GPU o más.</span>
        </span>
      </label>
    </div>

    <BlueprintCard v-if="suite" :title="suite.name" class="gap">
      <div class="form">
        <label class="wide">
          <span class="label">modelo (GGUF)</span>
          <select v-model="modelPath" :disabled="!models.length">
            <option v-for="m in models" :key="m.path" :value="m.path">{{ m.file }} · {{ gib(m.size / 1048576) }}</option>
          </select>
          <span v-if="modelsError" class="warn small">▲ {{ modelsError }}</span>
          <span v-else-if="!models.length" class="dim small">Sin GGUF en las carpetas del agente.</span>
        </label>

        <!-- Dispositivos -->
        <fieldset v-if="suiteId === 'bench-dispositivo'" class="wide devs">
          <legend class="label">dispositivo</legend>
          <label v-for="g in hostGpus" :key="g.device_id" class="dev" :class="{ 'dev--off': !benchName(g.device_id) }">
            <input v-model="single" type="radio" name="single" :value="g.device_id" :disabled="!benchName(g.device_id)" />
            <span :style="{ color: deviceColor(g) }">■</span> {{ shortName(g.name) }}
            <span class="dim mono">{{ benchName(g.device_id) ?? "llama-bench no la ve" }}</span>
          </label>
          <label class="dev">
            <input v-model="single" type="radio" name="single" value="cpu" />
            <span style="color: var(--dev-ram)">■</span> {{ shortName(hostCpu?.name) || "CPU" }} <span class="dim mono">sin GPU</span>
          </label>
        </fieldset>
        <fieldset v-else-if="suiteId !== 'bench-cpu'" class="wide devs">
          <legend class="label">{{ suiteId === "bench-ts" ? "GPU entre las que repartir" : "GPU (las capas que no quepan van a RAM)" }}</legend>
          <label v-for="g in hostGpus" :key="g.device_id" class="dev" :class="{ 'dev--off': !benchName(g.device_id) }">
            <input v-model="multi" type="checkbox" :value="g.device_id" :disabled="!benchName(g.device_id)" />
            <span :style="{ color: deviceColor(g) }">■</span> {{ shortName(g.name) }}
            <span class="dim mono">{{ benchName(g.device_id) ?? "llama-bench no la ve" }}</span>
          </label>
          <p v-if="!hostGpus.length" class="dim small">Este equipo no tiene GPU.</p>
        </fieldset>

        <label v-if="suite.sweep" class="wide">
          <span class="label">barrido de {{ suite.sweep_label }}</span>
          <input v-model="form.sweep" type="text" :placeholder="sweepPlaceholder" />
        </label>

        <label><span class="label">tamaño de prompt (pp)</span><input v-model="form.n_prompt" type="text" /></label>
        <label><span class="label">tokens generados (tg)</span><input v-model="form.n_gen" type="text" /></label>
        <label><span class="label">repeticiones</span><input v-model.number="form.repetitions" type="number" min="1" max="50" /></label>
        <label>
          <span class="label">flash attention</span>
          <select v-model="form.flash_attn">
            <option value="">lo que decida la build</option>
            <option value="on">on</option>
            <option value="off">off</option>
          </select>
        </label>
        <label>
          <span class="label">caché K / V</span>
          <span class="pair">
            <select v-model="form.cache_type_k" aria-label="tipo de caché K">
              <option value="">f16</option>
              <option v-for="t in ['q8_0', 'q4_0', 'bf16', 'f32']" :key="t" :value="t">{{ t }}</option>
            </select>
            <select v-model="form.cache_type_v" aria-label="tipo de caché V">
              <option value="">f16</option>
              <option v-for="t in ['q8_0', 'q4_0', 'bf16', 'f32']" :key="t" :value="t">{{ t }}</option>
            </select>
          </span>
        </label>
        <label><span class="label">reposo antes (s)</span><input v-model.number="form.baseline_s" type="number" min="0" max="600" /></label>
        <label class="wide"><span class="label">etiqueta (opcional)</span><input v-model="form.label" type="text" maxlength="80" /></label>
      </div>

      <p class="small">
        <Stamp v-if="isStandard" text="perfil estándar v1" tone="info" :tilt="0" />
        <Stamp v-else text="perfil propio" tone="warn" :tilt="0" />
        <span class="dim">
          pp {{ STANDARD.n_prompt }} · tg {{ STANDARD.n_gen }} · {{ STANDARD.repetitions }} repeticiones en cualquier equipo. Cambiarlo hace que el run no sea comparable con otros del perfil estándar.
        </span>
      </p>
      <p class="dim small">
        Antes de lanzar, Arena comprueba que no haya un servidor ocupando la tarjeta y que el modelo quepa (ESTIMADO).
      </p>
      <div class="actions">
        <button class="btn btn--primary" type="button" :disabled="busy || !canLaunch" @click="launch(false)">▶ Lanzar llama-bench</button>
        <button v-if="canForce" class="btn" type="button" :disabled="busy" @click="launch(true)">Lanzar igualmente</button>
      </div>
      <p v-if="error" class="error mono" role="alert">✕ {{ error }}</p>
    </BlueprintCard>

    <BlueprintCard title="Últimos benchmarks" class="gap">
      <p v-if="!recent.length" class="dim">Todavía no hay ninguno.</p>
      <ul v-else class="recent mono">
        <li v-for="r in recent" :key="r.id">
          <RouterLink :to="`/pruebas/${r.id}`">#{{ r.id }}</RouterLink>
          {{ SUITE_NAMES[r.suite] ?? r.suite }}
          <span class="dim">· {{ fmtDate(r.started_at) }}</span>
          <span v-if="r.summary?.bench?.best_tg"> · tg {{ fmt(r.summary.bench.best_tg.t_s, 1, "t/s") }}</span>
          <span v-if="r.summary?.bench?.best_pp"> · pp {{ fmt(r.summary.bench.best_pp.t_s, 0, "t/s") }}</span>
          <span class="dim"> · {{ RUN_STATUS[r.status]?.icon }} {{ RUN_STATUS[r.status]?.text }}</span>
        </li>
      </ul>
    </BlueprintCard>
  </div>
</template>

<style scoped>
.title {
  font-size: 20px;
  margin-bottom: 14px;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 11px;
}
.block {
  display: block;
  margin-top: 3px;
}
.warn {
  color: var(--warn);
}
.gap {
  margin-top: 18px;
}
.error {
  color: var(--crit);
  border: 1px dashed var(--crit);
  padding: 8px 10px;
  margin: 12px 0 0;
}
.empty p {
  margin: 0 0 6px;
}
.benchinfo {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.suites {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 12px;
  margin-top: 18px;
}
.suite {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  border: 1px solid var(--line);
  padding: 10px 12px;
  cursor: pointer;
  font-size: 13px;
}
.suite--on {
  border-color: var(--accent);
  background: rgba(108, 180, 255, 0.06);
}
.suite--off {
  opacity: 0.55;
  cursor: not-allowed;
}
.form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 10px 14px;
  margin-bottom: 12px;
}
.form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form .wide {
  grid-column: 1 / -1;
}
.devs {
  border: 1px dashed var(--line);
  padding: 8px 10px;
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
}
.devs legend {
  padding: 0 4px;
}
.dev {
  flex-direction: row !important;
  align-items: center;
  gap: 6px !important;
  font-size: 12px;
}
.dev--off {
  opacity: 0.55;
}
.pair {
  display: flex;
  gap: 6px;
}
input[type="number"],
input[type="text"],
select {
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 5px 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink);
  min-width: 0;
}
.actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.recent {
  list-style: none;
  margin: 0;
  padding: 0;
  font-size: 12px;
}
.recent li {
  padding: 4px 0;
  border-bottom: 1px dotted var(--line);
}
code {
  font-family: var(--font-mono);
}
</style>
