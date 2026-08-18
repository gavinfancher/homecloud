<!--
  gavinf rail — a Vue port of frontend/src/PortalRail.tsx for the docs site
  (VitePress isn't React, so this can't share the component directly; keep
  the two in sync when changing links, icons, or behavior). Toggle state and
  markup mirror the plain-HTML copy in frontend/gavinf-prod/worker.js too.
-->
<script setup lang="ts">
import { onMounted, watch, ref } from 'vue'

const OPEN_KEY = 'portal-rail-open'
const open = ref(false)

watch(open, (o) => document.body.classList.toggle('rail-open', o))

onMounted(() => {
  open.value = localStorage.getItem(OPEN_KEY) === '1'
})

function toggle() {
  open.value = !open.value
  localStorage.setItem(OPEN_KEY, open.value ? '1' : '0')
}
</script>

<template>
  <nav class="portal-rail" :class="{ open }">
    <a class="portal-rail-item portal-rail-brand" href="https://dash.gavinf.com" title="Dashboard">
      <span class="portal-rail-icon portal-rail-mark">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path
            d="M17.5 19a4.5 4.5 0 0 0 .5-8.97A6 6 0 0 0 6.34 9.5 4 4 0 0 0 7 19z"
            stroke="#3b82f6"
            stroke-width="1.75"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </span>
      <span class="portal-rail-label">Dashboard</span>
    </a>
    <div class="portal-rail-sep"></div>
    <a class="portal-rail-item" href="https://homecloud.gavinf.com" title="homecloud">
      <span class="portal-rail-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z" />
        </svg>
      </span>
      <span class="portal-rail-label">homecloud</span>
    </a>
    <a class="portal-rail-item" href="https://proxmox.gavinf.com" title="proxmox">
      <span class="portal-rail-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
      </span>
      <span class="portal-rail-label">proxmox</span>
    </a>
    <a class="portal-rail-item active" href="https://docs.gavinf.com" title="docs">
      <span class="portal-rail-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M9 13h6" />
          <path d="M9 17h6" />
        </svg>
      </span>
      <span class="portal-rail-label">docs</span>
    </a>
    <div class="portal-rail-spacer"></div>
    <button type="button" class="portal-rail-item portal-rail-toggle" :title="open ? 'Collapse' : 'Expand'" @click="toggle">
      <span class="portal-rail-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M9 3v18" />
        </svg>
      </span>
      <span class="portal-rail-label">{{ open ? 'Collapse' : 'Expand' }}</span>
    </button>
  </nav>
</template>
