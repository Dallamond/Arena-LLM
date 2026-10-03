import { createRouter, createWebHistory } from "vue-router";
import PanelView from "./views/PanelView.vue";
import PlaceholderView from "./views/PlaceholderView.vue";

export interface NavItem {
  path: string;
  label: string;
  icon: string;
  phase?: string; // fase de la hoja de ruta en la que llega la pantalla
  summary?: string;
}

export const NAV: NavItem[] = [
  { path: "/", label: "Panel", icon: "panel" },
  {
    path: "/servidores",
    label: "Servidores",
    icon: "servers",
    phase: "F3",
    summary: "Servidores llama-server detectados con todos sus flags, GGUF en disco y calculadora de encaje.",
  },
  {
    path: "/rendimiento",
    label: "Rendimiento",
    icon: "perf",
    phase: "F6",
    summary: "llama-bench por componente: solo GPU, solo CPU/RAM, híbrido (curva de la RAM) y reparto entre GPUs.",
  },
  {
    path: "/calidad",
    label: "Calidad",
    icon: "quality",
    phase: "F7",
    summary: "Razonamiento, código con ejecución aislada, contexto largo, concurrencia y estrés.",
  },
  {
    path: "/batalla",
    label: "Batalla",
    icon: "battle",
    phase: "F8",
    summary: "El mismo prompt en dos o más lados con parámetros editables y telemetría por GPU.",
  },
  {
    path: "/historial",
    label: "Historial",
    icon: "history",
    phase: "F9",
    summary: "Todos los runs guardados, filtrables, con etiquetas, notas y paquetes de resultados.",
  },
  {
    path: "/comparar",
    label: "Comparar",
    icon: "compare",
    phase: "F9",
    summary: "Veredictos, gráficas superpuestas, diff de configuración e insignia de comparabilidad.",
  },
  {
    path: "/registros",
    label: "Registros",
    icon: "logs",
    phase: "F4",
    summary: "Eventos del agente y del servidor: cambios de configuración, errores y abortos.",
  },
  {
    path: "/ajustes",
    label: "Ajustes",
    icon: "settings",
    phase: "F3",
    summary: "Equipos, servidores, umbrales por dispositivo, carpeta de modelos, apariencia y datos.",
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: PanelView, meta: { title: "Panel" } },
    ...NAV.filter((n) => n.path !== "/").map((n) => ({
      path: n.path,
      component: PlaceholderView,
      props: { item: n },
      meta: { title: n.label },
    })),
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) ?? "Arena"} · Arena LLM`;
});
