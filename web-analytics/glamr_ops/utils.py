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


def sorted_keys(some_dict, key=None):
    """
    Return the given dictionary with sorted keys.

    key:
        A custom key function that takes the dictionary key as input.  If None
        then this simply sorts the dictionary keys.
    """
    def adapter(item):
        return key(item[0])

    if key is None:
        keyarg = None
    else:
        keyarg = adapter

    return {
        k: v for k, v
        in sorted(some_dict.items(), key=keyarg)
    }
