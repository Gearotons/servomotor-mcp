# .mcpb packaging + registry/directory submission plan (2026-06-11)

**Status:** prep done (manifest draft alongside this file); **building/submitting is gated** on the
repo going public (QUESTIONS Batch 3 Q2). `.mcpb` = "MCP Bundle" (renamed from `.dxt` late 2025) —
the one-click install format for Claude Desktop; the highest-credibility distribution surface we get
for free. Spec/CLI: github.com/modelcontextprotocol/mcpb.

## Build steps (when approved)

1. `npm install -g @anthropic-ai/mcpb` (CLI; verify current package name at the repo above).
2. Layout the bundle dir: `manifest.json` (from this folder, validated) + `server/main.py`
   (thin launcher that imports `servomotor_mcp.server:main`) + `server/lib/` with vendored
   deps: `pip install --target server/lib mcp servomotor-mcp` (mock backend has no other deps;
   the `serial` extra pulls the `servomotor` lib — include it so real hardware works offline).
3. `mcpb validate manifest.json` → `mcpb pack . servomotor-mcp.mcpb`.
4. Test on a clean machine: double-click install into Claude Desktop, run with `backend=mock`
   ("list the motors, move axis1 to 45°"), then `backend=serial` against a real M17.
5. Sanity: bundle stays small (no tests/hardware_tests in the bundle); pin dep versions.

## Submission checklist (all free; do in this order, same day as repo goes public)

- [ ] **Official MCP Registry** (registry.modelcontextprotocol.io) — publish via the registry CLI
      flow from the public repo (server.json). Table stakes; "officially-listed" supports our
      category claim wording.
- [ ] **Claude Desktop Extensions directory** — submit the validated `.mcpb` (process per
      anthropic.com/engineering/desktop-extensions; check current submission form).
- [ ] **Directories:** Glama (~34k servers), mcp.so (~19.7k), PulseMCP (~17.6k), Smithery —
      each has an add-server form; a *hardware* server stands out in all of them.
- [ ] **PulseMCP newsletter tip** (outward-facing → draft exists in launch assets, approval-gated).
- [ ] **awesome-mcp-servers PR** (github.com/punkpeye/awesome-mcp-servers) — hardware section.

## Notes / risks
- Field names in `manifest.json` should be re-validated against the mcpb spec at build time
  (the format evolved from .dxt during 2025; `mcpb validate` is the source of truth).
- The bundle's default MUST stay `backend=mock` — a first-run user without hardware should get a
  delightful no-op demo, not a serial-port error.
- Version the bundle in lockstep with the PyPI package (`0.1.0` now).
