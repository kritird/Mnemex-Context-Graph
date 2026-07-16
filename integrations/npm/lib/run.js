'use strict';

const { spawn, spawnSync } = require('child_process');

// OpenMnemex `npx` shim (multi-agent plan v2, Phase 5, commit 5d).
//
// Pure ergonomics for JS-native users comparing us to `npx claude-mem install` -- no logic
// lives here. It launches the same Python engine every other agent adapter targets, through
// an ephemeral tool runner (uv preferred, pipx fallback) so nothing gets installed into the
// user's system Python. See ../README.md for why `--from`/`--spec` are required here: the
// script name (`openmnemex` / `openmnemex-mcp`) doesn't always match the PyPI package name
// (`openmnemex`), and the `[mcp]` extra must be requested explicitly or the MCP server installs
// with the SDK unavailable. Both were confirmed empirically against the built wheel (plan v2
// §8 correction, 2026-07-16) -- the bare `uvx openmnemex-mcp` form documented before that does
// not resolve.

function isOnPath(cmd) {
  const probe = spawnSync(cmd, ['--version'], { stdio: 'ignore' });
  return !(probe.error && probe.error.code === 'ENOENT');
}

function notFoundMessage(script, forwardedArgs) {
  const havePython = isOnPath('python3') || isOnPath('python');
  return (
    `openmnemex: neither 'uv' nor 'pipx' was found on PATH.\n\n` +
    (havePython
      ? `python3 is available, but this shim only launches through an ephemeral tool runner ` +
        `so it never installs anything into your system Python.\n\n`
      : '') +
    `Install one of:\n` +
    `  uv (recommended): https://docs.astral.sh/uv/getting-started/installation/\n` +
    `  pipx:             https://pipx.pypa.io/stable/installation/\n\n` +
    `Then re-run this command, or install the Python package directly:\n` +
    `  pip install 'openmnemex[mcp]'\n` +
    `  ${script}${forwardedArgs.length ? ' ' + forwardedArgs.join(' ') : ''}\n`
  );
}

// Runs an openmnemex console-script entry point (`openmnemex` or `openmnemex-mcp`), forwarding
// argv, stdio, exit code, and signals.
function run(script) {
  const forwardedArgs = process.argv.slice(2);
  const spec = 'openmnemex[mcp]';

  let launcher;
  let launcherArgs;
  if (isOnPath('uv')) {
    launcher = 'uv';
    launcherArgs = ['tool', 'run', '--from', spec, script, ...forwardedArgs];
  } else if (isOnPath('pipx')) {
    launcher = 'pipx';
    launcherArgs = ['run', '--spec', spec, script, ...forwardedArgs];
  } else {
    process.stderr.write(notFoundMessage(script, forwardedArgs));
    process.exit(1);
    return;
  }

  const child = spawn(launcher, launcherArgs, { stdio: 'inherit' });

  for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(sig, () => child.kill(sig));
  }

  child.on('error', (err) => {
    process.stderr.write(`openmnemex: failed to launch '${launcher}': ${err.message}\n`);
    process.exit(1);
  });

  child.on('exit', (code, signal) => {
    if (signal) {
      // Re-raise the same signal on ourselves rather than guessing an exit code.
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code === null ? 1 : code);
  });
}

module.exports = { run, isOnPath };
