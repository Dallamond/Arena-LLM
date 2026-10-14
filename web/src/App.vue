<script setup lang="ts">
import DeviceStrip from "./components/DeviceStrip.vue";
import SideNav from "./components/SideNav.vue";
import TopBar from "./components/TopBar.vue";
</script>

<template>
  <a class="skip sr-only" href="#main">Saltar al contenido</a>
  <TopBar />
  <div class="layout">
    <SideNav />
    <div class="content">
      <DeviceStrip v-if="$route.path !== '/'" />
      <main id="main" class="main" tabindex="-1">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  min-height: calc(100vh / var(--zoom) - var(--topbar-h));
}
.content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.main {
  padding: 24px var(--gap) 48px;
  max-width: 1600px;
  width: 100%;
  margin: 0 auto;
  outline: none;
}
.skip:focus {
  position: fixed;
  top: 8px;
  left: 8px;
  width: auto;
  height: auto;
  clip: auto;
  padding: 6px 10px;
  background: var(--panel);
  z-index: 100;
}
</style>
