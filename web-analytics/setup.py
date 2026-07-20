from subprocess import run
from setuptools import setup


def get_version():
    cmd = ['/usr/bin/git',  'describe', '--tags', '--always']
    try:
        p = run(cmd, capture_output=True, check=True)
    except Exception as e:
        print(f'Getting version failed: {e.__class__.__name__}: {e}')
        return 'UNKNOWN'

    out = p.stdout.decode().strip()
    if len(out.splitlines()) == 1 and out.startswith('v'):
        return out.lstrip('v')
    else:
        print('[WARNING] failed parsing version')
        return 'UNKNOWN'


setup(
    name='glamr_ops',
    version='1.2',
    # version=get_version(),  # disabled, it makes a mess with permission bits
    packages=[
        'glamr_ops',
        'glamr_ops/log',
    ])
