<script setup lang="ts">
// Historial de runs: búsqueda, selección para Comparar y enlace a la batalla de cada lado.
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { live, refreshRuns, runList } from "../api/live";
import type { Run } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import Stamp from "../components/Stamp.vue";
import { RUN_STATUS, fmt, fmtDate, fmtDuration, suiteLabel } from "../lib/format";

const MAX_COMPARE = 12;
const router = useRouter();
const text = ref("");
const selected = ref<number[]>([]);
const toggle = (id: number) =>
  (selected.value = selected.value.includes(id) ? selected.value.filter((x) => x !== id) : [...selected.value, id]);
const compare = () => router.push(`/comparar?runs=${[...selected.value].sort((a, b) => a - b).join(",")}`);
onMounted(() => refreshRuns().catch(() => {}));

function endpointName(r: Run): string {
  for (const list of Object.values(live.endpoints)) {
    const e = list.find((x) => x.id === r.endpoint_id);
    if (e) return e.alias || e.snapshot?.model_file || e.base_url;
  }
  // Un bench no tiene servidor: se muestra el GGUF que midió llama-bench
  const model = r.params?.model;
  if (r.kind === "bench" && typeof model === "string") return model.split(/[\\/]/).pop() ?? model;
  return r.endpoint_id ? `servidor #${r.endpoint_id}` : "—";
}

/** t/s de la fila: mediana del cliente; en un bench, la mejor generación (tg) del barrido. */
function tps(r: Run): number | null | undefined {
  return r.kind === "bench" ? r.summary?.bench?.best_tg?.t_s : r.summary?.tps_client.median;
}

function maxTemp(r: Run): number | null {
  const temps = Object.values(r.summary?.devices ?? {})
    .map((d) => d.temp_max_c)
    .filter((t): t is number => typeof t === "number");
  return temps.length ? Math.max(...temps) : null;
}

const rows = computed(() => {
  const q = text.value.trim().toLowerCase();
  return runList.value.filter(
    (r) => !q || `${r.id} ${r.suite} ${r.label ?? ""} ${endpointName(r)} ${r.status}`.toLowerCase().includes(q),
  );
});
</script>

<template>
  <div class="page">
    <div class="head">
      <h2 class="title">Historial</h2>
      <input v-model="text" class="search mono" type="search" placeholder="Buscar (suite, etiqueta, modelo, estado)…" aria-label="Buscar en el historial" />
      <span class="dim small">Marca runs para compararlos (también vale uno solo, para leer sus respuestas).</span>
    </div>
    <BlueprintCard>
      <p v-if="!rows.length" class="dim">Sin runs todavía. Lanza uno desde <RouterLink to="/calidad">Calidad</RouterLink>.</p>
      <div v-else class="scroll"><table class="runs mono">
        <thead>
          <tr>
            <th><span class="sr-only">elegir</span></th>
            <th>#</th>
            <th>fecha</th>
            <th>prueba</th>
            <th>servidor / modelo</th>
            <th>estado</th>
            <th>t/s (mediana)</th>
            <th>tokens</th>
            <th>temp. máx</th>
            <th>energía</th>
            <th>duración</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id" :class="{ sel: selected.includes(r.id) }">
            <td>
              <input
                type="checkbox"
                :checked="selected.includes(r.id)"
                :disabled="r.status === 'running' || (!selected.includes(r.id) && selected.length >= MAX_COMPARE)"
                :aria-label="`Elegir el run #${r.id} para comparar`"
                @change="toggle(r.id)"
              />
            </td>
            <td><RouterLink :to="`/pruebas/${r.id}`">#{{ r.id }}</RouterLink></td>
            <td>{{ fmtDate(r.started_at ?? r.created_at) }}</td>
            <td>
              {{ suiteLabel(r.suite) }}
              <RouterLink v-if="r.battle_id" :to="`/batalla/${r.battle_id}`" class="battle">⚔ #{{ r.battle_id }} · {{ r.side }}</RouterLink>
              <span v-if="r.label" class="dim">· {{ r.label }}</span>
            </td>
            <td>{{ endpointName(r) }}</td>
            <td>
              <Stamp :text="`${RUN_STATUS[r.status]?.icon} ${RUN_STATUS[r.status]?.text ?? r.status}`" :tone="RUN_STATUS[r.status]?.tone ?? 'dim'" :tilt="0" />
            </td>
            <td>{{ fmt(tps(r), 1) }}<span v-if="r.kind === 'bench' && tps(r) != null" class="dim"> tg</span></td>
            <td>{{ r.kind === "bench" ? "—" : fmt(r.summary?.completion_tokens) }}</td>
            <td>{{ fmt(maxTemp(r), 0, "°C") }}</td>
            <td>{{ fmt(r.summary?.energy_wh, 2, "Wh") }}</td>
            <td>{{ fmtDuration(r.finished_at && r.started_at ? r.finished_at - r.started_at : null) }}</td>
          </tr>
        </tbody>
      </table></div>
    </BlueprintCard>

    <!-- Bandeja de comparar -->
    <div v-if="selected.length" class="tray" role="region" aria-label="Runs elegidos para comparar">
      <span class="mono">{{ selected.map((id) => `#${id}`).join(" · ") }}</span>
      <button class="btn" type="button" @click="selected = []">Vaciar</button>
      <button class="btn btn--primary" type="button" @click="compare">{{ selected.length === 1 ? "Ver respuestas" : `Comparar (${selected.length})` }}</button>
    </div>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.title {
  font-size: 20px;
}
.search {
  flex: 1;
  max-width: 420px;
  background: var(--bg);
  border: 1px solid var(--line);
  padding: 5px 8px;
  font-size: 12px;
}
.dim {
  color: var(--ink-faint);
}
.scroll {
  overflow-x: auto;
}
.runs {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.runs th {
  text-align: left;
  font-weight: 400;
  color: var(--ink-faint);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--line);
  padding: 5px 8px;
}
.runs td {
  padding: 6px 8px;
  border-bottom: 1px dotted var(--line);
  white-space: nowrap;
}
.runs tbody tr:hover {
  background: rgba(108, 180, 255, 0.04);
}
.runs tr.sel {
  background: rgba(108, 180, 255, 0.08);
}
.battle {
  margin-left: 6px;
  font-size: 11px;
}
.small {
  font-size: 11px;
}
.tray {
  position: sticky;
  bottom: 12px;
  margin-top: 14px;
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  background: var(--panel);
  border: 1px solid var(--accent);
  padding: 8px 12px;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.35);
}
.tray .mono {
  margin-right: auto;
  font-size: 12px;
  overflow-wrap: anywhere;
}
</style>
