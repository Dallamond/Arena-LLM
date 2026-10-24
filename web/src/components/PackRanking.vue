<script setup lang="ts">
// Ranking acumulado de un paquete de batalla: lo que han sacado los modelos en todas sus batallas
// (solo las de la misma versión del paquete, así los aciertos son comparables).
import { ref, watch } from "vue";
import { api } from "../api/live";
import type { PackRanking } from "../api/types";
import { NO_DATA, fmt } from "../lib/format";

const props = defineProps<{ packId: string }>();
const data = ref<PackRanking | null>(null);
const error = ref<string | null>(null);

watch(
  () => props.packId,
  async (id) => {
    data.value = null;
    error.value = null;
    try {
      const r = await api<PackRanking>(`/api/battle-packs/${encodeURIComponent(id)}/ranking`);
      if (id === props.packId) data.value = r;
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    }
  },
  { immediate: true },
);
</script>

<template>
  <div class="ranking">
    <p v-if="error" class="error mono" role="alert">✕ {{ error }}</p>
    <p v-else-if="!data" class="dim small">Cargando ranking…</p>
    <template v-else>
      <p v-if="!data.rows.length" class="dim small">
        Aún no hay batallas terminadas de este paquete. Cuando las haya, aquí verás qué modelo va primero.
      </p>
      <div v-else class="scroll">
        <table class="tbl mono">
          <thead>
            <tr>
              <th>#</th>
              <th>modelo</th>
              <th>equipo / GPU</th>
              <th v-if="data.by_quality">aciertos (media)</th>
              <th v-if="data.by_quality">mejor</th>
              <th>t/s</th>
              <th>TTFT</th>
              <th>batallas</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in data.rows" :key="`${r.model}|${r.devices}|${r.host}`">
              <td>{{ r.rank }}.º</td>
              <td class="sans">
                {{ r.model }}<span v-if="r.quant" class="dim"> · {{ r.quant }}</span>
              </td>
              <td class="sans dim">{{ r.devices ?? NO_DATA }}</td>
              <td v-if="data.by_quality">{{ fmt(r.accuracy_mean, 0, "%") }}</td>
              <td v-if="data.by_quality">
                {{ r.correct !== null && r.total ? `${r.correct}/${r.total}` : NO_DATA }}
              </td>
              <td>{{ fmt(r.tps, 1) }}</td>
              <td>{{ fmt(r.ttft, 2, "s") }}</td>
              <td>
                <RouterLink :to="`/batalla/${r.last_battle_id}`">{{ r.battles }}</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="dim small note">
        {{ data.battles }} batalla(s) de esta versión del paquete. Los aciertos son absolutos: se pueden comparar entre
        días. {{ data.by_quality ? "" : "Sin corrección automática: se ordena por velocidad." }}
        <template v-if="data.other_versions">
          Hay {{ data.other_versions }} de otra versión del paquete, que no se mezclan.
        </template>
      </p>
    </template>
  </div>
</template>

<style scoped>
.note {
  margin: 8px 0 0;
}
.dim {
  color: var(--ink-faint);
}
.small {
  font-size: 12px;
}
</style>
