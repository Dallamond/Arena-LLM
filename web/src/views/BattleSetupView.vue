<script setup lang="ts">
// Configurar una batalla: los mismos prompts contra 2–6 lados (servidores), en paralelo o
// uno detrás de otro. Lo común (prompts, semilla, fases) es igual para todos; cada lado
// solo cambia su muestreo y su prompt de sistema.
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api, hostList, live } from "../api/live";
import type { Battle, Endpoint, Suite } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import PromptPicker from "../components/PromptPicker.vue";
import Stamp from "../components/Stamp.vue";
import { shortName } from "../lib/devices";
import { RUN_STATUS, fmt, fmtDate } from "../lib/format";
import { splitPrompts } from "../lib/library";

const MAX_SIDES = 6;
const router = useRouter();
const error = ref<string | null>(null);
const busy = ref(false);
const battles = ref<Battle[]>([]);

type EP = Endpoint & { hostName: string };
const endpoints = computed<EP[]>(() =>
  hostList.value.flatMap((h) => (live.endpoints[h.id] ?? []).map((e) => ({ ...e, hostName: h.name }))),
);
const ready = computed(() => endpoints.value.filter((e) => e.status === "listo"));
const epById = (id: number | null) => endpoints.value.find((e) => e.id === id) ?? null;

function gpuNames(e: Endpoint | null): string {
  if (!e) return "";
  const devs = live.hosts[e.host_pk]?.devices ?? [];
  const names = (e.snapshot?.devices ?? []).map((d) => shortName(devs.find((x) => x.device_id === d.device_id)?.name ?? d.device_id));
  return names.join(" + ") || "GPU sin asociar";
}
const epName = (e: Endpoint | null) => (e ? e.alias || e.snapshot?.model_file || e.base_url : "—");

// --- lo común ---
const prompts = ref("");
const promptDefaults = ref<string[]>([]);
const common = reactive({ seed: 42, temperature: 0, max_tokens: 512, repeats: 1, baseline_s: 5 });
const mode = ref<"paralelo" | "secuencial">("paralelo");
const label = ref("");

// --- lados ---
interface SideForm {
  endpoint_id: number | null;
  label: string;
  temperature: string;
  max_tokens: string;
  top_k: string;
  top_p: string;
  min_p: string;
  repeat_penalty: string;
  cache_prompt: "" | "si" | "no";
  system: string;
  extra: string;
  advanced: boolean;
}
const blank = (endpoint_id: number | null): SideForm => ({
  endpoint_id,
  label: "",
  temperature: "",
  max_tokens: "",
  top_k: "",
  top_p: "",
  min_p: "",
  repeat_penalty: "",
  cache_prompt: "",
  system: "",
  extra: "",
  advanced: false,
});
const sides = ref<SideForm[]>([]);
const LETTERS = "ABCDEF";

// Los servidores llegan por SSE: los lados se rellenan en cuanto aparecen (sin pisar lo elegido)
watch(
  ready,
  (list) => {
    const ids = list.map((e) => e.id);
    if (!sides.value.length) sides.value = [blank(null), blank(null)];
    sides.value.forEach((s, i) => {
      if (s.endpoint_id === null || !ids.includes(s.endpoint_id)) s.endpoint_id = ids[i] ?? ids[0] ?? null;
    });
  },
  { immediate: true },
);

const dupEndpoints = computed(() => {
  const ids = sides.value.map((s) => s.endpoint_id).filter((x) => x !== null);
  return new Set(ids).size < ids.length;
});

function addSide() {
  const used = new Set(sides.value.map((s) => s.endpoint_id));
  const next = ready.value.find((e) => !used.has(e.id))?.id ?? sides.value[0]?.endpoint_id ?? null;
  sides.value.push(blank(next));
}
function copyFromA(i: number) {
  const a = sides.value[0];
  sides.value[i] = { ...a, endpoint_id: sides.value[i].endpoint_id, label: sides.value[i].label };
}

function sideParams(s: SideForm, letter: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of ["temperature", "max_tokens", "top_k", "top_p", "min_p", "repeat_penalty"] as const) {
    if (s[k].trim() !== "") {
      const n = Number(s[k].replace(",", "."));
      if (!Number.isFinite(n)) throw new Error(`Lado ${letter}: '${k}' debe ser un número`);
      out[k] = k === "max_tokens" || k === "top_k" ? Math.round(n) : n;
    }
  }
  if (s.cache_prompt) out.cache_prompt = s.cache_prompt === "si";
  if (s.system.trim()) out.system = s.system;
  if (s.extra.trim()) {
    const extra = JSON.parse(s.extra);
    if (typeof extra !== "object" || Array.isArray(extra) || extra === null) throw new Error(`Lado ${letter}: 'extra' debe ser un objeto JSON`);
    out.extra = extra;
  }
  return out;
}

const promptList = computed(() => splitPrompts(prompts.value));
const canLaunch = computed(
  () => !busy.value && promptList.value.length > 0 && sides.value.length >= 2 && sides.value.every((s) => s.endpoint_id !== null) && !(mode.value === "paralelo" && dupEndpoints.value),
);

async function launch() {
  error.value = null;
  busy.value = true;
  try {
    const body = {
      mode: mode.value,
      label: label.value || null,
      prompts: promptList.value,
      common: { ...common },
      sides: sides.value.map((s, i) => ({ endpoint_id: s.endpoint_id, label: s.label || null, params: sideParams(s, LETTERS[i]) })),
    };
    const b = await api<Battle>("/api/battles", { method: "POST", body: JSON.stringify(body) });
    router.push(`/batalla/${b.id}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

onMounted(async () => {
  try {
    const suites = await api<Suite[]>("/api/suites");
    const d = suites.find((s) => s.id === "libre")?.defaults ?? {};
    promptDefaults.value = (d.prompts as string[]) ?? [];
    prompts.value = promptDefaults.value.join("\n---\n");
    common.seed = Number(d.seed ?? common.seed);
    common.temperature = Number(d.temperature ?? common.temperature);
    common.max_tokens = Number(d.max_tokens ?? common.max_tokens);
    common.baseline_s = Number(d.baseline_s ?? common.baseline_s);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
  api<Battle[]>("/api/battles?limit=20")
    .then((b) => (battles.value = b))
    .catch(() => {});
});
</script>

<template>
  <div class="page">
    <div class="head">
      <h2 class="title">Batalla</h2>
      <span class="dim small">Los mismos prompts contra varios servidores, con telemetría por GPU y marcador final.</span>
    </div>

    <div v-if="!ready.length" class="empty">
      <p>Hace falta al menos un servidor listo (dos para el modo paralelo).</p>
      <p class="dim">Lanza tus <code>llama-server</code> (en Servidores → GGUF en disco tienes el comando) y aparecerán aquí.</p>
    </div>

    <BlueprintCard title="Prompts (comunes a todos los lados)">
      <PromptPicker v-model="prompts" :defaults="promptDefaults" @max-tokens="(n) => (common.max_tokens = n)" />
      <div class="form">
        <label><span class="label">semilla</span><input v-model.number="common.seed" type="number" /></label>
        <label><span class="label">temperatura</span><input v-model.number="common.temperature" type="number" step="0.05" min="0" max="2" /></label>
        <label><span class="label">tokens máximos</span><input v-model.number="common.max_tokens" type="number" min="1" max="131072" /></label>
        <label><span class="label">repeticiones</span><input v-model.number="common.repeats" type="number" min="1" max="100" /></label>
        <label><span class="label">reposo antes (s)</span><input v-model.number="common.baseline_s" type="number" min="0" max="600" /></label>
      </div>
      <p class="dim small">La semilla, los prompts y las fases son siempre iguales en todos los lados. Temperatura y tokens máximos son el valor por defecto: cada lado puede cambiarlos.</p>
    </BlueprintCard>

    <!-- Lados -->
    <div class="sides">
      <BlueprintCard v-for="(s, i) in sides" :key="i" :title="`Lado ${LETTERS[i]}`">
        <template #actions>
          <button v-if="i > 0" class="btn tiny" type="button" title="Copia los parámetros del lado A" @click="copyFromA(i)">Copiar A →</button>
          <button v-if="sides.length > 2" class="btn tiny" type="button" :aria-label="`Quitar el lado ${LETTERS[i]}`" @click="sides.splice(i, 1)">Quitar</button>
        </template>
        <label class="field">
          <span class="label">servidor</span>
          <select v-model="s.endpoint_id">
            <option :value="null" disabled>elige un servidor…</option>
            <option v-for="e in ready" :key="e.id" :value="e.id">{{ epName(e) }} · {{ e.base_url }} · {{ gpuNames(e) }}</option>
          </select>
        </label>
        <p v-if="epById(s.endpoint_id)" class="dim small mono ep">
          {{ epById(s.endpoint_id)?.snapshot?.derived?.model_ftype ?? "" }} · ctx {{ fmt(epById(s.endpoint_id)?.snapshot?.derived?.n_ctx_slot) }} ×
          {{ fmt(epById(s.endpoint_id)?.snapshot?.derived?.total_slots) }} slots · {{ gpuNames(epById(s.endpoint_id)) }} · {{ epById(s.endpoint_id)?.hostName }}
        </p>
        <div class="form">
          <label><span class="label">temperatura</span><input v-model="s.temperature" type="text" inputmode="decimal" :placeholder="`común (${common.temperature})`" /></label>
          <label><span class="label">tokens máximos</span><input v-model="s.max_tokens" type="text" inputmode="numeric" :placeholder="`común (${common.max_tokens})`" /></label>
          <label class="wide"><span class="label">etiqueta del lado (opcional)</span><input v-model="s.label" type="text" maxlength="60" placeholder="p. ej. Qwen 7B en la 3060" /></label>
        </div>
        <button class="btn tiny" type="button" :aria-expanded="s.advanced" @click="s.advanced = !s.advanced">{{ s.advanced ? "Ocultar" : "Mostrar" }} avanzado</button>
        <div v-if="s.advanced" class="form adv">
          <label><span class="label">top_k</span><input v-model="s.top_k" type="text" placeholder="del servidor" /></label>
          <label><span class="label">top_p</span><input v-model="s.top_p" type="text" placeholder="del servidor" /></label>
          <label><span class="label">min_p</span><input v-model="s.min_p" type="text" placeholder="del servidor" /></label>
          <label><span class="label">repeat_penalty</span><input v-model="s.repeat_penalty" type="text" placeholder="del servidor" /></label>
          <label>
            <span class="label">caché de prompt</span>
            <select v-model="s.cache_prompt">
              <option value="">común (desactivada)</option>
              <option value="si">activada</option>
              <option value="no">desactivada</option>
            </select>
          </label>
          <label class="wide"><span class="label">prompt de sistema</span><textarea v-model="s.system" rows="2" /></label>
          <label class="wide"><span class="label">extra (JSON que se envía tal cual)</span><textarea v-model="s.extra" rows="2" class="mono" placeholder="{}" /></label>
        </div>
      </BlueprintCard>
      <button v-if="sides.length < MAX_SIDES" class="add-side" type="button" @click="addSide">＋ Añadir lado</button>
    </div>

    <BlueprintCard title="Lanzar" class="gap">
      <div class="launch">
        <div class="seg" role="radiogroup" aria-label="Modo">
          <button type="button" role="radio" class="seg__btn" :aria-checked="mode === 'paralelo'" @click="mode = 'paralelo'">⇉ En paralelo</button>
          <button type="button" role="radio" class="seg__btn" :aria-checked="mode === 'secuencial'" @click="mode = 'secuencial'">→ Uno detrás de otro</button>
        </div>
        <label class="field grow"><span class="label">etiqueta de la batalla (opcional)</span><input v-model="label" type="text" maxlength="80" /></label>
        <button class="btn btn--primary" type="button" :disabled="!canLaunch" @click="launch">▶ Lanzar batalla ({{ promptList.length }} prompts × {{ sides.length }} lados)</button>
      </div>
      <p class="dim small">
        <template v-if="mode === 'paralelo'">Todos los lados a la vez: cada uno necesita su propio servidor. Si comparten GPU o equipo, se reparten la máquina y la velocidad baja.</template>
        <template v-else>Un lado detrás de otro: sirve con un solo servidor (p. ej. para variar solo la temperatura) y cada lado tiene la máquina para él solo.</template>
      </p>
      <p v-if="mode === 'paralelo' && dupEndpoints" class="warn small">▲ Hay dos lados con el mismo servidor: en paralelo no se puede. Cambia uno o usa «uno detrás de otro».</p>
      <p v-if="error" class="error mono" role="alert">✕ {{ error }}</p>
    </BlueprintCard>

    <BlueprintCard v-if="battles.length" title="Batallas recientes" class="gap">
      <table class="tbl mono">
        <tbody>
          <tr v-for="b in battles" :key="b.id">
            <td><RouterLink :to="`/batalla/${b.id}`">#{{ b.id }}</RouterLink></td>
            <td>{{ fmtDate(b.created_at) }}</td>
            <td class="sans">{{ b.label ?? "" }}</td>
            <td>{{ b.sides.length }} lados · {{ b.mode }}</td>
            <td><Stamp :text="`${RUN_STATUS[b.status]?.icon} ${RUN_STATUS[b.status]?.text ?? b.status}`" :tone="RUN_STATUS[b.status]?.tone ?? 'dim'" :tilt="0" /></td>
          </tr>
        </tbody>
      </table>
    </BlueprintCard>
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
  margin: 10px 0 0;
}
.gap {
  margin-top: 18px;
}
.empty {
  border: 1px dashed var(--line-strong);
  padding: 14px;
  margin-bottom: 14px;
}
.empty p {
  margin: 0 0 4px;
}
.form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px 14px;
  margin: 12px 0 10px;
}
.form label,
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form .wide {
  grid-column: 1 / -1;
}
.adv {
  border-top: 1px dotted var(--line);
  padding-top: 10px;
}
input[type="number"],
input[type="text"],
textarea,
select {
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 5px 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink);
  min-width: 0;
}
textarea {
  resize: vertical;
}
.sides {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 18px;
  margin-top: 18px;
  align-items: start;
}
.ep {
  margin: 6px 0 0;
}
.add-side {
  border: 1px dashed var(--line-strong);
  background: none;
  color: var(--ink-dim);
  font: inherit;
  font-size: 14px;
  min-height: 120px;
  cursor: pointer;
}
.add-side:hover {
  color: var(--ink);
  border-color: var(--accent);
}
.add-side:focus-visible,
.seg__btn:focus-visible {
  outline: 2px solid var(--accent);
}
.launch {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  margin-bottom: 8px;
}
.grow {
  flex: 1;
  min-width: 200px;
}
.seg {
  display: flex;
  gap: 0;
}
.seg__btn {
  background: none;
  border: 1px solid var(--line);
  color: var(--ink-dim);
  font-family: var(--font-sans);
  font-size: 13px;
  padding: 6px 12px;
  cursor: pointer;
}
.seg__btn[aria-checked="true"] {
  border-color: var(--accent);
  color: var(--ink);
  background: rgba(108, 180, 255, 0.08);
  font-weight: 600;
}
.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.tbl td {
  padding: 4px 8px;
  border-bottom: 1px dotted var(--line);
}
.tbl .sans {
  font-family: var(--font-sans);
}
.btn.tiny {
  padding: 1px 8px;
  font-size: 11px;
}
code {
  font-family: var(--font-mono);
}
</style>
