// Nuxt layer for the `inventory` module.
//
// Components live under ./components with no folder prefix so cross-layer
// auto-imports resolve, and the locales are declared so @nuxtjs/i18n merges
// the `inventory.*` keys into the host's es/en at build time — same pattern
// as every other module with a screen of its own.
export default defineNuxtConfig({
  components: [
    { path: './components', pathPrefix: false }
  ],
  i18n: {
    locales: [
      { code: 'en', file: 'en.json' },
      { code: 'es', file: 'es.json' }
    ],
    langDir: 'locales'
  }
})
