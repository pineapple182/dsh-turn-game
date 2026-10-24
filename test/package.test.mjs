import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const pkg = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
const patch = readFileSync(resolve(root, 'cordis.patch.yml'), 'utf8')
const readme = readFileSync(resolve(root, 'README.md'), 'utf8')
const readmeEn = readFileSync(resolve(root, 'README.en.md'), 'utf8')

test('package is a DSH bundle with publishable metadata', () => {
  assert.equal(pkg.name, 'dsh-turn-game')
  assert.match(pkg.version, /^\d+\.\d+\.\d+/)
  assert.equal(pkg.license, 'MIT')
  assert.equal(pkg.dsh.bundle.patch, './cordis.patch.yml')
  assert.match(pkg.engines.dsh, /0\.2/)
  assert.match(pkg.engines.node, /22|24/)
  assert.equal(pkg.main, 'lib/index.js')
  assert.doesNotMatch(patch, /name:\s*dsh-turn-game\s*\n\s*config:\s*\n\s*enabled:\s*false/)
  assert.match(patch, /name:\s*dsh-turn-game/)
})

test('npm files include the patch, entrypoint, license and icon', () => {
  for (const file of ['lib/', 'cordis.patch.yml', 'README.md', 'README.en.md', 'LICENSE', 'icon.svg']) {
    assert.ok(pkg.files.includes(file), `missing ${file} in files`)
  }
})

test('README exposes a one-step install command', () => {
  assert.match(readme, /dsh plugin --profile web add dsh-turn-game/)
  assert.match(readme, /README\.en\.md/)
  assert.match(readmeEn, /README\.md/)
  assert.match(readmeEn, /dsh plugin --profile web add dsh-turn-game/)
})
