"""
apache2 combined log fixing, parsing, processing
"""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import dataclasses
from datetime import date as datetime_date, datetime, timedelta
import gzip as stdlib_gzip
from itertools import chain
import json
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory

from glamr_ops import get_configuration
from glamr_ops.utils import gzip


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
    hits_parser = subs.add_parser('import-hits', help='Compile hits from logs')
    hits_parser.add_argument(
        'logs',
        nargs='*', type=Path,
        help='Path to log files to process.'
    )
    hits_parser.add_argument(
        '--hits-data',
        help='Path to the hits data directory',
    )
    args = argp.parse_args()
    match args.cmd:
        case 'fix': fix_logs(*args.paths)
        case 'import-hits':
            LogData.update_from_logfiles(*args.logs, data_dir=args.hits_data)
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


class LogEntries:
    """
    A generator to read and parse apache 2 combined log file

        path: Path to log file
        skip [int]:
            Skip this many initial lines.

    This yields instances of ApacheLogentry.
    """
    def __init__(self, path, skip=0):
        self.path = Path(path)
        self.skip = skip
        self.total_lines = None

    def __iter__(self):
        print(f'Reading {self.path.name} ...', end=' ', flush=True)

        with ExitStack() as estack:
            if self.path.suffix == '.gz':
                ifile = estack.enter_context(stdlib_gzip.open(self.path, 'rt'))
            else:
                ifile = estack.enter_context(open(self.path))

            for lnum, line in enumerate(ifile, start=1):
                if lnum <= self.skip:
                    continue

                errmsg = (f'log parsing error in {ifile.name} at line {lnum}: {{msg}}\n'
                          f'bad line: {line}')

                try:
                    yield ApacheLogEntry.from_line(line)
                except BadApacheLog as e:
                    raise RuntimeError(errmsg.format(msg=e)) from e

        if self.skip:
            print(f'{lnum - self.skip}/{lnum} [OK]')
        else:
            print(f'{lnum} [OK]')
        self.total_lines = lnum


class LogData:
    """ Count of hits between start and end date at one second resolution """
    data_file_pat = re.compile(r'(?P<year>[0-9]{4})-(?P<month>[0-9]{2}).json($|.gz)')

    def __init__(self, first_day=None, last_day=None, data_dir=None):
        if isinstance(first_day, str):
            first_day = datetime_date.fromisoformat(first_day)
        if isinstance(last_day, str):
            last_day = datetime_date.fromisoformat(last_day)

        if data_dir is None:
            self.data_dir = Path(self.get_default_data_dir())
        else:
            self.data_dir = Path(data_dir)

        if first_day and last_day and last_day < first_day:
            raise ValueError('last day must come after first day (or be the same)')

        self.first_day = first_day
        self.last_day = last_day
        self.load_data()
        # If needed, set first/last days from data
        if self.first_day is None and self.hits:
            self.first_day = list(self.hits.keys())[0]
        if self.last_day is None and self.hits:
            self.last_day = list(self.hits.keys())[-1]

    @classmethod
    def get_default_data_dir(cls):
        return Path(get_configuration()['VAR_DIR']) / 'hits.data'

    @classmethod
    def update_from_logfiles(cls, *logfiles, data_dir=None):
        """ Implement the CLI hits sub-command """
        if data_dir:
            data_dir = Path(data_dir)
        else:
            data_dir = cls.get_default_data_dir()

        if not logfiles:
            log_dir = Path(get_configuration()['VAR_DIR']) / 'daily-logs'
            last_update = cls.get_last_modified().timestamp()
            logfiles = [
                path
                for _, path
                in list_log_files(log_dir)
                if path.stat().st_mtime >= last_update
            ]
        # divide logfile into monthly batches
        # A log file may also have data from previous day
        batches = {}
        for i in logfiles:
            day = get_date(i)
            prev_day = day - timedelta(days=1)
            for month in {(day.year, day.month), (prev_day.year, prev_day.month)}:
                if month not in batches:
                    batches[month] = []
                batches[month].append(i)

        objs = []
        for (year, month), logfile_batch in batches.items():
            first_day = datetime_date(year, month, 1)
            last_day = datetime_date(
                year if month < 12 else year + 1,
                (month % 12) + 1,
                1
            ) - timedelta(days=1)  # 1st day of next month minus 1 day
            obj = cls(first_day, last_day, data_dir=data_dir)
            obj.import_log_files(*logfile_batch)
            obj.save_data()
            objs.append(obj)
        return objs

    @classmethod
    def get_last_modified(cls, data_dir=None):
        """
        Get timestamp when data base was last modified

        Returns datetime if at least one data file is present, else returns None.
        """
        if data_dir is None:
            data_dir = cls.get_default_data_dir()

        last = None
        for (y, m), path in cls.list_all_data_files(data_dir):
            mtime = path.stat().st_mtime
            if last is None or mtime > last:
                last = mtime
        return datetime.fromtimestamp(last).astimezone()

    @classmethod
    def list_all_data_files(cls, data_dir=None):
        """ helper listing *all* data files, sorted by year/month """
        if data_dir is None:
            data_dir = cls.get_default_data_dir()

        files = {}
        for i in data_dir.iterdir():
            if m := cls.data_file_pat.match(i.name):
                key = (int(m['year']), int(m['month']))
                if key in files:
                    raise RuntimeError(f'there are two files for year/month: {key}')
                files[key] = i
        return sorted(files.items())

    def get_data_files(self):
        """
        List data files' paths

        Return list of tuples ((year, month), Path)
        """
        files = []
        for (y, m), path in self.list_all_data_files(data_dir=self.data_dir):
            if self.first_day:
                if y < self.first_day.year:
                    continue  # file too old
                if m < self.first_day.month:
                    continue  # file too old

            if self.last_day:
                if self.last_day.year < y:
                    continue  # file too recent
                if self.last_day.month < m:
                    continue  # file too recent

            files.append(((y, m), path))
        return files

    def get_data_file(self, year, month, compressed=True):
        """ Get path to data file for given month """
        # cf. LogData.data_file_pat
        stem = f'{year}-{month:02d}'
        suf = '.json.gz' if compressed else '.json'
        return (self.data_dir / stem).with_suffix(suf)

    @staticmethod
    def encode_counts(counts):
        """
        Encode per-second hit counts
        """
        def as_str():
            prev_sec = -1
            for sec, count in counts.items():
                step = sec - prev_sec
                if step == 1:
                    yield str(count)
                elif step > 1:
                    # number of zeros, negated
                    yield str(-(step - 1))
                    yield str(count)
                else:
                    raise RuntimeError('bug, seconds should increase monotonically')
                prev_sec = sec
        return ' '.join(as_str())

    @staticmethod
    def decode_counts(count_data):
        """
        Decode hits counts

        Reverses encode_counts
        """
        def seconds_count():
            cur_sec = -1
            for item in count_data.split(' '):
                item = int(item)
                if 0 < item:
                    # normal count
                    cur_sec += 1
                    yield cur_sec, item
                elif item < 0:
                    # gap
                    cur_sec += -item
                else:
                    raise ValueError('bug, got a zero')
        return dict(seconds_count())

    @staticmethod
    def try_int(value):
        """
        helper to convert string into int, if possible, without raising

        Needed for importing json data, as json.dump converts integer dict keys
        into strings.
        """
        try:
            return int(value)
        except ValueError:
            return value

    def load_data(self):
        """
        Load data from data files.

        Usually called at instantiation.  This sets the import_state, hits, and
        loaded_data_files attributes.
        """
        self.hits = {}
        self.import_state = {}
        self.loaded_data_files = {}
        for (y, m), path in self.get_data_files():
            if path.suffix == '.gz':
                ifile = stdlib_gzip.open(path, 'rt')
            else:
                ifile = path.open()
            with ifile as ifile:
                print(f'Loading data for {y}/{m}... ', end='', flush=True)
                data = json.load(ifile)
                for logfile_name, line_count in data['import'].items():
                    # TODO: temp code saved whole paths, should just be filename
                    # remove after re-importing logs
                    logfile_name = Path(logfile_name).name
                    if line_count0 := self.import_state.get(logfile_name):
                        if line_count0 != line_count:
                            raise RuntimeError(
                                f'import line count inconsistency: {path=} '
                                f'{logfile_name=} {line_count0=} {line_count=}'
                            )
                    else:
                        self.import_state[logfile_name] = line_count

                for date, single_day_data in data['hits'].items():
                    date = datetime_date.fromisoformat(date)
                    if self.first_day and date < self.first_day:
                        continue
                    if self.last_day and self.last_day < date:
                        continue
                    self.hits[date] = {
                        self.try_int(status): self.decode_counts(counts_data)
                        for status, counts_data
                        in single_day_data.items()
                    }
            self.loaded_data_files[(y, m)] = path
            print('[OK]')

    def save_data(self):
        # 1. get all months for which we have data
        months = sorted(set((i.year, i.month) for i in self.hits.keys()))
        for year, month in months:
            print(f'Saving {year}/{month},', end=' ')
            if data_file := self.loaded_data_files.get((year, month)):
                print(f'replacing {data_file.name} ...', end=' ', flush=True)
            else:
                data_file = self.get_data_file(year, month)
                if data_file.is_file():
                    raise FileExistsError(
                        f'should not overwrite a file that was not loaded: {data_file}'
                    )

            save_data = {}
            save_data['import'] = {
                str(logfile): line_count
                for logfile, line_count in self.import_state.items()
            }

            hits = {}
            for date, data in self.hits.items():
                if date.year != year or date.month != month:
                    continue
                date = date.isoformat()
                hits[date] = {}
                for status, counts in data.items():
                    hits[date][status] = self.encode_counts(counts)
            save_data['hits'] = hits

            with TemporaryDirectory(dir=self.data_dir) as tmpd:
                tmp_file = Path(tmpd) / data_file.name
                if data_file.suffix == '.gz':
                    tmp_file = tmp_file.with_suffix('')
                with tmp_file.open('w') as ofile:
                    json.dump(save_data, ofile, indent=4)
                    ofile.write('\n')
                    ofile.flush()
                if data_file.suffix == '.gz':
                    tmp_file = gzip(tmp_file)
                tmp_file.rename(data_file)  # atomic replacement
            print('[OK]')

    def import_log_files(self, *logfiles):
        log_iters = [
            LogEntries(path, skip=self.import_state.get(path.name, 0))
            for path in logfiles
        ]
        hits = self.get_hits(chain.from_iterable(log_iters))
        for date, hits_per_status in hits.items():
            for status, counts in hits_per_status.items():
                for sec, count in counts.items():
                    if date not in self.hits:
                        self.hits[date] = {}
                    if status not in self.hits[date]:
                        self.hits[date][status] = {}
                    if sec in self.hits[date][status]:
                        self.hits[date][status][sec] += count
                        print(f'[DEBUG] same second {date=} {status=} {sec=} '
                              f'{self.hits[date][status][sec]=} {count=}')
                        # raise RuntimeError(
                        #     f'DUPE? {date=} {status=} {sec=} '
                        #     f'{self.hits[date][status][sec]=}'
                        # )
                    else:
                        self.hits[date][status][sec] = count

        for i in log_iters:
            if i.total_lines is None:
                raise RuntimeError('log entry iterator is not exhaused? {vars(i)=}')
            if i.path in self.import_state:
                raise RuntimeError(
                    f'duplicate log import? {i.path=} {self.import_state=}'
                )
            self.import_state[i.path.name] = i.total_lines

    def get_hits(self, log_entries):
        """
        Convert log entries into hits per second time series

        log_entries:  Iterable over log entries as made by LogEntries()

        Returns hits time series data structure
        """
        # 1. Collect and count hits per day per status per second
        hits0 = defaultdict(lambda: defaultdict(Counter))
        for entry in log_entries:
            dt = entry.timestamp  # datetime
            date = dt.date()
            if self.first_day and date < self.first_day:
                # too old
                continue
            if self.last_day and self.last_day < date:
                # too recent
                continue

            seconds = dt.hour * 3600 + dt.minute * 60 + dt.second

            if entry.user_agent.startswith('kube-probe/'):
                if 200 <= entry.status <= 299:
                    hits0[date]['probe'][seconds] += 1
                elif 400 <= entry.status:
                    hits0[date]['probe-fail'][seconds] += 1
                continue

            else:
                hits0[date][entry.status][seconds] += 1

        # 2. Sort by day/status
        sorted_hits = {}
        for date, day_hits in sorted(hits0.items(), key=lambda x: x[0]):
            sorted_day_hits = {}
            for status, seconds_data in sorted(day_hits.items(), key=lambda x: str(x[0])):  # noqa:E501
                sorted_day_hits[status] = \
                    dict(sorted(seconds_data.items(), key=lambda x: x[0]))
            sorted_hits[date] = sorted_day_hits

        return sorted_hits


def fix_file(ifile, ofile, efile):
    """
    Fix a log file -- helper

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


def fix_logs(*paths, redo=False):
    """
    Fix given apache log file(s)

    redo [bool]:
        when processing a whole directory a fix.log will be kept and its
        modtime will be consulted to determine if a file got fixed before and
        not be fixed again.  Setting redo to True will skip this check.

    Implement the CLI fix sub-command but can also be called via "glamr_ops.log
    retrieve"

    Returns True if some fixes got applied and False otherwise.
    """
    if not paths:
        # stdin/out mode
        return fix_file(sys.stdin, sys.stdout, sys.stderr)

    ret_val = False
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
            if ifile_stats.st_mtime <= last_check and not redo:
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
                    ret_val = True

            if fixlog:
                # update fixlog's mtime so this access log can be skipped next time
                fixlog.touch()

    return ret_val


class InvalidLogFileName(Exception):
    pass


access_log_pat = re.compile(r'^access\.(?P<date>[0-9]{8}).log(.gz)?$')


def get_date(path):
    """
    Get date for given log file

    Log file should be named access.YYYMMDD.log[.gz]
    """
    path = Path(path)
    if m := access_log_pat.match(path.name):
        # parse as YYYYMMDD
        year = int(m['date'][:4])
        month = int(m['date'][4:6])
        day = int(m['date'][6:])

        try:
            return datetime_date(year, month, day)
        except ValueError as e:
            raise InvalidLogFileName(f'bad date in filename: {path} -- {e}') from e
    else:
        raise InvalidLogFileName(f'invalid log filename: {path}')


def list_log_files(dirpath, suffix=None):
    """
    Get list of apache access log files in given directory.

    Returns list of tuples (date, pathlib.Path) sorted by date
    """
    if suffix is None:
        allowed_suffices = ['.log', '.log.gz']
    elif isinstance(suffix, str):
        allowed_suffices = [suffix]
    else:
        # assume a list already
        allowed_suffices = suffix

    items = []
    for i in Path(dirpath).iterdir():
        for j in allowed_suffices:
            if i.name.endswith(j):
                break
        else:
            # invalid suffix
            continue

        try:
            items.append((get_date(i), i))
        except InvalidLogFileName:
            pass

    # sort by date
    return sorted(items)


if __name__ == '__main__':
    cli()
