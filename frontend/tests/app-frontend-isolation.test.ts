/**
 * An App's screens name no module outside the App.
 *
 * The backend has had this guard for years (`test_module_isolation.py`);
 * the frontend had none, and it showed: the patient record imported the
 * components of eight other modules and called three of their APIs, so
 * none of them could be switched off without leaving it broken.
 *
 * What another App contributes to a screen arrives through a slot
 * (`registerSlot`), and the data it needs through the slot's `loader`.
 * This reads the source of each decoupled App's layers and fails on a
 * component owned by, or an `/api/v1/<module>` path belonging to, a
 * module outside the App. Shared components in the host app are fair
 * game; so is every module inside the same App.
 *
 * Apps are added here as they are decoupled — see `backend/apps.json`.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { basename, dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const modulesRoot = resolve(frontendRoot, '..', 'backend', 'app', 'modules')

/** Apps whose frontend must stand on its own, by module. */
const DECOUPLED_APPS: Record<string, string[]> = {
  patients: ['patients', 'patients_clinical', 'patient_timeline', 'media', 'memberships']
}

/** Core API namespaces, not modules. */
const CORE_APIS = new Set(['auth', 'modules', 'apps', 'events', 'agents', 'privacy', 'clinics', 'users'])

function walk(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir).flatMap((name) => {
    if (name === 'node_modules') return []
    const path = join(dir, name)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

const allModules = readdirSync(modulesRoot).filter(name =>
  existsSync(join(modulesRoot, name, 'frontend'))
)

/** Component name → the module whose layer defines it. */
const componentOwner = new Map<string, string>()
for (const module of allModules) {
  for (const file of walk(join(modulesRoot, module, 'frontend', 'components'))) {
    if (file.endsWith('.vue')) componentOwner.set(basename(file, '.vue'), module)
  }
}

describe.each(Object.entries(DECOUPLED_APPS))('%s app frontend', (_app, modules) => {
  const sources = modules.flatMap(module =>
    walk(join(modulesRoot, module, 'frontend')).filter(f => /\.(vue|ts)$/.test(f))
  )

  it('has source to check', () => {
    expect(sources.length).toBeGreaterThan(10)
  })

  it('uses no component owned by a module outside the App', () => {
    const offenders: string[] = []
    for (const file of sources) {
      const text = readFileSync(file, 'utf-8')
      for (const [, name] of text.matchAll(/<([A-Z][A-Za-z0-9]+)/g)) {
        const owner = componentOwner.get(name!)
        if (owner && !modules.includes(owner)) {
          offenders.push(`${relative(modulesRoot, file)}: <${name}> belongs to ${owner}`)
        }
      }
    }
    expect([...new Set(offenders)]).toEqual([])
  })

  it('calls no API of a module outside the App', () => {
    const offenders: string[] = []
    for (const file of sources) {
      const text = readFileSync(file, 'utf-8')
      for (const [, target] of text.matchAll(/api\/v1\/([a-z_]+)/g)) {
        if (!modules.includes(target!) && !CORE_APIS.has(target!)) {
          offenders.push(`${relative(modulesRoot, file)}: /api/v1/${target}`)
        }
      }
    }
    expect([...new Set(offenders)]).toEqual([])
  })
})
