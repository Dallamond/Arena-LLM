<script setup lang="ts">
// Iconos de trazo propios (estilo plano técnico). Decorativos: siempre van con texto.
const PATHS: Record<string, string> = {
  panel: "M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z",
  servers: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  perf: "M3 20h18M6 16l4-6 4 3 5-8",
  quality: "M4 12l5 5L20 6",
  battle: "M4 4l7 7M20 4l-7 7M7 17l-3 3M17 17l3 3M9 15l6-6M15 15L9 9",
  history: "M12 7v5l3 2M3 12a9 9 0 1 0 3-6.7M3 4v4h4",
  compare: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  logs: "M5 4h14v16H5zM8 8h8M8 12h8M8 16h5",
  settings: "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1",
  collapse: "M15 6l-6 6 6 6",
  expand: "M9 6l6 6-6 6",
};
defineProps<{ name: string; size?: number }>();
</script>

<template>
  <svg
    :width="size ?? 18"
    :height="size ?? 18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="square"
    aria-hidden="true"
  >
    <path :d="PATHS[name] ?? ''" />
  </svg>
</template>
