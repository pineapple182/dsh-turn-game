# Publishing checklist

This document is for maintainers. It is not part of the npm package.

## 1. GitHub

- Owner/repo: `pineapple182/dsh-turn-game` (update `package.json` if the
  final name differs).
- Public repository.
- Add the GitHub topic `dsh-plugin` after the repo exists.
- Description: "Turn-based game adapter for DeepSeek Harness; includes a
  Gomoku example."
- The repository root must keep `package.json` as the plugin package. The
  Gomoku example stays under `examples/gomoku/`.
- Enable GitHub Security Advisories.
- Optional: social preview from `icon.svg`.

## 2. npm

- Package name: `dsh-turn-game` (checked available; unscoped).
- Author: `大肥鱼 (DeepSeek Harness AI)`; maintainer `pineapple182`.
- License: MIT.
- `files` contains only `lib/`, `cordis.patch.yml`, `README.md`, `LICENSE`,
  `icon.svg`; examples and tests stay in the repository.
- Run the tests and inspect the tarball before publishing:

  ```powershell
  node test/package.test.mjs
  node test/gateway-client.test.mjs
  node test/activation-controller.test.mjs
  node test/host.test.mjs
  pnpm pack
  ```

- Preferred release: push a `v0.1.0` tag and let
  `.github/workflows/publish.yml` publish with npm provenance. Add an
  `NPM_TOKEN` repository secret (Automation token with 2FA bypass, or use
  trusted publishing).
- Never commit `.npmrc` or tokens; `.gitignore` already excludes `.npmrc`.

## 3. DSH Plugin Hub (dsh-plugin.org)

Requirements from the hub:

- Public repo with an accurate description and README.
- GitHub topic `dsh-plugin`.
- README install command, e.g.
  `dsh plugin --profile web add dsh-turn-game`.
- Plugin exports `apply(ctx)`.
- Repository root `package.json` with the plugin name/version (the hub reads
  it and verifies the matching npm package).
- Publish the package to npm so the in-DSH Plugin Hub can install it in one
  step.
- Declare license, screenshots/demo, permissions, compatibility.
- Add the `dsh-plugin` topic before submitting.

Submit via the hub's **Submit** flow / issue. Suggested category:
**Entertainment** (or Tools & Capabilities if the hub prefers generic
automation). Include:

- One-line value: "Wake the current DSH session for its turn in any
  turn-based game; includes a Gomoku example."
- Install: `dsh plugin --profile web add dsh-turn-game`.
- Compatibility: DSH `0.2.x` (tested `0.2.1-rc.2`).
- Permissions: localhost gateway only; no filesystem/shell access.
- Screenshots: `docs/screenshots/lobby.png`, `midgame.png`, `win.png`.
- License: MIT.
- Repository: `https://github.com/pineapple182/dsh-turn-game`.

After listing, add the badge to the README if desired:

```markdown
[![Listed on dsh-plugin.org](https://dsh-plugin.org/badges/listed.svg)](https://dsh-plugin.org/plugins/pineapple182/dsh-turn-game)
```

## 4. Release order

1. CI green on Windows and Linux.
2. Tag `v0.1.0`; npm publish succeeds.
3. Verify `dsh plugin --profile desktop add dsh-turn-game` on a clean
   profile.
4. Add the `dsh-plugin` topic and submit to the hub.
5. Update CHANGELOG and release notes.
