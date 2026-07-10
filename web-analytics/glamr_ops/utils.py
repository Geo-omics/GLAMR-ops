from pathlib import Path
from shutil import which
from subprocess import run


def gzip(path):
    """
    gzip given file in place.

    path [str|Path]: File to be compressed.

    Returns Path to compressed file.
    """
    path = Path(path)
    PROGS = ['pigz', 'gzip']
    for i in PROGS:
        if prog := which(i):
            break
    else:
        raise RuntimeError(f'none of {PROGS} in PATH?')

    run([prog, str(path)], check=True)
    return path.with_suffix(path.suffix + '.gz')
