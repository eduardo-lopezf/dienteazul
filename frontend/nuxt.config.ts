// https://nuxt.com/docs/api/configuration/nuxt-config
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Plugin } from 'vite'

/**
 * Load Nuxt Layer paths from `modules.json`.
 *
 * The backend writes this file whenever a module with a declared
 * `manifest.frontend.layer_path` is installed. When absent (fresh
 * checkout, no community modules yet), returns an empty array.
 */
function loadModuleLayers(): string[] {
  // `DIENTEAZUL_MODULES_JSON` lets CI (and anyone without a running
  // backend) point at a manifest with repo-relative paths, so the module
  // layers are actually typechecked instead of being stubbed away — the
  // blind spot that let type errors pile up unseen. A developer's real
  // `modules.json`, written by their backend with container paths, is
  // left alone.
  const path = resolve(__dirname, process.env.DIENTEAZUL_MODULES_JSON ?? 'modules.json')
  try {
    const raw = readFileSync(path, 'utf-8')
    const payload = JSON.parse(raw) as { layers?: string[] }
    return Array.isArray(payload.layers) ? payload.layers : []
  } catch (err: unknown) {
    const code = (err as { code?: string }).code
    if (code !== 'ENOENT') {
      console.warn('[nuxt.config] modules.json is malformed, using empty layers:', err)
    }
    return []
  }
}

// Resolved once here so the auto-import below carries an absolute path
// instead of a bare specifier (see the `imports:extend` hook).
const vueI18nEntry = resolve(__dirname, 'node_modules/vue-i18n/dist/vue-i18n.esm-bundler.js')

const moduleLayers = loadModuleLayers()
const modulesJsonPath = resolve(__dirname, process.env.DIENTEAZUL_MODULES_JSON ?? 'modules.json')

// Nuxt 4.6 hands Vite's dependency scanner the components that modules
// register from `node_modules`. `@nuxtjs/i18n`'s `NuxtLinkLocale` imports
// `#components`, a Nuxt alias its own package.json does not declare, and
// Vite 8's scanner gives up on the whole scan: "Missing "#components"
// specifier in "@nuxtjs/i18n" package … Skipping dependency pre-bundling".
// Nothing behind that alias is a dependency to pre-bundle, so the scan
// steps over it. Vite passes `scan: true` to `resolveId` only while
// scanning; the hook's public type leaves the flag out, hence the cast.
const scanSkipsNuxtComponentsAlias: Plugin = {
  name: 'dienteazul:scan-skips-nuxt-components-alias',
  enforce: 'pre',
  resolveId(id, _importer, options) {
    if ((options as { scan?: boolean }).scan && id === '#components') {
      return { id, external: true }
    }
  }
}

export default defineNuxtConfig({

  // The dev server runs in a container against this same mounted
  // directory, so a host-side `nuxt typecheck` writing `.nuxt` corrupts
  // the running app's build ("Package import specifier
  // #nuxt-icon-server-options is not defined"). The typecheck gate sets
  // this to a scratch directory so the two never share one.

  extends: moduleLayers,

  modules: [
    '@nuxt/eslint',
    '@nuxt/ui',
    '@nuxtjs/i18n'
  ],

  components: [
    {
      path: '~/components',
      pathPrefix: false
    }
  ],

  devtools: {
    enabled: true
  },
  app: {
    head: {
      title: 'Dental Demo',
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }
      ]
    }
  },

  css: ['~/assets/css/main.css'],

  // Default to light mode; users can opt into dark via the toggle. Both
  // ``preference`` and ``fallback`` are set so SSR + first-paint render
  // light without a flash even before client hydration reads OS prefs.
  colorMode: {
    preference: 'light',
    fallback: 'light'
  },

  runtimeConfig: {
    // Server-side only: the browser talks exclusively to the same-origin BFF.
    apiBaseUrlServer: process.env.NUXT_API_BASE_URL_SERVER || 'http://backend:8000',
    public: {
      // Deliberately empty. Browser API traffic is same-origin via Nitro.
      apiBaseUrl: '',
      // Public app origin for CSRF validation behind a TLS-terminating proxy.
      appOrigin: process.env.NUXT_PUBLIC_APP_ORIGIN || '',
      demoMode: process.env.NUXT_PUBLIC_DEMO_MODE === 'true',
      // Documentation portal origin used by the in-app help drawer
      // (Fase 5 of issue #75). Empty disables the help button.
      docsUrl: process.env.NUXT_PUBLIC_DOCS_URL || 'https://docs.dienteazul.com',
      // Minutes without interaction before a session ends and the user is
      // sent to login (ADR 0030). Overridable at runtime with
      // NUXT_PUBLIC_SESSION_IDLE_MINUTES.
      sessionIdleMinutes: 60
    }
  },
  srcDir: 'app',
  buildDir: process.env.NUXT_BUILD_DIR ?? '.nuxt',

  // Response headers that bound what a browser will do with a page
  // (ADR 0029, invariant 4). The API sets its own set; this is the half
  // that covers the rendered app.
  //
  // No `Content-Security-Policy` here yet, deliberately: Nuxt inlines
  // the hydration payload, so a real policy needs per-request nonces
  // and a pass over every inline style. Shipping a wrong one either
  // breaks hydration or gets relaxed to `unsafe-inline`, which is a
  // header that looks like a control and is not one. Tracked as
  // follow-up in ADR 0029.
  routeRules: {
    '/**': {
      headers: {
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
        'Referrer-Policy': 'strict-origin-when-cross-origin'
      }
    },
    // The patient-facing budget view carries its access token in the
    // path (ADR 0006). `no-referrer` keeps that token out of the
    // `Referer` of anything the page links to, and `noindex` is the
    // header ADR 0006 assumed was already set and never was.
    '/p/**': {
      headers: {
        'Referrer-Policy': 'no-referrer',
        'X-Robots-Tag': 'noindex, nofollow'
      }
    }
  },

  // Restart dev server when the backend rewrites `modules.json` on
  // module install/uninstall. `extends` is evaluated once at config
  // boot, so a layer added after Nuxt started is invisible until
  // restart. Watching the file makes the round-trip automatic.
  watch: [modulesJsonPath],

  compatibilityDate: '2025-01-15',

  vite: {
    plugins: [scanSkipsNuxtComponentsAlias],
    optimizeDeps: {
      // Pre-bundle deps that Vite otherwise discovers at runtime. Runtime
      // discovery triggers a full page reload, which in CI races Playwright's
      // `goto` and causes net::ERR_ABORTED on the very first visit to any
      // route that uses these packages.
      include: [
        'nprogress',
        '@vueuse/core',
        '@vue/devtools-core',
        '@vue/devtools-kit'
      ]
    }
  },

  // `@nuxtjs/i18n` registers `useI18n` with the bare specifier
  // `vue-i18n`, which the auto-import transform can only resolve from
  // the host. Module layers live outside `frontend/`, so there the
  // resolution fails and the injection is silently skipped — the call
  // then throws `useI18n is not defined` at runtime and takes the whole
  // page down (the Tratamientos pipeline did exactly that). Pointing the
  // registration at the resolved file makes it inject in every layer.
  hooks: {
    'imports:extend'(imports) {
      const useI18nImport = imports.find(i => i.name === 'useI18n' && i.from === 'vue-i18n')
      if (useI18nImport) useI18nImport.from = vueI18nEntry
    }
  },

  eslint: {
    config: {
      stylistic: {
        commaDangle: 'never',
        braceStyle: '1tbs'
      }
    }
  },

  i18n: {
    locales: [
      { code: 'en', name: 'English', file: 'en.json' },
      { code: 'es', name: 'Español', file: 'es.json' }
    ],
    defaultLocale: 'es',
    langDir: 'locales',
    strategy: 'no_prefix',
    detectBrowserLanguage: false
  },

  // Pre-bundle every `i-lucide-*` icon referenced in source into the client
  // bundle. Without this, @nuxt/icon fetches icons lazily per-name on client
  // navigation, which causes the sidebar to briefly render a stale / wrong
  // icon (e.g. the settings cog showing up next to "Pacientes") until the
  // real icon resolves.
  icon: {
    clientBundle: {
      scan: true,
      sizeLimitKb: 512
    }
  }
})
