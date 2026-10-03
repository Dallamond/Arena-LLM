<script setup lang="ts">
// Historial básico de runs (filtros, comparar y exportar llegan en F9).
import { computed, onMounted, ref } from "vue";
import { live, refreshRuns, runList } from "../api/live";
import type { Run } from "../api/types";
import BlueprintCard from "../components/BlueprintCard.vue";
import Stamp from "../components/Stamp.vue";
import { RUN_STATUS, fmt, fmtDate, fmtDuration } from "../lib/format";

const text = ref("");
onMounted(() => refreshRuns().catch(() => {}));

function endpointName(r: Run): string {
  for (const list of Object.values(live.endpoints)) {
    const e = list.find((x) => x.id === r.endpoint_id);
    if (e) return e.alias || e.snapshot?.model_file || e.base_url;
  }
  return r.endpoint_id ? `servidor #${r.endpoint_id}` : "—";
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
      <Stamp text="comparar y exportar: F9" tone="dim" />
    </div>
    <BlueprintCard>
      <p v-if="!rows.length" class="mono dim">Sin runs todavía. Lanza uno desde <RouterLink to="/calidad">Calidad</RouterLink>.</p>
      <div v-else class="scroll"><table class="runs mono">
        <thead>
          <tr>
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
          <tr v-for="r in rows" :key="r.id">
            <td><RouterLink :to="`/pruebas/${r.id}`">#{{ r.id }}</RouterLink></td>
            <td>{{ fmtDate(r.started_at ?? r.created_at) }}</td>
            <td>
              {{ r.suite === "estres" ? "Estrés" : "Libre" }}
              <span v-if="r.label" class="dim">· {{ r.label }}</span>
            </td>
            <td>{{ endpointName(r) }}</td>
            <td>
              <Stamp :text="`${RUN_STATUS[r.status]?.icon} ${RUN_STATUS[r.status]?.text ?? r.status}`" :tone="RUN_STATUS[r.status]?.tone ?? 'dim'" :tilt="0" />
            </td>
            <td>{{ fmt(r.summary?.tps_client.median, 1) }}</td>
            <td>{{ fmt(r.summary?.completion_tokens) }}</td>
            <td>{{ fmt(maxTemp(r), 0, "°C") }}</td>
            <td>{{ fmt(r.summary?.energy_wh, 2, "Wh") }}</td>
            <td>{{ fmtDuration(r.finished_at && r.started_at ? r.finished_at - r.started_at : null) }}</td>
          </tr>
        </tbody>
      </table></div>
    </BlueprintCard>
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
  font-size: 18px;
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
</style>
