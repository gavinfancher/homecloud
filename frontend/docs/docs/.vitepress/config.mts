import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'docs',
  description: 'Documentation for gavinf.com projects, generated from Markdown.',
  cleanUrls: true,
  appearance: 'force-dark',
  themeConfig: {
    // The gavinf rail (Dashboard/homecloud/proxmox/docs) covers top-level
    // cross-site nav — no separate VitePress top nav needed.
    nav: [],
    // One tree, sections nested under it — not a flat group per section
    // plus a duplicate "Sections" list of the same links.
    sidebar: [
      {
        text: 'Sections',
        items: [
          {
            text: 'Cloudflare',
            link: '/cloudflare/',
            collapsed: false,
            items: [{ text: 'Tunnel & DNS', link: '/cloudflare/tunnel' }],
          },
          { text: 'Infisical', link: '/infisical/' },
          {
            text: 'Proxmox',
            link: '/proxmox/',
            collapsed: false,
            items: [{ text: 'VM status API', link: '/proxmox/vm-status' }],
          },
          {
            text: 'AWS',
            link: '/aws/',
            collapsed: false,
            items: [{ text: 'Backups', link: '/aws/backups' }],
          },
        ],
      },
    ],
    // No "On this page" outline — neither the desktop right rail nor its
    // collapsed mobile "On this page ›" form. `outline: false` alone only
    // empties the heading list; `aside: false` removes the container too.
    outline: false,
    aside: false,
  },
})
