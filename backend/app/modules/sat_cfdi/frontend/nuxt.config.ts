// Nuxt layer for the `sat_cfdi` module (Mexico's SAT, CFDI 4.0). No pages
// of its own: the issuer's settings are a page of Settings → Billing.
// i18n keys live under `satCfdi.*`.
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
