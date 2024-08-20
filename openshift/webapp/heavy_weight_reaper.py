#!/usr/bin/env python3
from datetime import datetime
import os
from signal import SIGHUP, SIGTERM
from time import sleep, monotonic

import uwsgi

VERBOSE = False
LOG = 'reaper.log'
MAX_MEMORY = 1_000_000_000
WAIT_TIME = 60


logfile = open(LOG, 'a')


def log(*args):
    print(f'[{datetime.now()}]', *args, flush=True, file=logfile)


retirees = {}

log(f'({__file__}) pid:{os.getpid()} starting')
while True:
    workers = {i['pid']: i for i in uwsgi.workers()}
    now = monotonic()
    if VERBOSE:
        for i in workers.values():
            log(f'[DEBUG]         pid:{i["pid"]} rss:{i["rss"]} {i["status"]}')
            # log(f'[DEBUG] {i}')

    if not workers:
        log('[NOTICE] no workers found')

    # remove dead workers
    for pid in set(retirees).difference(workers):
        lag = now - retirees[pid]['first']
        log(f'worker pid:{pid} gone after {lag:.0f}s')
        del retirees[pid]

    for pid, ret in retirees.items():
        w = workers[pid]
        rss = w['rss']
        status = w['status'].decode()
        attempts = ret['attempts']
        if attempts >= 5:
            os.kill(pid, SIGTERM)
            ret['term'] = True
            log(f'Terminating: {pid} rss:{rss} {status}')
            break

        lag = now - ret['last']
        if lag > WAIT_TIME:
            ret['last'] = now
            ret['attempts'] += 1
            os.kill(pid, SIGHUP)
            log(f'Reminder #{attempts} sent:{pid} rss:{rss} {status}')
            break

    for pid, w in workers.items():
        if pid in retirees:
            continue

        rss = w['rss']
        status = w['status'].decode()

        if rss > MAX_MEMORY and status == 'idle':
            retirees[pid] = {
                'first': now,
                'last': now,
                'attempts': 1,
                'term': False,
            }
            os.kill(pid, SIGHUP)
            log(f'Retiring pid:{pid} rss:{rss}')
            break
    sleep(5)
