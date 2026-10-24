# Security

`dsh-turn-game` runs inside the DeepSeek Harness host process and talks to a
local Turn Gateway over HTTP. It does not read files, execute shell commands,
or open network connections beyond the configured `gatewayUrl`.

- The default gateway is `http://127.0.0.1:8766`.
- The plugin has no runtime dependencies; `@deepseek-ai/*` packages are
  provided by the DSH host.
- The example game binds to `127.0.0.1` by default and has no accounts.
- The plugin has no player tokens yet; local actors are trusted.

Please report security issues privately through GitHub Security Advisories
on the repository, not in a public issue. The commit email
`pineapple182@users.noreply.github.com` is a GitHub noreply attribution
address, not a monitored mailbox; do not send reports there.
