<script setup lang="ts">
// Elegir varios GGUF de un equipo para el asistente: cada uno con su encaje ESTIMADO frente a la memoria
// libre de ahora y la etiqueta de recomendado. El contexto, los slots y la caché KV los fija el asistente.
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { api } from "../api/live";
import type { FitResponse, ModelsResponse } from "../api/types";
import { shortName } from "../lib/devices";
import { NO_DATA, fmt, isNum } from "../lib/format";
import { recommend } from "../lib/recommend";

const props = defineProps<{
  hostId: number;
  ctx: number;
  parallel: number;
  kvType: string;
  target: string; // "auto" | device_id: contra qué GPU se evalúan los recomendados
  modelValue: string[];
}>();
const emit = defineEmits<{ "update:modelValue": [paths: string[]] }>();

const models = ref<ModelsResponse | null>(null);
const fits = reactive<Record<string, FitResponse | { error: string } | undefined>>({});
const error = ref<string | null>(null);
const loading = ref(false);
const filter = ref("");

const files = computed(() => (models.value?.files ?? []).filter((f) => !f.split_part || f.split_part === 1));
const ok = (r: FitResponse | { error: string } | undefined) => (r && "fit" in r ? r : null);

let generation = 0;
async function compute() {
  const gen = ++generation;
  loading.value = true;
  const q = new URLSearchParams({ ctx: String(props.ctx), parallel: String(props.parallel), kv_type: props.kvType });
  const queue = [...files.value];
  const worker = async () => {
    for (let f = queue.shift(); f; f = queue.shift()) {
      try {
        const r = await api<FitResponse>(`/api/hosts/${props.hostId}/fit?path=${encodeURIComponent(f.path)}&${q}`);
        if (gen === generation) fits[f.path] = r;
      } catch (e) {
        if (gen === generation) fits[f.path] = { error: (e as Error).message };
      }
    }
  };
  await Promise.all([worker(), worker()]);
  if (gen === generation) loading.value = false;
}

async function load() {
  error.value = null;
  models.value = null;
  try {
    models.value = await api<ModelsResponse>(`/api/hosts/${props.hostId}/models`);
    await compute();
  } catch (e) {
    error.value = (e as Error).message;
  }
}
onMounted(load);
watch(() => props.hostId, load);
let timer: number | undefined;
watch(
  () => [props.ctx, props.parallel, props.kvType],
  () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(compute, 350);
  },
);
onBeforeUnmount(() => window.clearTimeout(timer));

const recs = computed(() =>
  recommend(
    files.value.map((f) => ({ path: f.path, r: ok(fits[f.path]) })),
    props.target,
    Math.floor(props.ctx / Math.max(props.parallel, 1)),
    shortName,
  ),
);

const GIB = 1024 ** 3;
const VERDICT: Record<string, { icon: string; cls: string }> = {
  gpu: { icon: "✓", cls: "ok" },
  split: { icon: "⇄", cls: "info" },
  ram: { icon: "▨", cls: "warn" },
  cpu: { icon: "▨", cls: "warn" },
  no: { icon: "✕", cls: "crit" },
  unknown: { icon: "?", cls: "dim" },
};

const rows = computed(() => {
  const q = filter.value.trim().toLowerCase();
  return files.value
    .map((f) => ({ f, r: ok(fits[f.path]), err: "error" in (fits[f.path] ?? {}) ? (fits[f.path] as { error: string }).error : null }))
    .filter(({ f, r }) => !q || `${f.file} ${r?.model.name ?? ""}`.toLowerCase().includes(q))
    .sort((a, b) => (recs.value.get(a.f.path)?.rank ?? 99) - (recs.value.get(b.f.path)?.rank ?? 99) || (b.r?.model.n_params ?? 0) - (a.r?.model.n_params ?? 0));
});

const selected = computed(() => new Set(props.modelValue));
function toggle(path: string) {
  const next = new Set(selected.value);
  if (!next.delete(path)) next.add(path);
  emit("update:modelValue", [...next]);
}
function pickRecommended() {
  emit("update:modelValue", [...recs.value.keys()]);
}
const verdictText = (r: FitResponse) => {
  const fitting = r.fit.gpus.filter((g) => g.fits);
  return r.fit.verdict === "gpu" && fitting.length ? `Cabe en ${fitting.map((g) => shortName(g.name)).join(" · ")}` : (r.fit.label ?? NO_DATA);
};
function paramsB(n: number | null | undefined): string {
  if (!isNum(n) || n <= 0) return NO_DATA;
  return n >= 1e9 ? `${fmt(n / 1e9, 1)} B` : `${fmt(n / 1e6, 0)} M`;
}
</script>

<template>
  <div class="mp">
    <div class="mp__tools">
      <input v-model="filter" type="search" class="mp__search" placeholder="Filtrar modelos…" aria-label="Filtrar modelos" />
      <button type="button" class="btn" :disabled="!recs.size" @click="pickRecommended">★ Marcar los recomendados ({{ recs.size }})</button>
      <button type="button" class="btn" :disabled="!modelValue.length" @click="emit('update:modelValue', [])">Quitar todos</button>
      <span class="dim small">{{ modelValue.length }} elegidos · {{ loading ? "calculando encaje…" : "encaje con la memoria libre de ahora" }}</span>
    </div>
    <p v-if="error" class="warn">No se pudo leer la carpeta de modelos: {{ error }}</p>
    <p v-else-if="models && !models.model_dirs.length" class="dim">
      El agente no tiene carpetas de modelos configuradas (<code>model_dirs</code> en <code>agent.json</code>).
    </p>
    <p v-else-if="models && !files.length" class="dim">No hay ficheros .gguf en {{ models.model_dirs.join(", ") }}.</p>

    <ul class="mp__list">
      <li v-for="{ f, r, err } in rows" :key="f.path" class="mp__row" :class="{ 'mp__row--on': selected.has(f.path) }">
        <label class="mp__label">
          <input type="checkbox" :checked="selected.has(f.path)" :disabled="r?.estimate.kind === 'mmproj'" @change="toggle(f.path)" />
          <span class="mp__name">{{ r?.model.name ?? f.file }}</span>
        </label>
        <template v-if="r">
          <span v-if="recs.get(f.path)" class="tag tag--rec" :title="recs.get(f.path)!.reason">
            <span aria-hidden="true">★</span> {{ recs.get(f.path)!.rank === 1 ? "Mejor para tu hardware" : "Recomendado" }}
          </span>
          <span class="mp__facts mono">{{ paramsB(r.model.n_params) }} · {{ r.model.file_type ?? "?" }} · {{ fmt(f.size / GIB, 1) }} GiB</span>
          <span v-if="r.estimate.kind === 'model'" class="verdict" :class="`verdict--${VERDICT[r.fit.verdict]?.cls ?? 'dim'}`">
            <span aria-hidden="true">{{ VERDICT[r.fit.verdict]?.icon }}</span> {{ verdictText(r) }}
          </span>
          <span v-else class="dim small">{{ r.estimate.notes[0] }}</span>
        </template>
        <span v-else class="dim small">{{ err ?? "Leyendo cabecera…" }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.mp {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mp__tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.mp__search {
  min-width: 220px;
}
.mp__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 420px;
  overflow: auto;
}
.mp__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg);
  border: 1.5px solid transparent;
}
.mp__row--on {
  border-color: var(--accent);
}
.mp__label {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 220px;
  flex: 1 1 260px;
  font-weight: 600;
  cursor: pointer;
}
.mp__name {
  overflow-wrap: anywhere;
}
.mp__facts {
  font-size: 13px;
  color: var(--ink-dim);
}
.tag--rec {
  font-size: 12px;
  font-weight: 600;
  padding: 1px 10px;
  border-radius: 999px;
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 14%, transparent);
  cursor: help;
}
.verdict {
  font-size: 13px;
  font-weight: 600;
  padding: 2px 12px;
  border-radius: 999px;
  color: var(--tone);
  background: color-mix(in srgb, var(--tone) 14%, transparent);
}
.verdict--ok {
  --tone: var(--ok);
}
.verdict--info {
  --tone: #64d2ff;
}
.verdict--warn {
  --tone: var(--warn);
}
.verdict--crit {
  --tone: var(--crit);
}
.verdict--dim {
  --tone: var(--ink-dim);
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
</style>
