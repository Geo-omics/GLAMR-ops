""" command-line interface for general log operations """
import argparse
import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import shlex
import shutil
from subprocess import run

from glamr_ops import get_configuration
from glamr_ops.utils import gzip
from .apache import fix_logs, list_log_files


def cli():
    argp = argparse.ArgumentParser(description=__doc__)
    subs = argp.add_subparsers(dest='cmd')

    retrieve_subp = subs.add_parser(
        'retrieve',
        help='Retrieve log files',
    )
    retrieve_subp.add_argument('--source-dir')
    retrieve_subp.add_argument('--destination-dir')
    retrieve_subp.add_argument('--dry-run', action='store_true')
    retrieve_subp.add_argument(
        '--remove-original', action='store_true',
        help='Remove original log files (at the source directory) after '
             'making a successful copy except for today\'s log which will be '
             'preserved as it may be incomplete.',
    )
    retrieve_subp.add_argument('--no-fix', action='store_true')

    args = argp.parse_args()
    match args.cmd:
        case 'retrieve': retrieve(
            src_dir=args.source_dir,
            dst_dir=args.destination_dir,
            dry_run=args.dry_run,
            remove_original=args.remove_original,
            fixup=not args.no_fix
        )
        case _: argp.error('invalid sub command')


def retrieve(src_dir=None, dst_dir=None, remove_original=False, dry_run=False,
             fixup=False):
    """
    Get apache log file, fix and compress if needed.

    Will only fix uncompressed logs.
    """
    conf = get_configuration()
    if src_dir:
        src_dir = Path(src_dir)
    else:
        src_dir = Path(conf['OPENSHIFT_APACHE_LOGS'])

    if dst_dir:
        dst_dir = Path(dst_dir)
    else:
        dst_dir = Path(conf['VAR_DIR']) / 'daily-logs'

    # See what we already have, except most recent log
    have = dict(list_log_files(dst_dir, suffix='.log.gz')[:-1])
    today = datetime.date.today()

    with TemporaryDirectory(dir=dst_dir) as tmpd:
        for date, src in list_log_files(src_dir):
            if date in have:
                diff = src.stat().st_mtime - have[date].stat().st_mtime
                if diff > 1.0:
                    # src is newer than existing file
                    # NOTE: pigz drops sub-second precision of mtime
                    print(f'[INFO] update? {src.name} {diff=}')
                    pass
                else:
                    # skip this one
                    print(f'[INFO] already have {src.name} -- remove manually')
                    continue

            dst = dst_dir / src.name
            tmp_dst = Path(tmpd) / src.name
            print(f'Getting {src.name} ', end='', flush=True)
            shutil.copy2(src, tmp_dst)
            tmp_dst.chmod(0o660)  # turbo storage really likes x perms

            if fixup:
                fixed = fix_logs(tmp_dst.parent, redo=True)
                if fixed:
                    fixlog = tmp_dst.with_name('fix.log')
                    if fixlog.is_file():
                        # append fix log to common fix log
                        fixlog_safe = shlex.quote(tmpd) + '/fix.log'
                        globalfixlog_safe = shlex.quote(str(dst_dir)) + '/fix.log'
                        cmd = f'cat {fixlog_safe} >> {globalfixlog_safe}'
                        if dry_run:
                            fixlines = fixlog.read_text().splitlines()
                            if fixlines:
                                print()
                            for line in fixlines:
                                print(f'  [FIXED] {line.strip()}')
                        else:
                            run([cmd], shell=True, check=True)
                        fixlog.unlink()
                    print('[fixed]', end=' ', flush=True)

            if tmp_dst.suffix == '.log':
                print('[compressing]', end=' ', flush=True)
                tmp_dst = gzip(tmp_dst)
                dst = dst.with_suffix('.log.gz')  # was .log

            if not dry_run:
                tmp_dst.rename(dst)

            if remove_original and date < today:
                # remove older logs at source, keep today's log
                print('[remove original]', end=' ', flush=True)
                if not dry_run:
                    src.unlink()
            if dry_run:
                print('[dry run OK]')
            else:
                print('[OK]')


if __name__ == '__main__':
    cli()
