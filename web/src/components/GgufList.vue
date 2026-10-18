<script setup lang="ts">
// GGUF en disco de un equipo con su encaje ESTIMADO (pesos + KV + cómputo) frente a la memoria libre.
// Se elige la GPU destino y cada modelo se lanza directamente en ella (el agente ejecuta llama-server).
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { api, gpus, gpuSample, live, now } from "../api/live";
import type {
  FitParams,
  FitResponse,
  LaunchedResponse,
  LaunchedServer,
  LaunchOption,
  ModelFile,
  ModelsResponse,
} from "../api/types";
import { deviceColor, shortName } from "../lib/devices";
import { NO_DATA, fmt, isNum } from "../lib/format";
import { recommend } from "../lib/recommend";
import BarWithOverflow from "./BarWithOverflow.vue";
import LaunchCommand from "./LaunchCommand.vue";
import Stamp from "./Stamp.vue";

const props = defineProps<{ hostId: number }>();
const emit = defineEmits<{ count: [n: number, bytes: number] }>();

const STORE_KEY = "arena.fit";
const TARGET_KEY = "arena.launchTarget";
const SORT_KEY = "arena.modelSort";
const CTX_PRESETS = [4096, 8192, 16384, 32768, 65536, 131072];
const KV_TYPES = ["f16", "q8_0", "q4_0"];

function stored<T extends object>(key: string, base: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...base, ...JSON.parse(raw) } : base;
  } catch {
    return base;
  }
}
function store(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* sin almacenamiento: se usa el valor por defecto */
  }
}

const params = reactive<FitParams>(stored<FitParams>(STORE_KEY, { ctx: 8192, parallel: 1, kv_type: "f16" }));
const sort = reactive(stored(SORT_KEY, { key: "size", desc: true }));
const target = ref<string>(stored(TARGET_KEY, { id: "auto" }).id);
watch(target, (id) => store(TARGET_KEY, { id }));
watch(sort, () => store(SORT_KEY, sort));

const models = ref<ModelsResponse | null>(null);
const error = ref<string | null>(null);
const fits = reactive<Record<string, FitResponse | { error: string } | undefined>>({});
const open = ref<Record<string, boolean>>({});
const openCmd = ref<Record<string, boolean>>({});
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
  store(STORE_KEY, params);
  window.clearTimeout(timer);
  timer = window.setTimeout(computeFits, 350);
});

// --- lanzados desde Arena (para parar y enseñar el registro mientras cargan)
const launched = ref<LaunchedServer[]>([]);
async function loadLaunched() {
  try {
    const r = await api<LaunchedResponse>(`/api/hosts/${props.hostId}/launched`);
    launched.value = r.launched;
  } catch {
    /* un agente antiguo no tiene esta función: solo se oculta el estado */
  }
}
let poll: number | undefined;

onMounted(async () => {
  poll = window.setInterval(loadLaunched, 3000);
  loadLaunched();
  await loadModels();
  await computeFits();
});
onBeforeUnmount(() => {
  window.clearInterval(poll);
  window.clearTimeout(timer);
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
const VERDICT_RANK: Record<string, number> = { gpu: 0, split: 1, ram: 2, cpu: 3, no: 4, unknown: 5 };

/** Etiqueta con nombres cortos de GPU ("RTX 3060" en vez de "NVIDIA GeForce RTX 3060"). */
function verdictLabel(r: FitResponse): string {
  const fitting = r.fit.gpus.filter((g) => g.fits);
  if (r.fit.verdict === "gpu" && fitting.length) return `Cabe en ${fitting.map((g) => shortName(g.name)).join(" · ")}`;
  return r.fit.label ?? NO_DATA;
}

function ok(r: FitResponse | { error: string } | undefined): FitResponse | null {
  return r && "fit" in r ? r : null;
}

/** Barra: la GPU destino (o donde cabe, o la de más memoria libre); sólido = VRAM, rayado = lo que se va a RAM. */
function bar(r: FitResponse) {
  const gs = r.fit.gpus.filter((g) => isNum(g.free));
  if (!gs.length || !isNum(r.fit.need_full_gpu)) return null;
  const g =
    gs.find((x) => x.device_id === target.value) ??
    gs.find((x) => x.fits) ??
    gs.reduce((a, b) => ((b.free ?? 0) > (a.free ?? 0) ? b : a));
  const free = g.free as number;
  const need = r.fit.need_full_gpu as number;
  return {
    name: shortName(g.name),
    used: Math.min(need, free) / 1024 ** 2,
    total: free / 1024 ** 2,
    overflow: need > free ? (need - free) / 1024 ** 2 : null,
  };
}

// --- GPU destino
const host = computed(() => live.hosts[props.hostId] ?? null);
const gpuList = computed(() => gpus(host.value));
const snap = computed(() => live.metrics[props.hostId] ?? null);
const targetGpu = computed(() => gpuList.value.find((g) => g.device_id === target.value) ?? null);
watch(gpuList, (list) => {
  if (target.value !== "auto" && list.length && !list.some((g) => g.device_id === target.value)) target.value = "auto";
});
function freeGib(id: string): number | null {
  const s = gpuSample(snap.value, id);
  return isNum(s?.mem_total_mib) && isNum(s?.mem_used_mib) ? (s.mem_total_mib - s.mem_used_mib) / 1024 : null;
}

/** Opción de arranque que corresponde a la GPU destino (o la recomendada con "Automático"). */
function optionFor(r: FitResponse | null): { opt: LaunchOption | null; why: string | null } {
  const c = r?.command;
  if (!c) return { opt: null, why: "Sin datos" };
  if (!c.available) return { opt: null, why: c.reason };
  if (target.value === "auto") return { opt: c.options[0] ?? null, why: null };
  const opt = c.options.find((o) => o.device_id === target.value) ?? null;
  return opt ? { opt, why: null } : { opt: null, why: `No cabe entero en ${shortName(targetGpu.value?.name)}` };
}

// --- estado de ejecución de cada modelo
const samePath = (a: string, b: string) => a.replace(/\\/g, "/").toLowerCase() === b.replace(/\\/g, "/").toLowerCase();
function runOf(f: ModelFile) {
  const ep = (live.endpoints[props.hostId] ?? []).find(
    (e) => e.status !== "detenido" && (e.snapshot?.model_file === f.file || (e.snapshot?.model_path && samePath(e.snapshot.model_path, f.path))),
  );
  const port = ep ? Number(new URL(ep.base_url).port) || null : null;
  const mine = launched.value.find((l) => l.alive && samePath(l.model, f.path)) ?? null;
  return { ep: ep ?? null, port: port ?? mine?.port ?? null, mine };
}
/** Aviso si el contexto por slot elegido supera el de entrenamiento del modelo. */
function ctxWarning(r: { model: { context_length: number | null } }): string | null {
  const train = r.model.context_length;
  const perSlot = Math.floor(params.ctx / Math.max(params.parallel, 1));
  if (!isNum(train) || train <= 0 || perSlot <= train) return null;
  return `El contexto por slot (${fmt(perSlot)}) supera el de entrenamiento (${fmt(train)}): la calidad puede caer.`;
}
const busy = reactive<Record<string, boolean>>({});
const launchError = reactive<Record<string, string | undefined>>({});

async function act(f: ModelFile, path: string, body: object) {
  busy[f.path] = true;
  launchError[f.path] = undefined;
  try {
    await api(`/api/hosts/${props.hostId}${path}`, { method: "POST", body: JSON.stringify(body) });
    await loadLaunched();
  } catch (e) {
    launchError[f.path] = (e as Error).message;
  } finally {
    busy[f.path] = false;
  }
}
const launchModel = (f: ModelFile, opt: LaunchOption) =>
  act(f, "/launch", { path: f.path, option: opt.id, ctx: params.ctx, parallel: params.parallel, kv_type: params.kv_type });
const stopModel = (f: ModelFile, pid: number) => act(f, "/launch/stop", { pid });

// --- recomendados para este hardware (ESTIMADO): los que caben enteros en GPU con más parámetros efectivos
const recs = computed(() =>
  recommend(
    files.value.map((f) => ({ path: f.path, r: ok(fits[f.path]) })),
    target.value,
    Math.floor(params.ctx / Math.max(params.parallel, 1)),
    shortName,
  ),
);

// --- orden
const SORTS = [
  { key: "rec", label: "Recomendado" },
  { key: "size", label: "Tamaño" },
  { key: "params", label: "Parámetros (B)" },
  { key: "name", label: "Nombre" },
  { key: "fit", label: "Encaje" },
];

const rows = computed(() => {
  const list = files.value.map((f) => {
    const raw = fits[f.path];
    const r = ok(raw);
    return { f, r, err: raw && "error" in raw ? raw.error : null, b: r ? bar(r) : null, size: partsSize(f) };
  });
  const dir = sort.desc ? -1 : 1;
  const name = (x: (typeof list)[number]) => (x.r?.model.name ?? x.f.file).toLowerCase();
  const num = (v: number | null | undefined) => (isNum(v) && v > 0 ? v : null);
  list.sort((a, b) => {
    let c = 0;
    if (sort.key === "rec") {
      c = (recs.value.get(a.f.path)?.rank ?? 99) - (recs.value.get(b.f.path)?.rank ?? 99);
      if (c === 0) c = (b.r?.model.n_params ?? 0) - (a.r?.model.n_params ?? 0);
      return sort.desc ? c : -c;
    }
    if (sort.key === "name") c = name(a).localeCompare(name(b));
    else if (sort.key === "params") {
      const x = num(a.r?.model.n_params);
      const y = num(b.r?.model.n_params);
      if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1; // sin dato, siempre al final
      c = x - y;
    } else if (sort.key === "fit") {
      c = (VERDICT_RANK[a.r?.fit.verdict ?? "unknown"] ?? 9) - (VERDICT_RANK[b.r?.fit.verdict ?? "unknown"] ?? 9);
      if (c === 0) c = b.size - a.size; // dentro del mismo encaje, los mayores primero
      return sort.desc ? -c : c;
    } else c = a.size - b.size;
    return c * dir || name(a).localeCompare(name(b));
  });
  return list;
});

function paramsB(n: number | null | undefined): { v: string; u: string } | null {
  if (!isNum(n) || n <= 0) return null;
  return n >= 1e9 ? { v: fmt(n / 1e9, 1), u: "B" } : { v: fmt(n / 1e6, 0), u: "M" };
}
function ctxK(n: number | null | undefined): string {
  return isNum(n) ? (n >= 1024 ? `${fmt(n / 1024, 0)}k` : fmt(n)) : NO_DATA;
}
function elapsed(l: LaunchedServer): string {
  const s = Math.max(0, Math.round(now.value - l.started_at));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}
</script>

<template>
  <div class="gguf">
    <!-- GPU destino: cada modelo se lanza directamente en la elegida -->
    <section class="targets" aria-label="GPU destino">
      <span class="label">Lanzar en</span>
      <div class="chips" role="radiogroup" aria-label="GPU destino">
        <button
          type="button"
          role="radio"
          class="chip"
          :class="{ 'chip--on': target === 'auto' }"
          :aria-checked="target === 'auto'"
          @click="target = 'auto'"
        >
          <span class="chip__name">Automático</span>
          <span class="chip__sub">la recomendada</span>
        </button>
        <button
          v-for="g in gpuList"
          :key="g.device_id"
          type="button"
          role="radio"
          class="chip"
          :class="{ 'chip--on': target === g.device_id }"
          :style="{ '--c': deviceColor(g) }"
          :aria-checked="target === g.device_id"
          @click="target = g.device_id"
        >
          <span class="chip__name"><span class="dot" aria-hidden="true" />{{ shortName(g.name) }}</span>
          <span class="chip__sub num2">{{ isNum(freeGib(g.device_id)) ? fmt(freeGib(g.device_id), 1, "GiB libres") : "sin datos" }}</span>
        </button>
      </div>
    </section>

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
      <label>
        <span class="label">Ordenar por</span>
        <span class="sortbox">
          <select v-model="sort.key">
            <option v-for="s in SORTS" :key="s.key" :value="s.key">{{ s.label }}</option>
          </select>
          <button
            class="btn sortdir"
            type="button"
            :aria-label="sort.desc ? 'Orden descendente: cambiar a ascendente' : 'Orden ascendente: cambiar a descendente'"
            :title="sort.desc ? 'De mayor a menor' : 'De menor a mayor'"
            @click="sort.desc = !sort.desc"
          >
            {{ sort.desc ? "↓ Mayor primero" : "↑ Menor primero" }}
          </button>
        </span>
      </label>
      <button class="btn" type="button" :disabled="loading" @click="computeFits">{{ loading ? "Calculando…" : "Recalcular encaje" }}</button>
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
      <li v-for="{ f, r, err, b, size } in rows" :key="f.path" class="row" :class="{ 'row--on': runOf(f).ep, 'row--rec': recs.get(f.path)?.rank === 1 }">
        <template v-if="r">
          <header class="head">
            <h4 class="title">{{ r!.model.name ?? f.file }}</h4>
            <span v-if="recs.get(f.path)" class="tag tag--rec" :title="recs.get(f.path)!.reason">
              <span aria-hidden="true">★</span>
              {{ recs.get(f.path)!.rank === 1 ? "Mejor para tu hardware" : "Recomendado" }}
            </span>
            <span class="tag">{{ r!.model.architecture ?? "?" }}</span>
            <span v-if="r!.estimate.kind === 'mmproj'" class="tag">proyector</span>
            <span v-if="(r!.estimate.recurrent ?? 0) > 0" class="tag">híbrido</span>
            <span v-if="r!.model.expert_count" class="tag">MoE</span>
            <span v-if="f.split_total" class="tag">{{ f.split_total }} partes</span>
            <span v-if="runOf(f).ep" class="state state--on">
              <span aria-hidden="true">●</span> {{ runOf(f).ep!.status === "listo" ? "en marcha" : runOf(f).ep!.status }}
              <template v-if="runOf(f).port"> · :{{ runOf(f).port }}</template>
            </span>
            <span v-else-if="runOf(f).mine" class="state state--wait"><span aria-hidden="true">◌</span> arrancando · {{ elapsed(runOf(f).mine!) }}</span>
          </header>

          <dl class="stats">
            <div>
              <dt>Parámetros</dt>
              <dd class="num">
                <template v-if="paramsB(r!.model.n_params)">{{ paramsB(r!.model.n_params)!.v }}<span class="unit">{{ paramsB(r!.model.n_params)!.u }}</span></template>
                <template v-else><span class="nodata">sin datos</span></template>
              </dd>
            </div>
            <div>
              <dt>Cuantización</dt>
              <dd class="num">{{ r!.model.file_type ?? NO_DATA }}</dd>
            </div>
            <div>
              <dt>Tamaño</dt>
              <dd class="num">{{ fmt(size / GIB, 1) }}<span class="unit">GiB</span></dd>
            </div>
            <div>
              <dt>Contexto máx.</dt>
              <dd class="num">{{ ctxK(r!.model.context_length) }}</dd>
            </div>
            <div v-if="r!.estimate.n_layers">
              <dt>Capas</dt>
              <dd class="num">{{ r!.estimate.n_layers }}</dd>
            </div>
          </dl>

          <div v-if="r!.estimate.kind === 'model'" class="fit">
            <span class="verdict" :class="`verdict--${VERDICT[r!.fit.verdict]?.cls ?? 'dim'}`">
              <span aria-hidden="true">{{ VERDICT[r!.fit.verdict]?.icon }}</span> {{ verdictLabel(r!) }}
            </span>
            <div v-if="b" class="barbox">
              <BarWithOverflow v-bind="b!" :label="`Encaje en ${b!.name}`" :dimension="false" />
              <span class="dim fitnote">necesita {{ gb(r!.fit.need_full_gpu) }} · libre en {{ b!.name }}</span>
            </div>
          </div>
          <p v-else class="dim fit">{{ r!.estimate.notes[0] }}</p>
          <p v-if="ctxWarning(r!)" class="ctxwarn" role="note">▲ {{ ctxWarning(r!) }}</p>

          <div v-if="r!.estimate.kind === 'model'" class="actions">
            <template v-if="runOf(f).mine || runOf(f).ep">
              <button
                v-if="runOf(f).mine"
                class="btn btn--lg btn--stop"
                type="button"
                :disabled="busy[f.path]"
                @click="stopModel(f, runOf(f).mine!.pid)"
              >
                {{ busy[f.path] ? "Parando…" : "Parar" }}
              </button>
              <span v-else class="dim hint">Lanzado fuera de Arena: ciérralo donde lo abriste.</span>
            </template>
            <template v-else>
              <button
                class="btn btn--primary btn--lg"
                type="button"
                :disabled="busy[f.path] || !optionFor(r).opt"
                :title="optionFor(r).why ?? optionFor(r).opt?.label"
                @click="launchModel(f, optionFor(r).opt!)"
              >
                {{ busy[f.path] ? "Lanzando…" : target === "auto" ? "Lanzar" : `Lanzar en ${shortName(targetGpu?.name)}` }}
              </button>
              <span v-if="optionFor(r).why" class="dim hint">{{ optionFor(r).why }}</span>
              <span v-else-if="target === 'auto' && optionFor(r).opt" class="dim hint">{{ optionFor(r).opt!.label }}</span>
            </template>
            <button class="btn" type="button" :aria-expanded="!!open[f.path]" @click="open[f.path] = !open[f.path]">
              {{ open[f.path] ? "Ocultar" : "Ver" }} desglose
            </button>
            <button
              v-if="r!.command"
              class="btn"
              type="button"
              :aria-expanded="!!openCmd[f.path]"
              @click="openCmd[f.path] = !openCmd[f.path]"
            >
              {{ openCmd[f.path] ? "Ocultar" : "Copiar" }} comando
            </button>
          </div>
          <p v-if="launchError[f.path]" class="error" role="alert">▲ {{ launchError[f.path] }}</p>
          <pre v-if="runOf(f).mine && !runOf(f).ep" class="log" aria-label="Registro de llama-server">{{ runOf(f).mine!.log_tail.slice(-4).join("\n") || "esperando la salida de llama-server…" }}</pre>

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
          <LaunchCommand v-if="openCmd[f.path] && r!.command" :command="r!.command" />
          <p class="file dim">{{ f.path }}</p>
        </template>

        <template v-else>
          <header class="head"><h4 class="title">{{ f.file }}</h4></header>
          <p class="dim">{{ err ?? "Leyendo cabecera…" }}</p>
          <p class="file dim">{{ f.path }}</p>
        </template>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.targets {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.targets > .label {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
}
.chips {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
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
  transition: background 0.15s, border-color 0.15s;
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
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--c);
}
.chip__sub {
  font-size: 12px;
  color: var(--ink-faint);
}
.num2 {
  font-variant-numeric: tabular-nums;
}
.controls {
  display: flex;
  align-items: flex-end;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.controls label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.controls input {
  width: 80px;
}
.controls input,
.controls select,
.sortdir {
  height: 34px;
  box-sizing: border-box;
}
.sortbox {
  display: flex;
  gap: 6px;
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.row {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: var(--panel);
  border: 1.5px solid transparent;
  border-radius: var(--radius);
  padding: 20px 24px;
}
.row--on {
  border-color: color-mix(in srgb, var(--ok) 55%, transparent);
}
.row--rec:not(.row--on) {
  border-color: color-mix(in srgb, var(--ok) 28%, transparent);
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.title {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.01em;
  margin: 0 4px 0 0;
  overflow-wrap: anywhere;
}
.tag {
  font-size: 12px;
  font-weight: 500;
  padding: 1px 10px;
  border-radius: 999px;
  background: var(--panel-raised);
  color: var(--ink-dim);
}
.tag--rec {
  font-weight: 600;
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 14%, transparent);
  cursor: help;
}
.state {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
  padding: 3px 12px;
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
}
.state--on {
  color: var(--ok);
  background: color-mix(in srgb, var(--ok) 14%, transparent);
}
.state--wait {
  color: var(--warn);
  background: color-mix(in srgb, var(--warn) 14%, transparent);
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 14px 24px;
  margin: 0;
}
.stats dt {
  font-size: 12px;
  color: var(--ink-dim);
  margin-bottom: 2px;
}
.stats dd {
  margin: 0;
  font-size: 30px;
  white-space: nowrap;
}
.nodata {
  font-size: 15px;
  font-weight: 500;
  color: var(--ink-faint);
}
.fit {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  margin: 0;
}
.ctxwarn {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--warn);
}
.verdict {
  font-size: 15px;
  font-weight: 600;
  padding: 4px 14px;
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
.barbox {
  flex: 1;
  min-width: 220px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.barbox :deep(.bwo__track) {
  height: 12px;
}
.fitnote {
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.hint {
  font-size: 13px;
}
.btn--stop {
  background: color-mix(in srgb, var(--crit) 20%, transparent);
  color: var(--crit);
}
.error {
  margin: 0;
  color: var(--warn);
  font-size: 13px;
}
.log {
  margin: 0;
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg);
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink-dim);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.file {
  margin: 0;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.detail {
  border-top: 1px solid var(--line);
  padding-top: 12px;
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
  font-size: 13px;
}
.kv div {
  display: grid;
  grid-template-columns: 150px 1fr;
  gap: 10px;
  padding: 3px 0;
  border-bottom: 1px solid var(--line);
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
  font-size: 13px;
  color: var(--ink-dim);
}
.empty {
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  padding: 14px;
}
.dim {
  color: var(--ink-faint);
}
code {
  font-family: var(--font-mono);
}
</style>
