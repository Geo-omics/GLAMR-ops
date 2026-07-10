import shlex
from subprocess import PIPE, run


CONFIG_FILE = '/etc/glamr-web-analytics.conf'


def get_configuration(config_file=CONFIG_FILE):
    SHELL_VARS = "set -o posix; set | grep -E '^[A-Z][A-Z_]*=' | grep -v ^BASH_ | sort"
    cmd = f"""
        set -eu -o pipefail;
        before=$({SHELL_VARS});
        source {shlex.quote(config_file)};
        after=$(unset before; {SHELL_VARS});
        diff --suppress-common-lines <(echo "$before") <(echo "$after");
    """
    p = run(cmd, shell=True, executable='/bin/bash', stdout=PIPE)
    config = {}
    for line in p.stdout.decode().split('\n'):
        if not line.startswith('> '):
            continue

        varname, _, value = line.lstrip('> ').partition('=')
        if not varname:
            raise ValueError(f'bad variable name at line: "{line}"')
        if varname in config:
            raise ValueError(f'duplicate variable name: "{line}"')
        config[varname] = value
    return config
