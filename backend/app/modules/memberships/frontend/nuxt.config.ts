// Nuxt layer for the `memberships` module: the plans page and the
// "Membresía" tab of the patient record, with its locales merged at build time.
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
