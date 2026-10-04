import { createRouter, createWebHistory } from "vue-router";
import BattleSetupView from "./views/BattleSetupView.vue";
import BattleView from "./views/BattleView.vue";
import BenchView from "./views/BenchView.vue";
import CompareView from "./views/CompareView.vue";
import HistoryView from "./views/HistoryView.vue";
import PanelView from "./views/PanelView.vue";
import PlaceholderView from "./views/PlaceholderView.vue";
import QualityView from "./views/QualityView.vue";
import RunView from "./views/RunView.vue";
import ServersView from "./views/ServersView.vue";
import SettingsView from "./views/SettingsView.vue";

export interface NavItem {
  path: string;
  label: string;
  icon: string;
  phase?: string; // fase de la hoja de ruta en la que llega la pantalla (si aún no está)
  summary?: string;
}

export const NAV: NavItem[] = [
  { path: "/", label: "Panel", icon: "panel" },
  { path: "/servidores", label: "Servidores", icon: "servers" },
  { path: "/calidad", label: "Calidad", icon: "quality" },
  { path: "/rendimiento", label: "Rendimiento", icon: "perf" },
  { path: "/batalla", label: "Batalla", icon: "battle" },
  { path: "/historial", label: "Historial", icon: "history" },
  { path: "/comparar", label: "Comparar", icon: "compare" },
  { path: "/ajustes", label: "Ajustes", icon: "settings" },
];

const placeholders = NAV.filter((n) => n.phase).map((n) => ({
  path: n.path,
  component: PlaceholderView,
  props: { item: n },
  meta: { title: n.label },
}));

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: PanelView, meta: { title: "Panel" } },
    { path: "/servidores", component: ServersView, meta: { title: "Servidores" } },
    { path: "/calidad", component: QualityView, meta: { title: "Calidad" } },
    { path: "/rendimiento", component: BenchView, meta: { title: "Rendimiento" } },
    { path: "/batalla", component: BattleSetupView, meta: { title: "Batalla" } },
    { path: "/batalla/:id", component: BattleView, props: true, meta: { title: "Batalla" } },
    { path: "/historial", component: HistoryView, meta: { title: "Historial" } },
    { path: "/comparar", component: CompareView, meta: { title: "Comparar" } },
    { path: "/pruebas/:id", component: RunView, props: true, meta: { title: "Prueba" } },
    { path: "/ajustes/:section?", component: SettingsView, meta: { title: "Ajustes" } },
    ...placeholders,
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) ?? "Arena"} · Arena LLM`;
});
