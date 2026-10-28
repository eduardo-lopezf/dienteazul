// Nuxt layer for the `calendar_feed` module.
//
// Components live under ./components with no folder-prefix naming
// (matches host convention so <CalendarFeedCard /> resolves across
// layers).
export default defineNuxtConfig({
  components: [
    { path: './components', pathPrefix: false }
  ]
})
