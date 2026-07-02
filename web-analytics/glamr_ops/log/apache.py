"""
apache2 combined log fixing, parsing, processing
"""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import dataclasses
from datetime import datetime
import gzip
from itertools import chain
import json
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import NamedTemporaryFile


def cli():
    """ the command-line interface """
    argp = argparse.ArgumentParser(description=__doc__)
    subs = argp.add_subparsers(dest='cmd', help='Commands to manage apache log files')
    fix_parser = subs.add_parser('fix', help='Fix apache logs')
    fix_parser.add_argument(
        'paths',
        nargs='*', type=Path,
        help='Path to log files or a directory.  If this is omitted then input is '
             'expected to stdin',
    )
    hits_parser = subs.add_parser('hits', help='Compile hits from logs')
    hits_parser.add_argument(
        'logs',
        nargs='+', type=Path,
        help='Path to log files to process.'
    )
    hits_parser.add_argument(
        '-o', '--output', help='output file'
    )
    args = argp.parse_args()
    match args.cmd:
        case 'fix': fix_logs(*args.paths)
        case 'hits': compile_hits(args.logs, output=args.output)
        case _: argp.error('invalid subcommand')


class BadApacheLog(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class ApacheLogEntry:
    host: str
    timestamp: datetime
    request: str
    status: int
    bytes: int
    referer: str
    user_agent: str

    log_item_pat = {
        'host': r'[.0-9]+',
        'l': r'[^ ]+',
        'u': r'[^ ]+',
        'timestamp': r'\[([^\]]+)\]',
        'request': r'"[^"]+"',
        'status': r'[0-9]+',
        'bytes': r'[0-9]+',
        'referer': r'"[^"]*"',
        'user_agent': r'"[^"]+"',
    }
    logpat = (
        '^'
        + ' '.join((f'(?P<{k}>{v})' for k, v in log_item_pat.items()))
        + '$'
    )
    logpat = re.compile(logpat)

    @classmethod
    def from_line(cls, line):
        """ Get instance from log line """
        line = line.rstrip('\n')
        m = cls.logpat.match(line)
        if m is None:
            raise BadApacheLog('line did not match pattern')

        kw = {k: v for k, v in m.groupdict().items() if k in cls.__dataclass_fields__}

        try:
            kw['timestamp'] = datetime.strptime(
                kw['timestamp'],
                '[%d/%b/%Y:%H:%M:%S %z]'
            ).astimezone()
        except ValueError as e:
            raise BadApacheLog(f'bad timestamp: {e}') from e

        try:
            kw['status'] = int(kw['status'])
        except ValueError as e:
            raise BadApacheLog(f'bad status: {e}') from e

        try:
            kw['bytes'] = int(kw['bytes'])
        except ValueError as e:
            raise BadApacheLog(f'bad bytes: {e}') from e

        for k in ('request', 'referer', 'user_agent'):
            kw[k] = kw[k].strip('"')

        return cls(**kw)


def get_log_entries(path, errout=sys.stderr):
    """
    Read and parse apache 2 combined log file

        path: Path to log file

    Returns a generator over the log entries yielding a dictionary.
    """
    path = Path(path)

    with ExitStack() as estack:
        if path.suffix == '.gz':
            ifile = estack.enter_context(gzip.open(path, 'rt'))
        else:
            ifile = estack.enter_context(open(path))

        for lnum, line in enumerate(ifile, start=1):
            errmsg = (f'log parsing error in {ifile.name} at line {lnum}: {{msg}}\n'
                      f'bad line: {line}')

            try:
                yield ApacheLogEntry.from_line(line)
            except BadApacheLog as e:
                raise RuntimeError(errmsg.format(msg=e)) from e


def get_hits(log_entries):
    """
    Convert log entries into hits per second time series

    log_entries:  Iterable over log entries as made by get_log_entries()

    Returns hits time series data structure
    """
    # 1. Collect and count hits per day per status per second
    hits0 = defaultdict(lambda: defaultdict(Counter))
    for entry in log_entries:
        dt = entry.timestamp  # datetime
        date = dt.date()
        seconds = dt.hour * 3600 + dt.minute * 60 + dt.second

        if entry.user_agent.startswith('kube-probe/'):
            if 200 <= entry.status <= 299:
                hits0[date]['probe'][seconds] += 1
            elif 400 <= entry.status:
                hits0[date]['probe-fail'][seconds] += 1
            continue

        else:
            hits0[date][entry.status][seconds] += 1

    # 2. Sort by day/status and compile condensed listings
    hits = {}
    for date, day_hits in sorted(hits0.items(), key=lambda x: x[0]):
        hits[date.isoformat()] = {}
        for status, seconds_data in sorted(day_hits.items(), key=lambda x: str(x[0])):
            listing = None
            for sec, count in sorted(seconds_data.items(), key=lambda x: x[0]):
                if not listing:
                    # first round
                    cur_list = [count]
                    listing = [(sec, cur_list)]
                    continue

                gap = sec - listing[-1][0] - len(cur_list)
                if gap == 0:
                    # seconds are consecutive
                    cur_list.append(count)
                elif gap <= 8:
                    # small gap, fill in zeros
                    cur_list.extend([0] * gap + [count])
                else:
                    # gap too big, start new list
                    cur_list = [count]
                    listing.append((sec, cur_list))

            listing = {
                secs: ' '.join(str(i) for i in count_list)
                for secs, count_list in listing
            }
            hits[date.isoformat()][status] = listing

    return hits


def compile_hits(logfiles, output=None):
    """ Implement the CLI hits sub-command """
    entries = chain.from_iterable((get_log_entries(path) for path in logfiles))
    hits = get_hits(entries)
    with ExitStack() as estack:
        if output:
            ofile = estack.enter_context(open(output, 'w'))
        else:
            ofile = sys.stdout
        json.dump(hits, ofile, indent=4)


def fix_file(ifile, ofile, efile):
    """
    Fix a log file

    ifile: input file, open file handle
    ofile: output file, open file handle with mode 'w'
    efile: error file, open file handle with mode 'w'
    """
    fixed_something = False
    log_name = Path(ifile.name).name
    for lineno, line in enumerate(ifile, start=1):
        line = line.rstrip()
        if m := ApacheLogEntry.logpat.search(line):
            ofile.write(f'{m.group(0)}\n')
            if m.start() != 0 or m.end() != len(line):
                fixed_something = True
                print(f'{log_name}:{lineno} Non-matching at start: '
                      f'{m.start()}, at end: {len(line) - m.end()}',
                      file=efile)

        else:
            fixed_something = True
            print(f'{log_name}:{lineno} Bad line', file=efile)
    return fixed_something


def fix_logs(*paths):
    """ implement the CLI fix sub-command """
    if not paths:
        # stdin/out mode
        fix_file(sys.stdin, sys.stdout, sys.stderr)
        return

    with ExitStack() as estack:
        if len(paths) == 1 and (log_dir := paths[0]).is_dir():
            # process a directory
            fixlog = log_dir / 'fix.log'
            if fixlog.exists():
                last_check = fixlog.stat().st_mtime
            else:
                last_check = -1
            efile = estack.enter_context(open(fixlog, 'a'))
            input_files = sorted(log_dir.glob('access.*.log'))
        else:
            # process all given file(s), no fixlog check
            fixlog = None
            last_check = -1
            efile = sys.stderr
            input_files = paths

        for i in input_files:
            ifile_stats = i.stat()
            if ifile_stats.st_mtime <= last_check:
                continue

            with NamedTemporaryFile('w', dir=str(i.parent)) as ofile:
                with open(i) as ifile:
                    needs_save = fix_file(ifile, ofile, efile)

                if needs_save:
                    ofile.flush()
                    # keep owners/mode like original file
                    shutil.chown(ofile.name, user=i.owner(), group=i.group())
                    os.chmod(ofile.name, mode=ifile_stats.st_mode)
                    # atomic overwrite of existing file if all went well, the
                    # rename will disappear the tempfile's name, so have to
                    # stop the _closer from trying to unlink it.
                    os.rename(ofile.name, i)
                    ofile._closer.delete = False

            if fixlog:
                # update fixlog's mtime so this access log can be skipped next time
                fixlog.touch()


if __name__ == '__main__':
    cli()
