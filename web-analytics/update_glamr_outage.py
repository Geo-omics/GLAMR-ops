#!/usr/bin/env python3
"""
Generate a outage report for greatlakesomics.org from apache "combined" log
files.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta
from itertools import pairwise
import re
import sys

import matplotlib.pyplot
import pandas


# values below are times in seconds
DEFAULT_CUTOFF = 90
WEBAPP_CUTOFF = 300
PROBE_INTERVAL = 10


def read_logs():
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

    everything = []  # everuy timestamp
    hits = []  # non-probes only, hits from outside
    probes = []
    for i in args.logs:
        with open(i) as ifile:
            for lnum, line in enumerate(ifile, start=1):
                line = line.rstrip('\n')
                m = logpat.match(line)
                if m is None:
                    print(f'log parsing error in {ifile.name} at line {lnum}: '
                          f'{line}', file=sys.stderr)
                    continue

                dt = datetime.strptime(
                    m['timestamp'],
                    '[%d/%b/%Y:%H:%M:%S %z]'
                ).astimezone()

                if m['user_agent'].startswith('"kube-probe/'):
                    if args.plot:
                        probes.append(dt)

                    if args.webapp:
                        # don't keep probes in webapp mode
                        continue
                else:
                    hits.append(dt)

                everything.append(dt)
    with open('hits.txt', 'w') as ofile:
        for i in hits:
            ofile.write(f'{i}\n')
    return everything, hits, probes


def get_missed_probes(probes):
    """
    Turn list of probe timestamps into Series of missed probes
    """
    missed_timestamps = []
    probe_interval = timedelta(seconds=PROBE_INTERVAL)
    probes = sorted(probes)
    for a, b in pairwise(probes):
        if a == b:
            # ignore duplicates
            continue

        delay = (b - a) - probe_interval

        if delay.total_seconds() < 0:
            # negative lag is more than expected interval
            # probes coming too quickly, resetting
            delay = timedelta(0)

        missed_count = int(delay.total_seconds()) // PROBE_INTERVAL

        current_dt = a
        for i in range(1, missed_count + 1):
            current_dt = current_dt + probe_interval
            missed_timestamps.append(current_dt)

    return missed_timestamps


def frame_data(hits, missed):
    """
    Get our data into a DataFrame, indexed by every second

    hits: list of datetimes
    missed: list of datetimes (sorted, unique)
    """
    hits = sorted(hits)
    start = min(hits[0], probes[0])
    end = max(hits[-1], probes[-1])
    start = start.astimezone(end.tzinfo)  # potential daylight savings
    seconds = pandas.date_range(start=start, end=end, freq='S')
    df = pandas.DataFrame(
        {
            'miss': pandas.Series(
                [1] * len(missed),
                dtype=int,
                index=missed,
            ).reindex(seconds, fill_value=0),
            'hits': pandas.Series(
                Counter(hits),
                dtype=int,
            ).reindex(seconds, fill_value=0),
        },
        dtype=int,
        index=seconds,
    )
    return df


def draw_plot(miss_data, hits_data, start, title, res, filename):
    """
    Plot one figure with matplotlib

    miss_data, hits_data: Series
    start: the first datetime of the interval to be plotted
    title: str, figure title
    res: missed probe rate resolution, str
    filename: str, filename, but no directory
    """
    miss_data = miss_data[start <= miss_data.index]
    hits_data = hits_data[start <= hits_data.index]
    fig, ax = matplotlib.pyplot.subplots(1)
    ax.set_title(title)
    ax2 = ax.twinx()

    if hits_data.any():
        logy = False
    else:
        logy = False
    hits_data[hits_data == 0] = None
    hits_data.plot(ax=ax, logy=logy, style='-', color='C2', label='hits')

    if miss_data.any():
        logy = True
    else:
        logy = False
        # ax.set_ylim(ymin=0)
    miss_data[miss_data == 0] = None
    miss_data.plot(ax=ax2, logy=logy, color='C1',
                   label='missed probes')
    # ylim: rate goes to 1.0, add a bit more to ensure a 1.0 line is visible
    ax2.set_ylim(ymax=1.1)

    # Make a single legend for both axes
    li, la = ax.get_legend_handles_labels()
    li2, la2 = ax2.get_legend_handles_labels()
    ax.legend(li + li2, la + la2)
    ax.set_ylabel('hits $s^{-1}$')
    ax2.set_ylabel(f'probe failure rate\n(at {res} resolution)')

    # finish up
    fig.set_tight_layout(True)  # affects other figures below
    fig.set_size_inches(13, 3)  # affects other figures below
    outpath = f'{args.output_dir}/{filename}'
    fig.savefig(outpath)
    print(f'Plot saved to {outpath}')
    matplotlib.pyplot.close(fig=fig)


def plot_stuff(df):
    """
    Generate data points to be plotted and issue plotting commands.

    For missed probes' y-axis values: These are mean probe failure rate over a
    time-window.  The window size is determined by what the plot can resolve.
    So for the daily plot this is about one pixel per minute.  For a probe
    interval of 10s we get six probes per minute, so a window size of 6.
    Window size then scales proportional with temporal lenght of the plot.
    """
    # 1. the windows
    one_min = timedelta(minutes=1)  # resolution for daily plot
    ten_mins = timedelta(minutes=10)  # resolutionm for week
    one_hour = timedelta(hours=1)  # resolution for year or so

    # 2, expected number of probes in each window
    # (will divide the miss count to get failure rate)
    exp1m = 60 / PROBE_INTERVAL
    exp10m = (10 * 60) / PROBE_INTERVAL
    exp1h = (60 * 60) / PROBE_INTERVAL

    # 3. calculate the failure rate
    df['miss_1min'] = df['miss'].rolling(window=one_min, center=True).sum() / exp1m  # noqa: E501
    df['miss_10min'] = df['miss'].rolling(window=ten_mins, center=True).sum() / exp10m  # noqa: E501
    df['miss_1hour'] = df['miss'].rolling(window=one_hour, center=True).sum() / exp1h  # noqa: E501

    # 4. hits per second, averaged over window, for each resolution
    df['hits_s_1min'] = df['hits'].rolling(window=ten_mins, center=True).sum() / (5 * 60)  # noqa:E501
    df['hits_s_10min'] = df['hits'].rolling(window=one_hour, center=True).sum() / (60 * 60)  # noqa: E501
    df['hits_s_1hour'] = df['hits'].rolling(window=one_hour * 6, center=True).sum() / (6 * 60 * 60)  # noqa: E501

    df.to_csv('data.csv', sep='\t')
    now = pandas.Timestamp.now(tz=df.index[-1].tzinfo)
    last = df.index[-1]

    # 1. yesterday outage plotting
    day = pandas.Timedelta(days=1)
    if now - last <= day:
        end = now
        day_label = 'yesterday'
    else:
        end = last
        day_label = 'most recent day'

    start = (end - day).replace(hour=0, minute=0, second=0, microsecond=0)
    draw_plot(
        df['miss_1min'],
        df['hits_s_1min'],
        start,
        title=f'Outage since {day_label}',
        res='1 min',
        filename='outage_day.svg',
    )

    # 2. last week outage plotting
    week = pandas.Timedelta(days=7)
    if now - last <= week:
        end = now
        week_label = 'last 7 days'
    else:
        end = last
        week_label = 'most recent 7 days'
    start = (end - week).replace(hour=0, minute=0, second=0, microsecond=0)
    draw_plot(
        df['miss_10min'],
        df['hits_s_10min'],
        start,
        title=f'Outage {week_label}',
        res='10 mins',
        filename='outage_week.svg',
    )

    # 3. all-time outage plotting
    draw_plot(
        df['miss_1hour'],
        df['hits_s_1hour'],
        df.index[0],
        title='All-time outage',
        res='1 h',
        filename='outage_all.svg',
    )


if __name__ == '__main__':
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument(
        'logs',
        nargs='+',
        help='apache access log files, combined format',
    )
    argp.add_argument(
        '-o', '--output-dir',
        default='.',
        help='Directory to which plots will be save',
    )
    argp.add_argument(
        '--webapp',
        action='store_true',
        help=f'Webapp-only mode.  Ignore webserver probes and report outtages '
             f'longer than {WEBAPP_CUTOFF}s.  In normal mode webserver probes '
             f'are included in the analysis and outages larser than '
             f'{DEFAULT_CUTOFF}s are reported.',
    )
    argp.add_argument(
        '--plot',
        action='store_true',
        help='Make plots of hits and missing probes',
    )
    args = argp.parse_args()

    if args.webapp:
        cutoff = WEBAPP_CUTOFF
    else:
        cutoff = DEFAULT_CUTOFF

    everything, hits, probes = read_logs()
    print(f'Got {len(hits)} hits, {len(probes)} probes')
    missed = get_missed_probes(probes)
    data = frame_data(hits, missed)
    print(f'Total time interval: {len(data.index)} seconds')
    if args.plot:
        plot_stuff(data)

    shown_msg = False
    for a, b in pairwise(sorted(everything)):
        diff = int((b - a).total_seconds())
        if diff > cutoff:
            if not shown_msg:
                print('Probe gaps:')
                shown_msg = True
            print(f'{diff:>5}s: {a} ... {b}')
