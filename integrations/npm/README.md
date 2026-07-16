# openmnemex (npm shim)

This package is a ~2-file `npx` shim, not a reimplementation. OpenMnemex's engine is Python
(see the repo root); this package exists only so JS-native users can run

```
npx openmnemex install --agent <agent> [--project|--user] [--pin-graph]
npx openmnemex-mcp
```

without knowing `uv`/`pipx` exist. Both commands exec the real `openmnemex` PyPI package
through whichever ephemeral tool runner is on `PATH` (`uv` preferred, `pipx` fallback) --
nothing gets installed into your system Python. If neither is found, the shim prints
install links and exits non-zero rather than guessing.

## Why `--from` / `--spec`

`uvx openmnemex-mcp` (bare) does not resolve: `uv`/`pipx` treat the argument as the PyPI
package name to install, and no package named `openmnemex-mcp` exists -- it's a console
script *inside* the `openmnemex` package, alongside the `openmnemex` installer script. The
correct invocation needs the package named explicitly (`--from`/`--spec`) and the `[mcp]`
extra (or the MCP server installs with its SDK unavailable):

```
uv tool run --from 'openmnemex[mcp]' openmnemex-mcp
pipx run --spec 'openmnemex[mcp]' openmnemex-mcp
```

`lib/run.js` is the only file with logic; both `bin/*.js` entry points just call it with the
script name to launch.

## Not yet published

This package isn't on the npm registry yet -- it ships in the repo (`integrations/npm/`)
alongside the OpenCode plugin adapter. Publish with `npm publish` from this directory once
the corresponding `openmnemex` PyPI release is live (the shim has nothing to launch before
that).
