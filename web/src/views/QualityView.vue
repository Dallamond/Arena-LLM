<script setup lang="ts">
// Lanzar pruebas: elegir servidor detectado, suite y parámetros.
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, hostList, live } from "../api/live";
import type { Endpoint, Suite } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import Stamp from "../components/Stamp.vue";
import { fmt, fmtDuration } from "../lib/format";

const route = useRoute();
const router = useRouter();
const suites = ref<Suite[]>([]);
const error = ref<string | null>(null);
const busy = ref(false);

const endpoints = computed<(Endpoint & { hostName: string })[]>(() =>
  hostList.value.flatMap((h) => (live.endpoints[h.id] ?? []).map((e) => ({ ...e, hostName: h.name }))),
);
const ready = computed(() => endpoints.value.filter((e) => e.status === "listo"));
const endpointId = ref<number | null>(null);
const selected = computed(() => endpoints.value.find((e) => e.id === endpointId.value) ?? null);
const busyEndpoint = computed(() =>
  Object.values(live.runs).find((r) => r.endpoint_id === endpointId.value && (r.status === "running" || r.status === "pending")),
);

watch(
  ready,
  (list) => {
    const fromQuery = Number(route.query.endpoint);
    if (endpointId.value === null || !list.some((e) => e.id === endpointId.value)) {
      endpointId.value = list.find((e) => e.id === fromQuery)?.id ?? list[0]?.id ?? null;
    }
  },
  { immediate: true },
);

// Formularios (valores por defecto de cada suite)
const stress = reactive({ duration_s: 120, parallel: 1, max_tokens: 512, baseline_s: 10, cooldown_s: 30, label: "" });
const free = reactive({ prompts: "", repeats: 1, max_tokens: 512, baseline_s: 5, label: "" });
const adv = reactive({ temperature: 0, seed: 42, top_k: "", top_p: "", min_p: "", cache_prompt: false, system: "", extra: "{}" });
const showAdv = ref(false);

onMounted(async () => {
  try {
    suites.value = await api<Suite[]>("/api/suites");
    const s = suites.value.find((x) => x.id === "estres")?.defaults ?? {};
    Object.assign(stress, {
      duration_s: s.duration_s ?? stress.duration_s,
      parallel: s.parallel ?? stress.parallel,
      max_tokens: s.max_tokens ?? stress.max_tokens,
      baseline_s: s.baseline_s ?? stress.baseline_s,
      cooldown_s: s.cooldown_s ?? stress.cooldown_s,
    });
    const f = suites.value.find((x) => x.id === "libre")?.defaults ?? {};
    free.prompts = ((f.prompts as string[]) ?? []).join("\n---\n");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
});

function advParams(): Record<string, unknown> {
  const out: Record<string, unknown> = {
    temperature: Number(adv.temperature),
    seed: Number(adv.seed),
    cache_prompt: adv.cache_prompt,
    system: adv.system,
  };
  for (const k of ["top_k", "top_p", "min_p"] as const) if (adv[k] !== "") out[k] = Number(adv[k]);
  const extra = JSON.parse(adv.extra || "{}");
  if (typeof extra !== "object" || Array.isArray(extra) || extra === null) throw new Error("'extra' debe ser un objeto JSON");
  out.extra = extra;
  return out;
}

async function launch(suite: "estres" | "libre") {
  if (endpointId.value === null) return;
  error.value = null;
  busy.value = true;
  try {
    const base = advParams();
    const params =
      suite === "estres"
        ? { ...base, duration_s: stress.duration_s, parallel: stress.parallel, max_tokens: stress.max_tokens, baseline_s: stress.baseline_s, cooldown_s: stress.cooldown_s }
        : {
            ...base,
            prompts: free.prompts.split(/^\s*---\s*$/m).map((p) => p.trim()).filter(Boolean),
            repeats: free.repeats,
            max_tokens: free.max_tokens,
            baseline_s: free.baseline_s,
            cooldown_s: 0,
          };
    const label = suite === "estres" ? stress.label : free.label;
    const run = await api<{ id: number }>("/api/runs", {
      method: "POST",
      body: JSON.stringify({ suite, endpoint_id: endpointId.value, label: label || null, params }),
    });
    router.push(`/pruebas/${run.id}`);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

const stressTotal = computed(() => Number(stress.baseline_s) + Number(stress.duration_s) + Number(stress.cooldown_s));
</script>

<template>
  <div class="page">
    <h2 class="title">Calidad y estrés</h2>

    <!-- Servidor objetivo -->
    <BlueprintCard fig="FIG.40" title="Servidor a probar">
      <div v-if="!endpoints.length" class="empty">
        <p>Ningún servidor detectado.</p>
        <p class="mono dim">Lanza <code>llama-server</code> como siempre; aparecerá aquí en unos segundos.</p>
      </div>
      <div v-else class="targets">
        <label v-for="e in endpoints" :key="e.id" class="target" :class="{ 'target--off': e.status !== 'listo', 'target--on': e.id === endpointId }">
          <input v-model="endpointId" type="radio" name="endpoint" :value="e.id" :disabled="e.status !== 'listo'" />
          <span class="mono target__text">
            <b>{{ e.alias || e.snapshot?.model_file || e.base_url }}</b>
            <span class="dim"> · {{ e.base_url }} · {{ e.hostName }}</span><br />
            <span class="dim small">
              {{ e.snapshot?.derived?.model_ftype ?? "" }} · ctx {{ fmt(e.snapshot?.derived?.n_ctx_slot) }} × {{ fmt(e.snapshot?.derived?.total_slots) }} slots ·
              -ngl {{ e.snapshot?.flags?.ngl ?? "?" }}
            </span>
          </span>
          <Stamp :text="e.status" :tone="e.status === 'listo' ? 'info' : e.status === 'cargando' ? 'warn' : 'dim'" />
        </label>
      </div>
      <p v-if="busyEndpoint" class="warn mono small">
        ▲ Ya hay una prueba en marcha en este servidor:
        <RouterLink :to="`/pruebas/${busyEndpoint.id}`">run #{{ busyEndpoint.id }}</RouterLink>
      </p>
    </BlueprintCard>

    <p v-if="error" class="error mono" role="alert">✕ {{ error }}</p>

    <div class="cards">
      <!-- Estrés -->
      <BlueprintCard fig="FIG.41" title="Estrés GPU/VRAM">
        <p class="desc">Peticiones largas en bucle durante el tiempo elegido. Mide t/s a lo largo del tiempo, temperatura, potencia, reloj, throttling, degradación y energía. Aborta solo si una GPU llega a su umbral crítico.</p>
        <div class="form">
          <label><span class="label">duración (s)</span><input v-model.number="stress.duration_s" type="number" min="5" max="7200" /></label>
          <label><span class="label">peticiones en paralelo</span><input v-model.number="stress.parallel" type="number" min="1" max="64" /></label>
          <label><span class="label">tokens por petición</span><input v-model.number="stress.max_tokens" type="number" min="16" max="131072" /></label>
          <label><span class="label">reposo antes (s)</span><input v-model.number="stress.baseline_s" type="number" min="0" max="600" /></label>
          <label><span class="label">enfriamiento (s)</span><input v-model.number="stress.cooldown_s" type="number" min="0" max="1800" /></label>
          <label class="wide"><span class="label">etiqueta (opcional)</span><input v-model="stress.label" type="text" maxlength="80" placeholder="p. ej. 3060 · Qwen 7B · ventilador al 100 %" /></label>
        </div>
        <p class="mono dim small">
          Total ≈ {{ fmtDuration(stressTotal) }}.
          <span v-if="selected && stress.parallel > (selected.snapshot?.derived?.total_slots ?? 1)" class="warn">
            ▲ El servidor tiene {{ selected.snapshot?.derived?.total_slots }} slots: con más peticiones en paralelo, las demás esperan en cola.
          </span>
        </p>
        <button class="btn btn--primary" type="button" :disabled="busy || !endpointId || !!busyEndpoint" @click="launch('estres')">
          ▶ Lanzar estrés
        </button>
      </BlueprintCard>

      <!-- Libre -->
      <BlueprintCard fig="FIG.42" title="Prompt libre">
        <p class="desc">Uno o varios prompts propios, separados por una línea con <code>---</code>. Mide TTFT, t/s y tokens, y guarda prompt y respuesta.</p>
        <div class="form">
          <label class="wide"><span class="label">prompts</span><textarea v-model="free.prompts" rows="6" /></label>
          <label><span class="label">repeticiones</span><input v-model.number="free.repeats" type="number" min="1" max="100" /></label>
          <label><span class="label">tokens máximos</span><input v-model.number="free.max_tokens" type="number" min="1" max="131072" /></label>
          <label><span class="label">reposo antes (s)</span><input v-model.number="free.baseline_s" type="number" min="0" max="600" /></label>
          <label class="wide"><span class="label">etiqueta (opcional)</span><input v-model="free.label" type="text" maxlength="80" /></label>
        </div>
        <button class="btn btn--primary" type="button" :disabled="busy || !endpointId || !!busyEndpoint" @click="launch('libre')">
          ▶ Lanzar prompt libre
        </button>
      </BlueprintCard>
    </div>

    <!-- Parámetros comunes -->
    <BlueprintCard fig="FIG.43" title="Parámetros de generación (comunes)" class="gap">
      <template #actions>
        <button class="btn" type="button" :aria-expanded="showAdv" @click="showAdv = !showAdv">{{ showAdv ? "Ocultar" : "Mostrar" }}</button>
      </template>
      <p class="mono dim small">
        Perfil estándar: temperatura {{ adv.temperature }}, semilla {{ adv.seed }}, caché de prompt {{ adv.cache_prompt ? "activada" : "desactivada" }}.
        Cambiarlos hace que el run no sea comparable con otros del perfil estándar.
      </p>
      <div v-if="showAdv" class="form">
        <label><span class="label">temperatura</span><input v-model.number="adv.temperature" type="number" step="0.05" min="0" max="2" /></label>
        <label><span class="label">semilla</span><input v-model.number="adv.seed" type="number" /></label>
        <label><span class="label">top_k</span><input v-model="adv.top_k" type="number" placeholder="del servidor" /></label>
        <label><span class="label">top_p</span><input v-model="adv.top_p" type="number" step="0.01" placeholder="del servidor" /></label>
        <label><span class="label">min_p</span><input v-model="adv.min_p" type="number" step="0.01" placeholder="del servidor" /></label>
        <label class="check"><input v-model="adv.cache_prompt" type="checkbox" /> <span>caché de prompt</span></label>
        <label class="wide"><span class="label">prompt de sistema</span><textarea v-model="adv.system" rows="2" /></label>
        <label class="wide"><span class="label">extra (JSON que se envía tal cual)</span><textarea v-model="adv.extra" rows="2" class="mono" /></label>
      </div>
    </BlueprintCard>

    <!-- Próximas -->
    <BlueprintCard fig="FIG.44" title="Próximas pruebas" class="gap">
      <div class="todo">
        <Stamp text="llega en F7" tone="dim" />
        <p class="mono dim">Razonamiento (12 preguntas) · Código con ejecución aislada · Contexto largo (aguja en pajar) · Concurrencia</p>
      </div>
    </BlueprintCard>
  </div>
</template>

<style scoped>
.title {
  font-size: 18px;
  margin-bottom: 14px;
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
  margin: 14px 0 0;
}
.gap {
  margin-top: 18px;
}
.empty {
  border: 1px dashed var(--line-strong);
  padding: 18px;
}
.empty p {
  margin: 0 0 6px;
}
.targets {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.target {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  cursor: pointer;
  font-size: 12px;
}
.target--on {
  border-color: var(--accent);
  background: rgba(108, 180, 255, 0.06);
}
.target--off {
  opacity: 0.6;
  cursor: not-allowed;
}
.target__text {
  flex: 1;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: 18px;
  margin-top: 18px;
}
.desc {
  margin: 0 0 12px;
  color: var(--ink-dim);
  font-size: 13px;
}
.form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
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
.form .check {
  flex-direction: row;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
input[type="number"],
input[type="text"],
textarea {
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 5px 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink);
}
textarea {
  resize: vertical;
}
.todo {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.todo p {
  margin: 0;
}
code {
  font-family: var(--font-mono);
}
</style>
