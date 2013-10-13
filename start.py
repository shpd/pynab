import multiprocessing
import time
import logging
import signal

from pynab import log
from pynab.db import db

import pynab.groups
import pynab.binaries
import pynab.releases
import pynab.tvrage
import pynab.rars
import config


def init_update():
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def update(group_name):
    return pynab.groups.update(group_name)


def process_tvrage(limit):
    pynab.tvrage.process(limit)


def process_rars(limit):
    pynab.rars.process(limit)


if __name__ == '__main__':
    log.info('Starting update...')

    # print MP log as well
    multiprocessing.log_to_stderr().setLevel(logging.DEBUG)

    while True:
        active_groups = [group['name'] for group in db.groups.find({'active': 1})]

        # if maxtasksperchild is more than 1, everything breaks
        # they're long processes usually, so no problem having one task per child
        with multiprocessing.Pool(processes=config.site['update_threads'], initializer=init_update,
                                  maxtasksperchild=1) as pool:
            try:
                result = pool.map(update, active_groups)
                pool.terminate()
                pool.join()
            except KeyboardInterrupt:
                log.info('Caught ctrl-c, terminating workers.')
                pool.terminate()
                pool.join()

        # process binaries
        # TODO: benchmark threading for this - i suspect it won't do much (mongo table lock)
        pynab.binaries.process()

        # process releases
        # TODO: likewise
        pynab.releases.process()

        # post-processing

        # grab and append tvrage data to tv releases
        # only do 50 at a time though, so we don't smash the tvrage api
        # when your tvrage table has built up you'll rely on the api less
        tvrage_p = multiprocessing.Process(target=process_tvrage, args=(50,))
        tvrage_p.start()

        if config.site['check_passwords']:
            rar_p = multiprocessing.Process(target=process_rars, args=(5,))
            rar_p.start()
            rar_p.join()

        tvrage_p.join()

        # wait for the configured amount of time between cycles
        log.info('Sleeping for {:d} seconds...'.format(config.site['update_wait']))
        time.sleep(config.site['update_wait'])