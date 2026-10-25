// npm audit with a reasoned allowlist — ADR 0029.
//
// `npm audit` has no per-advisory exception, so the choice it offers is
// a gate that is red forever or one raised past the severity we care
// about. Both end the same way: nobody reads it. This keeps the gate at
// `high` and lists the exceptions individually, the way
// `tests/test_no_dynamic_sql.py` and the cross-tenant baseline do.
//
// Entries are promises. Each needs a reason that survives review, and
// each should go the moment its fix is reachable.
import { spawnSync } from 'node:child_process'

const ALLOWED = {
  // No fixed release exists: the advisory covers every published
  // version (<=1.4.0, the latest). `node-forge` arrives under `listhen`,
  // the dev-server listener that mints a self-signed certificate for
  // `nuxi dev --https`; the weakness is RSA PKCS#1 v1.5 signature
  // verification, which this project never asks it to do. Verified on
  // 2026-10-25: `listhen`, `nitropack` and `node-forge` are all absent
  // from `.output/server/node_modules`, and nothing under `.output`
  // mentions `node-forge`.
  //
  // `nuxt` itself needs no entry: its own advisories are closed as of
  // 4.6.2, and it is listed only through this chain. The same bump took
  // `@nuxt/devtools` to 3.4.4, which no longer depends on `simple-git` —
  // the two `simple-git` entries that used to sit below are gone with it.
  'node-forge': 'no published fix (<=1.4.0 is every version); dev-server TLS only, absent from .output'
}

const FAIL_AT = new Set(['high', 'critical'])

// `npm audit` queries a registry endpoint, and that call fails often
// enough to matter — a run of five here hung up four times.
const ATTEMPTS = 3

let report
let lastFailure = ''
for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
  const result = spawnSync('npm', ['audit', '--json'], {
    encoding: 'utf-8',
    maxBuffer: 64 * 1024 * 1024
  })

  let parsed
  try {
    parsed = JSON.parse(result.stdout)
  } catch {
    lastFailure = `unparseable output: ${(result.stdout ?? '').slice(0, 500)}${result.stderr ?? ''}`
    continue
  }

  // A failed audit still exits with *valid JSON* — `{ message, error }`
  // where `{ vulnerabilities }` belongs. Taken at face value that reads
  // as an audit that found nothing, which is the wrong answer twice
  // over: every allowlist entry below looks stale and is demanded gone,
  // and once the list is empty the gate goes green having checked
  // nothing at all. "Did not run" must never collapse into "no
  // findings", so the absence of `vulnerabilities` is a failure here.
  if (parsed && parsed.vulnerabilities && typeof parsed.vulnerabilities === 'object') {
    report = parsed
    break
  }
  lastFailure = parsed?.message ?? 'report carried no `vulnerabilities` key'
}

if (!report) {
  console.error(
    `audit-gate: \`npm audit\` did not complete after ${ATTEMPTS} attempt(s), `
    + 'so nothing was checked. This is not a clean audit.'
  )
  console.error(`Last failure: ${lastFailure}`)
  process.exit(2)
}

const entries = Object.entries(report.vulnerabilities ?? {})
const byName = new Map(entries)
const gating = entries.filter(([, v]) => FAIL_AT.has(v.severity))

/** The advisories a package carries itself, rather than through a dependency. */
function ownAdvisories(name) {
  return (byName.get(name)?.via ?? []).filter(
    entry => typeof entry === 'object' && FAIL_AT.has(entry.severity)
  )
}

/** The packages a package is high *through*, itself excluded. */
function parentsOf(name) {
  return (byName.get(name)?.via ?? []).filter(
    entry => typeof entry === 'string' && entry !== name
  )
}

/**
 * Which packages inherit an allowlisted reason.
 *
 * A package with a high advisory of its own needs its own entry. A
 * package that is only high *because* something it depends on is — the
 * six here, `nuxt` and `nitropack` → `listhen` → `node-forge` among them
 * — inherits the reason from the package that carries the advisory.
 * Writing those out by hand would be six copies of one sentence, each
 * going stale on its own; this keeps the gate asking about the one
 * package that is actually unfixable.
 *
 * Computed by elimination rather than by walking up, because the graph
 * has cycles: `nuxt` is high through `@nuxt/vite-builder`, which is high
 * through `nuxt`. Start by assuming every package without an advisory of
 * its own is covered, then drop any whose parent is not — repeat until
 * nothing moves. A cycle whose way out is allowlisted survives; one that
 * reaches an unexplained advisory is dropped along with it.
 */
function inheritedlyAllowed() {
  const covered = new Set(
    gating.filter(([name]) => !ownAdvisories(name).length).map(([name]) => name)
  )
  for (let changed = true; changed;) {
    changed = false
    for (const name of [...covered]) {
      const parents = parentsOf(name)
      const explained = parents.length > 0 && parents.every(
        parent => parent in ALLOWED || covered.has(parent) || !FAIL_AT.has(byName.get(parent)?.severity)
      )
      if (!explained) {
        covered.delete(name)
        changed = true
      }
    }
  }
  return covered
}

const inherited = inheritedlyAllowed()

/** The allowlisted packages a package's advisories actually come from. */
function rootsFor(name, seen = new Set()) {
  const roots = new Set()
  for (const parent of parentsOf(name)) {
    if (seen.has(parent)) continue
    seen.add(parent)
    if (parent in ALLOWED) roots.add(parent)
    else for (const root of rootsFor(parent, seen)) roots.add(root)
  }
  return roots
}

function allowedBecause(name) {
  if (name in ALLOWED) return `allowed — ${ALLOWED[name]}`
  if (!inherited.has(name)) return null
  const roots = [...rootsFor(name)]
  return `allowed — only high through ${roots.length ? roots.join(', ') : 'allowlisted dependencies'}`
}

const unlisted = gating.filter(([name]) => !allowedBecause(name))

for (const [name, v] of gating) {
  console.log(`${v.severity.padEnd(8)} ${name.padEnd(28)} ${allowedBecause(name) ?? 'NOT ALLOWED'}`)
}

// An exception that outlives its advisory is an exception nobody
// reviews, so a stale entry fails just as loudly as a new advisory.
const stale = Object.keys(ALLOWED).filter(
  name => !gating.some(([gatingName]) => gatingName === name)
)
if (stale.length) {
  console.error(
    `\naudit-gate: these are allowlisted but no longer reported at high/critical — `
    + `remove them from scripts/audit-gate.mjs: ${stale.join(', ')}`
  )
  process.exit(1)
}

if (unlisted.length) {
  console.error(
    `\naudit-gate: ${unlisted.length} unlisted high/critical advisor${
      unlisted.length === 1 ? 'y' : 'ies'
    }: ${unlisted.map(([n]) => n).join(', ')}\n`
    + `Fix them, or add an entry with a reason if the fix is genuinely unreachable.`
  )
  process.exit(1)
}

console.log(`\naudit-gate: no unlisted high/critical advisories.`)
