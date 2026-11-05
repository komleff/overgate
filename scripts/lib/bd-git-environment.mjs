// Git trust checks and publication must not inherit caller-supplied repository,
// remote, URL rewrite, config, hook or object namespace overrides.
export function cleanGitEnvironment(source = process.env) {
  const env = {};
  for (const [name, value] of Object.entries(source)) {
    if (name.startsWith('GIT_') && !/^(GIT_AUTHOR|GIT_COMMITTER)_(NAME|EMAIL|DATE)$/.test(name)) continue;
    env[name] = value;
  }
  env.GIT_CONFIG_GLOBAL = process.platform === 'win32' ? 'NUL' : '/dev/null';
  env.GIT_CONFIG_NOSYSTEM = '1';
  env.GIT_TERMINAL_PROMPT = '0';
  env.MSYS2_ARG_CONV_EXCL = '*';
  return env;
}

export function cleanBeadsEnvironment(source = process.env) {
  const env = cleanGitEnvironment(source);
  for (const name of Object.keys(env)) if (/^(BEADS_|BD_|DOLT_|OTEL_)/.test(name)) delete env[name];
  return env;
}
