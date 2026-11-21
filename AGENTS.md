# Repository instructions

Read [README.md](README.md) for the supported demo path, then
[docs/architecture.md](docs/architecture.md) and the implementation and tests
you are changing.

- Keep LiveKit room ownership separate from persistent case and work ownership.
  Preserve original scoped identities on replay and report uncertain outcomes
  until they can be reconciled.
- Keep read-only policy results and investigation permission separate from exact
  quote approval. The authenticated operator is the source of booking consent.
- Keep the default demo local, synthetic, and account-free. Exclude credentials,
  generated artifacts, and local runtime state from commits and media.
- Preserve state across ordinary restart. Use the explicit reset command only
  for an authorized demo reset.
- Check affected tests and exercise the supported UI path on the local stack
  before changing a documented behavior or demo claim.
