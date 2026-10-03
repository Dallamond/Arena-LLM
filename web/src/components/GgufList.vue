<script setup lang="ts">
// GGUF en disco de un equipo con su encaje ESTIMADO (pesos + KV + cómputo) frente a la memoria libre.
import { computed, onMounted, reactive, ref, watch } from "vue";
import { api } from "../api/live";
import type { FitParams, FitResponse, ModelFile, ModelsResponse } from "../api/types";
import { shortName } from "../lib/devices";
import { NO_DATA, fmt, isNum } from "../lib/format";
import BarWithOverflow from "./BarWithOverflow.vue";
import Stamp from "./Stamp.vue";

const props = defineProps<{ hostId: number }>();
const emit = defineEmits<{ count: [n: number, bytes: number] }>();

const STORE_KEY = "arena.fit";
const CTX_PRESETS = [4096, 8192, 16384, 32768, 65536, 131072];
const KV_TYPES = ["f16", "q8_0", "q4_0"];

function loadParams(): FitParams {
  const base: FitParams = { ctx: 8192, parallel: 1, kv_type: "f16" };
  try {
    return { ...base, ...JSON.parse(localStorage.getItem(STORE_KEY) ?? "{}") };
  } catch {
    return base;
  }
}
const params = reactive<FitParams>(loadParams());

const models = ref<ModelsResponse | null>(null);
const error = ref<string | null>(null);
const fits = reactive<Record<string, FitResponse | { error: string } | undefined>>({});
const open = ref<Record<string, boolean>>({});
const loading = ref(false);

// Las partes 2..n de un modelo partido no se listan: la parte 1 ya suma el modelo entero.
const files = computed(() => (models.value?.files ?? []).filter((f) => !f.split_part || f.split_part === 1));

function partsSize(f: ModelFile): number {
  if (!f.split_total) return f.size;
  const stem = f.path.replace(/-\d{5}-of-\d{5}\.gguf$/i, "");
  return (models.value?.files ?? []).filter((x) => x.path.startsWith(stem) && x.split_total).reduce((a, x) => a + x.size, 0);
}

async function loadModels() {
  error.value = null;
  try {
    models.value = await api<ModelsResponse>(`/api/hosts/${props.hostId}/models`);
    emit("count", files.value.length, files.value.reduce((a, f) => a + partsSize(f), 0));
  } catch (e) {
    error.value = (e as Error).message;
  }
}

let generation = 0;
async function computeFits() {
  const gen = ++generation;
  loading.value = true;
  const q = new URLSearchParams({ ctx: String(params.ctx), parallel: String(params.parallel), kv_type: params.kv_type });
  const queue = [...files.value];
  const worker = async () => {
    for (let f = queue.shift(); f; f = queue.shift()) {
      const path = f.path;
      try {
        const r = await api<FitResponse>(`/api/hosts/${props.hostId}/fit?path=${encodeURIComponent(path)}&${q}`);
        if (gen === generation) fits[path] = r;
      } catch (e) {
        if (gen === generation) fits[path] = { error: (e as Error).message };
      }
    }
  };
  await Promise.all([worker(), worker()]);
  if (gen === generation) loading.value = false;
}

let timer: number | undefined;
watch(params, () => {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(params));
  } catch {
    /* sin almacenamiento: se usa el valor por defecto */
  }
  window.clearTimeout(timer);
  timer = window.setTimeout(computeFits, 350);
});

onMounted(async () => {
  await loadModels();
  await computeFits();
});

defineExpose({ refresh: async () => (await loadModels(), computeFits()) });

const GIB = 1024 ** 3;
const gb = (b: number | null | undefined, d = 1) => (isNum(b) ? fmt(b / GIB, d, "GiB") : NO_DATA);

const VERDICT: Record<string, { icon: string; cls: string }> = {
  gpu: { icon: "✓", cls: "ok" },
  split: { icon: "⇄", cls: "info" },
  ram: { icon: "▨", cls: "warn" },
  cpu: { icon: "▨", cls: "warn" },
  no: { icon: "✕", cls: "crit" },
  unknown: { icon: "?", cls: "dim" },
};

/** Etiqueta con nombres cortos de GPU ("RTX 3060" en vez de "NVIDIA GeForce RTX 3060"). */
function verdictLabel(r: FitResponse): string {
  const fitting = r.fit.gpus.filter((g) => g.fits);
  if (r.fit.verdict === "gpu" && fitting.length) return `Cabe en ${fitting.map((g) => shortName(g.name)).join(" · ")}`;
  return r.fit.label ?? NO_DATA;
}

function ok(r: FitResponse | { error: string } | undefined): FitResponse | null {
  return r && "fit" in r ? r : null;
}

/** Barra: la GPU donde cabe (o la de más memoria libre); sólido = VRAM, rayado = lo que se va a RAM. */
function bar(r: FitResponse) {
  const gs = r.fit.gpus.filter((g) => isNum(g.free));
  if (!gs.length || !isNum(r.fit.need_full_gpu)) return null;
  const g = gs.find((x) => x.fits) ?? gs.reduce((a, b) => ((b.free ?? 0) > (a.free ?? 0) ? b : a));
  const free = g.free as number;
  const need = r.fit.need_full_gpu as number;
  return {
    name: shortName(g.name),
    used: Math.min(need, free) / 1024 ** 2,
    total: free / 1024 ** 2,
    overflow: need > free ? (need - free) / 1024 ** 2 : null,
  };
}

const rows = computed(() =>
  files.value.map((f) => {
    const raw = fits[f.path];
    const r = ok(raw);
    return { f, r, err: raw && "error" in raw ? raw.error : null, b: r ? bar(r) : null };
  }),
);

function params_b(n: number | null | undefined): string {
  if (!isNum(n) || n <= 0) return NO_DATA;
  return n >= 1e9 ? `${fmt(n / 1e9, 1)} B` : `${fmt(n / 1e6, 0)} M`;
}
</script>

<template>
  <div class="gguf">
    <div class="controls">
      <label>
        <span class="label">Contexto (-c)</span>
        <select v-model.number="params.ctx">
          <option v-for="c in CTX_PRESETS" :key="c" :value="c">{{ fmt(c) }}</option>
        </select>
      </label>
      <label>
        <span class="label">Slots (-np)</span>
        <input v-model.number="params.parallel" type="number" min="1" max="64" />
      </label>
      <label>
        <span class="label">Caché KV</span>
        <select v-model="params.kv_type">
          <option v-for="k in KV_TYPES" :key="k" :value="k">{{ k }}</option>
        </select>
      </label>
      <button class="btn" type="button" :disabled="loading" @click="computeFits">{{ loading ? "Calculando…" : "Recalcular con la memoria libre de ahora" }}</button>
      <Stamp text="estimado" tone="warn" :tilt="0" />
    </div>

    <p v-if="error" class="empty">No se pudo leer la carpeta de modelos: {{ error }}</p>
    <div v-else-if="models && !models.model_dirs.length" class="empty">
      <p>El agente no tiene carpetas de modelos configuradas.</p>
      <p class="dim">Añade <code>"model_dirs"</code> en <code>agent.json</code> o lanza el agente con <code>--models-dir &lt;carpeta&gt;</code>.</p>
    </div>
    <p v-else-if="models && !files.length" class="empty">No hay ficheros .gguf en {{ models.model_dirs.join(", ") }}.</p>
    <p v-for="(msg, dir) in models?.errors ?? {}" :key="dir" class="dim">{{ dir }}: {{ msg }}</p>

    <ul class="rows">
      <li v-for="{ f, r, err, b } in rows" :key="f.path" class="row">
        <template v-if="r">
          <div class="main">
            <div class="name">
              <span class="title">{{ r!.model.name ?? f.file }}</span>
              <span class="tag">{{ r!.model.architecture ?? "?" }}</span>
              <span v-if="r!.estimate.kind === 'mmproj'" class="tag">proyector</span>
              <span v-if="(r!.estimate.recurrent ?? 0) > 0" class="tag">híbrido</span>
              <span v-if="r!.model.expert_count" class="tag">MoE</span>
              <span v-if="f.split_total" class="tag">{{ f.split_total }} partes</span>
            </div>
            <div class="facts data">
              {{ r!.model.file_type ?? NO_DATA }} · {{ params_b(r!.model.n_params) }} ·
              {{ gb(partsSize(f)) }} · ctx entrenado {{ fmt(r!.model.context_length) }}
            </div>
            <div class="file dim">{{ f.path }}</div>
          </div>

          <div class="side">
            <template v-if="r!.estimate.kind === 'model'">
              <span class="verdict" :class="`verdict--${VERDICT[r!.fit.verdict]?.cls ?? 'dim'}`">
                <span aria-hidden="true">{{ VERDICT[r!.fit.verdict]?.icon }}</span> {{ verdictLabel(r!) }}
              </span>
              <div v-if="b" class="barbox">
                <BarWithOverflow
                  v-bind="b!"
                  :label="`Encaje en ${b!.name}`"
                  thin
                />
                <span class="dim small">necesita {{ gb(r!.fit.need_full_gpu) }} · libre en {{ b!.name }}</span>
              </div>
              <button class="btn tiny" type="button" :aria-expanded="!!open[f.path]" @click="open[f.path] = !open[f.path]">
                {{ open[f.path] ? "Ocultar" : "Ver" }} desglose
              </button>
            </template>
            <span v-else class="dim small">{{ r!.estimate.notes[0] }}</span>
          </div>

          <div v-if="open[f.path] && r!.estimate.kind === 'model'" class="detail">
            <dl class="kv">
              <div><dt>pesos en capas</dt><dd class="data">{{ gb(r!.estimate.weights_layers, 2) }} · {{ r!.estimate.n_layers }} capas</dd></div>
              <div><dt>salida (GPU)</dt><dd class="data">{{ gb(r!.estimate.output, 2) }}</dd></div>
              <div><dt>embeddings (RAM)</dt><dd class="data">{{ gb(r!.estimate.token_embd, 2) }}</dd></div>
              <div>
                <dt>caché KV</dt>
                <dd class="data">{{ gb(r!.estimate.kv, 2) }} · {{ r!.estimate.kv_layers }} capas con atención</dd>
              </div>
              <div v-if="r!.estimate.recurrent"><dt>estado recurrente</dt><dd class="data">{{ gb(r!.estimate.recurrent, 2) }}</dd></div>
              <div><dt>búfer de cómputo</dt><dd class="data">{{ gb(r!.estimate.compute, 2) }}</dd></div>
              <div><dt>reserva por GPU</dt><dd class="data">{{ fmt(r!.estimate.params?.reserve_mib) }} MiB</dd></div>
              <div v-if="isNum(r!.fit.ngl)"><dt>-ngl sugerido</dt><dd class="data">{{ r!.fit.ngl }}</dd></div>
              <div v-if="isNum(r!.fit.ram_need)"><dt>RAM necesaria</dt><dd class="data">{{ gb(r!.fit.ram_need, 2) }}</dd></div>
              <div v-for="g in r!.fit.gpus" :key="g.device_id">
                <dt>{{ shortName(g.name) }}</dt>
                <dd class="data">
                  libre {{ gb(g.free) }} ·
                  <b>{{ g.fits ? "cabe" : g.fits_if_empty ? "cabría vacía" : "no cabe" }}</b>
                </dd>
              </div>
            </dl>
            <ul v-if="r!.estimate.notes.length || r!.fit.hint" class="notes">
              <li v-if="r!.fit.hint">{{ r!.fit.hint }}</li>
              <li v-for="n in r!.estimate.notes" :key="n">{{ n }}</li>
            </ul>
          </div>
        </template>

        <template v-else>
          <div class="main">
            <div class="name"><span class="title">{{ f.file }}</span></div>
            <div class="file dim">{{ f.path }}</div>
          </div>
          <div class="side dim small">
            {{ err ?? "Leyendo cabecera…" }}
          </div>
        </template>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.controls {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.controls label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.controls input {
  width: 80px;
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 340px);
  gap: 8px 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  padding: 12px 14px;
}
@media (max-width: 900px) {
  .row {
    grid-template-columns: 1fr;
  }
}
.name {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.title {
  font-weight: 600;
  font-size: 14px;
  color: var(--ink);
}
.tag {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border: 1px solid var(--line);
  padding: 0 5px;
  color: var(--ink-dim);
}
.facts {
  margin-top: 4px;
  font-size: 12px;
}
.file {
  font-size: 11px;
  overflow-wrap: anywhere;
  margin-top: 2px;
}
.side {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
}
.verdict {
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border: 1px solid currentColor;
}
.verdict--ok {
  color: var(--ok);
}
.verdict--info {
  color: var(--accent);
}
.verdict--warn {
  color: var(--warn);
}
.verdict--crit {
  color: var(--crit);
}
.verdict--dim {
  color: var(--ink-dim);
}
.barbox {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.detail {
  grid-column: 1 / -1;
  border-top: 1px dotted var(--line);
  padding-top: 8px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}
@media (max-width: 900px) {
  .detail {
    grid-template-columns: 1fr;
  }
}
.kv {
  margin: 0;
  font-size: 12px;
}
.kv div {
  display: grid;
  grid-template-columns: 150px 1fr;
  gap: 10px;
  padding: 2px 0;
  border-bottom: 1px dotted var(--line);
}
.kv dt {
  color: var(--ink-dim);
}
.kv dd {
  margin: 0;
}
.notes {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
  color: var(--ink-dim);
}
.empty {
  border: 1px dashed var(--line-strong);
  padding: 14px;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 11px;
}
.btn.tiny {
  padding: 1px 8px;
  font-size: 11px;
}
code {
  font-family: var(--font-mono);
}
</style>
