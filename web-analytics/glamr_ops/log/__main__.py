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
from .apache import fix_logs, list_log_files, ApacheLogRetriever
from .uwsgi import UwsgiLogRetriever


def cli():
    argp = argparse.ArgumentParser(description=__doc__)
    subs = argp.add_subparsers(dest='cmd')

    retrieve_subp = subs.add_parser(
        'retrieve',
        help='Retrieve log files',
    )
    retrieve_subp.add_argument('log_type')
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
        case 'retrieve':
            kwargs = dict(
                src_dir=args.source_dir,
                dst_dir=args.destination_dir,
                remove_original=args.remove_original,
                fixup=not args.no_fix,
            )
            match args.log_type:
                case 'apache':
                    ApacheLogRetriever(**kwargs).run(dry_run=args.dry_run)
                case 'uwsgi':
                    UwsgiLogRetriever(**kwargs).run(dry_run=args.dry_run)
                case _: argp.error('unsupprted log type')
        case _: argp.error('invalid sub command')



if __name__ == '__main__':
    cli()
