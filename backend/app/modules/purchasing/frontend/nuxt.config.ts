// Nuxt layer for the `purchasing` module.
//
// Components live under ./components with no folder prefix so cross-layer
// auto-imports resolve, and the locales are declared so @nuxtjs/i18n merges
// the `purchasing.*` keys into the host's es/en at build time. Its screens
// hang off the inventory's, which is why the manifest contributes no
// navigation entry of its own.
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
