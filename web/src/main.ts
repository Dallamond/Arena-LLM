import { createApp } from "vue";
import "@fontsource/inter/400.css";
import "@fontsource/inter/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/600.css";
import "./styles/tokens.css";
import "./styles/base.css";
import App from "./App.vue";
import { connect } from "./api/live";
import { initAppearance } from "./lib/appearance";
import { router } from "./router";

initAppearance();
connect();
createApp(App).use(router).mount("#app");
