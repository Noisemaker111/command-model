# OpenCode2 file-evidence handoff

`inspect_file` is the first installed-host integration for the local specialist.
The frontier agent passes an exact known path and a short evidence request. The
adapter calls the host's registered `read` implementation, passes its text page to
`shell-specialist-pilot` on local Ollama, and returns only selected **verbatim**
lines, absolute file line numbers, coverage status, and a saved raw-page path.
Paths never pass through the local model. Existing request-local path bindings in
`run.py` remain the command-planning interface for the separate five-operation CLI.

This integration deliberately starts with evidence extraction from file pages.
It does not yet route arbitrary shell work or the CLI's five planning operations.
The caller already knows the path and read bounds, so there is no planning-model
call. Native `read` remains the right tool when the caller needs all lines.

## Configure

Keep the existing host configuration and add this **directory** to `plugins`.
OpenCode2 requires a directory containing `index.mjs`, not the entrypoint filename:

```json
{
  "plugins": [{
    "package": "C:/path/to/shell-forensics/experiments/command_specialist/opencode",
    "options": {
      "python": "C:/path/to/existing/.venv/Scripts/python.exe",
      "model": "shell-specialist-pilot",
      "baseURL": "http://127.0.0.1:11434",
      "artifacts": "C:/path/to/private/specialist-results",
      "timeoutMs": 15000
    }
  }]
}
```

Only Python's standard library is required at inference time. Reuse the existing
Ollama model; installation does not train, download or replace it. The Python
executable defaults to `COMMAND_SPECIALIST_PYTHON`, then `python`; the other defaults
are shown above except artifacts, which default to the OS temporary directory's
`command-specialist-host` subdirectory. The endpoint must be loopback HTTP. Config
options are operator-owned and cannot be supplied in model tool arguments.

Do not activate an unreviewed plugin in a production release. This repository's PR
prepares the adapter; global setup/release activation is separate.

## Agent use

Discover `inspect_file` with the host's Code Mode `search`, then call the returned
concrete tool (normally `tools.inspect_file`):

```javascript
const packet = await tools.inspect_file({
  path: "logs/build [draft]'s.log",
  evidence_request: "Return every ERROR and the final SUMMARY.",
  offset: 1,
  limit: 100
});
return packet;
```

Use `read` on `packet.raw_result` to reopen the original captured page. The text
artifact has page-relative lines; `packet.source_lines` contains original file
line numbers. A sibling JSON record preserves the full native tool result, host
and specialist identities, timing, requested bounds, and the returned packet.
Neither artifact is a complete-file claim when the native read was truncated.
Artifacts are private local files and are not automatically deleted.

- `status: selected` means indices were validated and evidence copied from the
  native page. It does **not** certify recall, task success, or absence of errors.
- `truncated: true` and `next_offset` mean more source lines exist. Follow the
  supplied native-read fallback, or request another specialist page explicitly.
- `status: fallback` retains raw output and supplies native `read` arguments.
  Unsupported native output, shortened lines, excessive context, invalid indices,
  unavailable Python/Ollama, or timeout do not become successful empty selections.
- Permission denials and native read failures propagate as tool errors. They
  trigger no model invocation or new result artifact and are never retried through
  an independent filesystem or shell executor.

## Boundaries and authorization

The adapter exposes the native `read` permission category and calls the captured
registered native read with the original session, agent, message and call identity.
That implementation retains path resolution, per-resource permission prompts and
denials, external-directory checks, and nearby instruction loading. The adapter
never reads the source file itself. Its subprocess only receives already-authorized
text and communicates with local Ollama. No shell commands are generated or run.

The page is at most 100 lines, and text plus request must fit the pilot's 8,000
character budget. The model selects ordered line indices; the adapter independently
validates them and reconstructs all returned text. Native shortened-line markers
cause fallback rather than a false exact-text claim. Empty pages need no model call.
No-match results remain model selections, not deterministic absence proofs.

`wall_ms` measures the native read (including permission wait), Python startup and
transport, local inference, validation, raw/record writing and record reopening;
it excludes the final timing-stamp write, host serialization, frontier generation,
and discovery. Measure the awaited host call and entire frontier operation
separately before making a whole-workflow performance claim.

## Checks

```powershell
node --test experiments/command_specialist/opencode/core.test.mjs
python -m unittest discover -s experiments/command_specialist -p 'test_*.py'
```

The core checks supplement real configured-host use. See `HOST_RESULTS.md` for
observed host runs, failures, exact scope, and remaining work.
