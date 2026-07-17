"""
apache2 combined log fixing, parsing, processing
"""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
import dataclasses
from datetime import date as datetime_date, datetime, time as datetime_time, timedelta
import gzip as stdlib_gzip
from itertools import chain
import json
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory

import pandas

from glamr_ops import get_configuration
from glamr_ops.utils import gzip, sorted_keys


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
    hits_parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run, existing data files are not overwritten.',
    )
    plot_parser = subs.add_parser('plot', help='Make plots')
    plot_parser.add_argument(
        'fromto',
        nargs='*',
        help='Not providing these implies auto-mode (used for the cron job).  '
        'If two iso-formatted date or times are given then these are start and'
        ' end point respectively.  If one argument is given, and it is a date '
        'then that day\'s data is plotted.  Alternatively a time and a '
        'duration e.g. "10m" can be given, in which case a time interval of '
        'that length with the given time at the midpoint will be plotted.',
    )
    plot_parser.add_argument(
        '--hits-data',
        help='Path to the hits data directory',
    )
    plot_parser.add_argument(
        '--outdir', help='Output directory',
    )
    plot_parser.add_argument(
        '--format',
        default=LogData.default_plot_fmt,
        help='Output files format.  Provide the a file suffix supported by '
             'matplotlib\'s Figure.savefig(). Defaults to {LogData.default_plot_fmt}',
    )
    args = argp.parse_args()
    match args.cmd:
        case 'fix': fix_logs(*args.paths)
        case 'import-hits':
            LogData.update_from_logfiles(
                *args.logs,
                data_dir=args.hits_data,
                dry_run=args.dry_run
            )
        case 'plot':
            if args.fromto:
                arg1, *arg2 = args.fromto
                arg2 = arg2[0] if arg2 else None
                try:
                    arg1 = datetime_date.fromisoformat(arg1)
                except ValueError as e1:
                    try:
                        arg1 = datetime.fromisoformat(arg1).astimezone()
                    except ValueError as e2:
                        try:
                            arg1 = datetime_time.fromisoformat(arg1)
                        except ValueError as e3:
                            argp.error(
                                f'first positional argument must be iso-formatted '
                                f'date, time, or datetime: {e1}/{e2}/{e3}'
                            )
                        else:
                            # time -> datetime
                            arg1 = LogData.d2dt(datetime.today(), arg1)

                if arg2:
                    try:
                        arg2 = datetime_date.fromisoformat(arg2)
                    except ValueError as e1:
                        try:
                            arg2 = datetime_time.fromisoformat(arg2)
                        except ValueError as e2:
                            try:
                                arg2 = datetime.fromisoformat(arg2).astimezone()
                            except ValueError as e3:
                                pat = re.compile(r'^([0-9]+)([hms])$')
                                units = {'h': 'hours', 'm': 'minutes', 's': 'seconds'}
                                if m := pat.match(arg2):
                                    if isinstance(arg1, datetime):
                                        amount, unit = m.groups()
                                        amount = int(amount)
                                        unit = units[unit]
                                        half_duration = timedelta(**{unit: amount}) / 2
                                        arg2 = arg1 + half_duration
                                        arg1 = arg1 - half_duration
                                        arg1 = arg1.replace(microsecond=0)
                                        arg2 = arg2.replace(microsecond=0)
                                    else:
                                        argp.error(
                                            'if the second positional argument is a '
                                            'duration, then the first must be a time '
                                            'or datetime'
                                        )
                                else:
                                    argp.error(
                                        f'second positional argument, if provided, '
                                        f'must be iso-formatted date, time, or '
                                        f'datetime: {e1}/{e2}/{e3} or a duration, '
                                        f'e.g.: 30s / 10m / 2h'
                                    )
                        else:
                            # time -> datetime
                            arg2 = LogData.d2dt(datetime.today(), arg2)
                        if not isinstance(arg1, datetime):
                            argp.error(
                                'if the first positional argument is a date, then the '
                                'second one, if given, must also be a date'
                            )
                    else:
                        # arg2 is date
                        if isinstance(arg1, datetime):
                            argp.error(
                                'if the second positional argument is a date, then '
                                'first one must be a date as well'
                            )
                        # date->datetime first day midnight to last second of other day
                        arg1 = datetime(arg1.year, arg1.month, arg1.day).astimezone()
                        arg2 = datetime(arg2.year, arg2.month, arg2.day, 23, 59, 59)
                        arg2 = arg2.astimezone()
                else:
                    # get arg2 default value if needed
                    if type(arg1) == datetime_date:
                        # the given day from 00:00:00 to 23:59:59
                        arg1 = datetime(arg1.year, arg1.month, arg1.day).astimezone()
                        arg2 = arg1 + timedelta(days=1) - timedelta(seconds=1)
                    else:
                        # default to 1-hour interval
                        halfhour = timedelta(hours=1) / 2
                        arg2 = arg1 + halfhour
                        arg1 = arg1 - halfhour
                if arg2 <= arg1:
                    argp.error('date/time of first positional argument must be earlier '
                               'than the second argument')

                logs = LogData(
                    first_day=arg1.date(),
                    last_day=arg2.date(),
                    data_dir=args.hits_data,
                )
                logs.plot(arg1, arg2, outdir=args.outdir, format=args.format)
            else:
                # auto-mode for cron job
                logs = LogData(data_dir=args.hits_data)
                logs.plot_yesterday(outdir=args.outdir, format=args.format)
                logs.plot_week(outdir=args.outdir, format=args.format)
                logs.plot_30days(outdir=args.outdir, format=args.format)
                logs.plot_all_years(outdir=args.outdir, format=args.format)
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
    plot_width_in = 13  # plot width in inches
    plot_height_in = 3  # plot height in inches
    plot_dpi = 100  # DPI for plot
    default_plot_fmt = 'png'

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
    def update_from_logfiles(cls, *logfiles, data_dir=None, dry_run=False):
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
            if obj.import_log_files(*logfile_batch):
                obj.save_data(dry_run=dry_run)
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

    @property
    def start(self):
        """ Get first timestamp in the data """
        for day, data in self.hits.items():
            break
        else:
            raise ValueError('no data loaded')
        first_sec = None
        for status, counts in data.items():
            for sec in counts.keys():
                if first_sec is None or sec < first_sec:
                    first_sec = sec
                break

        if first_sec is None:
            raise RuntimeError('bad data? the status counts should not be empty')
        return self.d2dt(day, first_sec)

    @property
    def end(self):
        """ Get last timestamp in the data """
        if not self.hits:
            raise ValueError('no data loaded')
        for day, data in self.hits.items():
            continue
        last_sec = None
        for status, counts in data.items():
            for sec in counts.keys():
                if last_sec is None or last_sec < sec:
                    last_sec = sec

        if last_sec is None:
            raise RuntimeError('bad data? the status counts should not be empty')
        return self.d2dt(day, last_sec)

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
        status_avail = set()
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
                    status_avail.update(self.hits[date].keys())

            self.loaded_data_files[(y, m)] = path
            self.status_avail = sorted(status_avail, key=str)
            print('[OK]')

    def save_data(self, dry_run=False):
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
                if not dry_run:
                    tmp_file.rename(data_file)  # atomic replacement
            print('[OK]')

    def import_log_files(self, *logfiles):
        """
        Import data from given log files

        Returns True if some new data was imported and False otherwise
        """
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
                        # An entry for this second already exists.  Assuming
                        # the skip count from the inport state is correct and
                        # the log file did not get corrupted, then these hits
                        # were not yet counted.
                        # TODO: remove the debug message after some time, once
                        # we're more convinced that this is all normal
                        print(f'[DEBUG] same second {date=} {status=} {sec=} '
                              f'was {self.hits[date][status][sec]=}, adding {count=}')
                        self.hits[date][status][sec] += count
                    else:
                        self.hits[date][status][sec] = count

        # maintain dictionary order since new keys may have been added (at end
        # of the respective dicts)
        self.hits = sorted_keys(self.hits)
        for date in self.hits.keys():
            # sort statuses
            self.hits[date] = sorted_keys(self.hits[date], lambda x: str(x))
            for status in self.hits[date].keys():
                # sort seconds
                self.hits[date][status] = sorted_keys(self.hits[date][status])

        for i in log_iters:
            if i.total_lines is None:
                raise RuntimeError('log entry iterator is not exhaused? {vars(i)=}')
            if i.path in self.import_state:
                raise RuntimeError(
                    f'duplicate log import? {i.path=} {self.import_state=}'
                )
            self.import_state[i.path.name] = i.total_lines

        return bool(hits)

    def get_hits(self, log_entries):
        """
        Convert log entries into hits per second time series

        log_entries:  Iterable over log entries as made by LogEntries()

        Returns hits time series data structure
        """
        # 1. Collect and count hits per day per status per second
        hits = defaultdict(lambda: defaultdict(Counter))
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
                    hits[date]['probe'][seconds] += 1
                elif 400 <= entry.status:
                    hits[date]['probe-fail'][seconds] += 1
                continue

            else:
                hits[date][entry.status][seconds] += 1

        # 2. Sort by day/status/seconds
        hits = sorted_keys(hits)
        for date in hits.keys():
            hits[date] = sorted_keys(hits[date], key=lambda x: str(x))
            for status in hits[date].keys():
                hits[date][status] = sorted_keys(hits[date][status])

        return hits

    @staticmethod
    def counts2list(index, counts_per_second):
        """ turn counts per sec dict into a list """
        for sec, timestamp in enumerate(index):
            yield counts_per_second.get(sec, 0)

    @staticmethod
    def d2dt(date, time=0):
        """
        Utility to make a datetime from a date and number of seconds into the day

        time:
            Time of the day, if an int, then number of seconds, other wise a
            datetime.time object.
        """
        if isinstance(time, int):
            seconds = time
        else:
            seconds = time.hour * 3600 + time.minute * 60 + time.second
        t = datetime(date.year, date.month, date.day).astimezone()
        return t + timedelta(seconds=seconds)

    def by_status(self, status, start=None, end=None):
        """
        Generate counts for given status

        This yields triplets (day, seconds, count)
        """
        if start:
            start_date = start.date()
            start_sec = start.hour * 3600 + start.minute * 60 + start.second
        else:
            start_date = start_sec = None

        if end:
            end_date = end.date()
            end_sec = end.hour * 3600 + end.minute * 60 + end.second
        else:
            end_date = end_sec = None

        for date, daydata in self.hits.items():
            # get data for all seconds unless we're on the first or last day
            min_sec = 0
            max_sec = 86400
            if start_date:
                if date < start_date:
                    continue
                if start_date == date:
                    min_sec = start_sec

            if end_date:
                if end_date < date:
                    break
                if date == end_date:
                    max_sec = end_sec

            for sec, counts in daydata.get(status, {}).items():
                if sec < min_sec:
                    continue
                if max_sec < sec:
                    break
                yield date, sec, counts

    def as_series(self, status, index=None):
        """ Get pandas Series from given status data and interval """
        if index is None:
            index = pandas.date_range(
                start=self.start,
                end=self.end,
                freq='S',
                name='timestamp',
            )

        timestamped_counts = (
            (self.d2dt(day, sec), count)
            for day, sec, count
            in self.by_status(status, start=index[0], end=index[-1])
        )

        def counts():
            """
            Concurrently iterate over index and count data, insert appropriate
            missing values as needed
            """
            hold_counts = False
            tstamp = count = None
            for i in index:
                if hold_counts:
                    if i == tstamp:
                        yield count
                        hold_counts = False
                    else:
                        yield 0
                else:
                    for tstamp, count in timestamped_counts:
                        if tstamp < i:
                            # counts need to catch up to index
                            continue
                        elif tstamp == i:
                            yield count
                        else:
                            # index needs to catch up to counts
                            yield 0
                            hold_counts = True
                        break
                    else:
                        # all data younger than index or end of data, but index
                        # continues
                        yield 0
                        hold_counts = True

        return pandas.Series(counts(), index, name=str(status))

    def as_dataframe(self, start, end):
        if start is None:
            start = self.start
        elif isinstance(start, str):
            start = datetime.fromisoformat(start).astimezone()
        if end is None:
            end = self.end
        elif isinstance(end, str):
            end = datetime.fromisoformat(end).astimezone()

        print('Compiling dataframe... ', end='', flush=True)
        index = pandas.date_range(start=start, end=end, freq='s', name='timestamp')
        df = pandas.DataFrame(index=index, dtype=pandas.Int64Dtype())
        for status in self.status_avail:
            df[str(status)] = self.as_series(status, index)
            print(status, end=' ', flush=True)
        print('[OK]')
        return df

    @classmethod
    def get_resampling_rate(cls, total_seconds, verbose=False):
        """
        Calculate optimal integral-hour/min/sec re-sampling rate

        The rate is how many seconds each dot of the plot represents.

        Returns a tuple (seconds, human_readable_text)
        """
        dots_target = cls.plot_dpi * cls.plot_width_in
        if verbose:
            print(f'[DEBUG] calc re-sampling: {dots_target=} {total_seconds=}')

        best_diff = None
        best_rate = None
        for unit, secs in [('s', 1), ('m', 60), ('h', 3600)]:
            for i in range(1, 30):
                if unit in ('s', 'm'):
                    if not (60 / i).is_integer():
                        # not an integral part of larger unit
                        continue
                else:
                    # hours
                    if not (24 / i).is_integer():
                        # not an integral part of day
                        continue

                rate = secs * i
                dots_needed = total_seconds / rate
                txt = f'{i}{unit}'
                diff = abs(dots_target - dots_needed)

                if verbose:
                    print(f'[DEBUG] {unit=} {i=} {dots_needed=} {diff=}', end='  ')

                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    best_rate = (rate, txt)
                    if verbose:
                        print(f'{best_rate=}')
                elif verbose:
                    print()

        return best_rate

    def _plot(self, df):
        """
        Do common plotting stuff
        """
        # 0. resampling
        # We're aiming for one datapoint per dot
        rate = round(len(df) / (self.plot_dpi * self.plot_width_in))
        rate, rate_txt = self.get_resampling_rate(len(df))
        print(f'Re-sampling at rate {rate}s / {rate_txt} ... ', end='', flush=True)
        df = df.resample(timedelta(seconds=rate)).mean()
        print('[OK]')

        # 1. sum data into four columns
        good_cols = [
            str(i) for i in self.status_avail
            if isinstance(i, int) and 200 <= i < 399 and str(i) in df.columns
        ]
        bad_cols = [
            str(i) for i in self.status_avail
            if isinstance(i, int) and 400 <= i < 499 and str(i) in df.columns
        ]
        err_cols = [
            str(i) for i in self.status_avail
            if isinstance(i, int) and 500 <= i < 599 and str(i) in df.columns
        ]
        other_cols = [
            i for i in df.columns
            if i not in good_cols + bad_cols + err_cols
        ]
        print('Summing columns by category... ', end='', flush=True)
        df['good hits'] = df[good_cols].sum(axis=1)
        df['bad hits'] = df[bad_cols].sum(axis=1)
        df['errors'] = df[err_cols].sum(axis=1)
        df['other'] = df[other_cols].sum(axis=1)
        print('[OK]')

        # 2. remove original columns
        for i in df.columns:
            if i not in ['good hits', 'bad hits', 'errors', 'other']:
                del df[i]

        # 3. assign colors to columns
        color = (
            'C2',  # green for good hits
            'C1',  # orange for bad
            'C3',  # red for errors
            'C7',  # grey for others
        )
        ax = df.plot(
            logy=True,
            color=color,
            linewidth=0.5,
        )
        ax.set_ylabel('hits per second')
        ax.figure.set_tight_layout(True)
        ax.figure.set_size_inches(self.plot_width_in, self.plot_height_in)
        ax.figure.set_dpi(self.plot_dpi)
        return ax, rate_txt

    def plot(self, start, end, outdir=None, format=default_plot_fmt):
        """ Plot given interval """
        if start is None:
            start = self.start
        elif isinstance(start, str):
            start = datetime.fromisoformat(start).astimezone()
        if end is None:
            end = self.end
        elif isinstance(end, str):
            end = datetime.fromisoformat(end).astimezone()

        print(f'Plot for {start} to {end} ...')
        df = self.as_dataframe(start, end)
        print(f'There is data for {len(df)} seconds.')
        print(df.describe())

        ax, rate_txt = self._plot(df)
        ax.set_title(f'Hits from {start} to {end} at {rate_txt} resolution')
        outfile = Path(outdir or '.') / f'apache_log_plot.{format}'
        print('Plotting... ', end='', flush=True)
        ax.figure.savefig(outfile)
        print(f'saved as: {outfile} [OK]')

    def plot_year(self, year=None, outdir=None, format=default_plot_fmt):
        if year is None:
            year = self.last_day.year

        start = datetime(year, 1, 1).astimezone()
        end = datetime(year + 1, 1, 1).astimezone() - timedelta(seconds=1)

        print(f'Plot for {start} to {end} ...')
        df = self.as_dataframe(start, end)

        ax, rate_txt = self._plot(df)
        ax.set_title(f'Hits for {year} at {rate_txt} resolution')
        outfile = Path(outdir or '.') / f'{year}.{format}'
        print('Plotting... ', end='', flush=True)
        ax.figure.savefig(outfile)
        print(f'saved as: {outfile} [OK]')

    def plot_month(self, year=None, month=None, outdir=None, format=default_plot_fmt):
        if month is None and month is not None:
            raise ValueError('need a year if month is given')
        if year is None:
            year = self.last_day.year
        if month is None:
            month = self.last_day.month

        start = datetime(year, month, 1).astimezone()
        end = datetime(
            year + 1 if month == 12 else year,
            (month + 1) % 12,
            1
        ).astimezone() - timedelta(seconds=1)

        print(f'Plot for {start} to {end} ...')
        df = self.as_dataframe(start, end)

        ax, rate_txt = self._plot(df)
        ax.set_title(f'Hits for {year}/{month} at {rate_txt} resolution')
        outfile = Path(outdir or '.') / f'{year}-{month:02d}.{format}'
        print('Plotting... ', end='', flush=True)
        ax.figure.savefig(outfile)
        print(f'saved as: {outfile} [OK]')

    def plot_30days(self, outdir=None, format=default_plot_fmt):
        """ Plot last 30 days """
        start = self.d2dt(datetime_date.today()) - timedelta(days=30)
        end = datetime.now().astimezone()
        print(f'Plot for {start} to {end} ...')
        df = self.as_dataframe(start, end)

        ax, rate_txt = self._plot(df)
        ax.set_title(f'Hits for last 30 days at {rate_txt} resolution')
        outfile = Path(outdir or '.') / f'month.{format}'
        print('Plotting... ', end='', flush=True)
        ax.figure.savefig(outfile)
        print(f'saved as: {outfile} [OK]')

    def plot_week(self, outdir=None, format=default_plot_fmt):
        """ Plot for last seven days """
        start = self.d2dt(datetime_date.today()) - timedelta(days=7)
        end = datetime.now().astimezone()
        print(f'Plot for {start} to {end} ...')
        df = self.as_dataframe(start, end)

        ax, rate_txt = self._plot(df)
        ax.set_title(f'Hits for last week at {rate_txt} resolution')
        outfile = Path(outdir or '.') / f'week.{format}'
        print('Plotting... ', end='', flush=True)
        ax.figure.savefig(outfile)
        print(f'saved as: {outfile} [OK]')

    def plot_yesterday(self, outdir=None, format=default_plot_fmt):
        """ Plot for all of yesterday until latest data """
        start = self.d2dt(datetime_date.today()) - timedelta(days=1)
        print(f'Plot for {start} to {self.end} ...')
        df = self.as_dataframe(start, self.end)

        ax, rate_txt = self._plot(df)
        ax.set_title(f'Hits since yesterday at {rate_txt} resolution')
        outfile = Path(outdir or '.') / f'yesterday.{format}'
        print('Plotting... ', end='', flush=True)
        ax.figure.savefig(outfile)
        print(f'saved as: {outfile} [OK]')

    def plot_all_years(self, outdir=None, format=default_plot_fmt):
        """ Ensure yearly plots exists """
        for year in sorted(set(day.year for day in self.hits)):
            outfile = Path(outdir or '.') / f'{year}.{format}'
            if outfile.is_file():
                plot_mt = datetime.fromtimestamp(outfile.stat().st_mtime).astimezone()
                data_mt = None
                for (y, _), path in self.loaded_data_files.items():
                    # get most recent modtime for this year's data
                    mt = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
                    if data_mt is None or data_mt < mt:
                        data_mt = mt
                if data_mt < plot_mt:
                    # existing file is up-to-date
                    print(f'Is up-to-date: {outfile}')
                    continue

            self.plot_year(year, outdir=outdir, format=format)


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
