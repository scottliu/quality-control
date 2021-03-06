"""Run Quality Checks against human generated datasets"""

import sys
from loguru import logger
import pandas as pd
import numpy as np
from datetime import datetime
from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter
from datetime import timedelta

import app.checks as checks
from .qc_config import QCConfig
from .data.data_source import DataSource
from .log.result_log import ResultLog
from .modeling.forecast_io import load_forecast_hd5
from .modeling.forecast_plot import plot_to_file
from .util import udatetime
#import .util import 

def check_working(ds: DataSource, config: QCConfig) -> ResultLog:
    """
    Check unpublished results in the working google sheet
    (sheet URL defined in app/data/worksheet_wrapper.py)
    """

    log = ResultLog()

    # targetDate is the date that the dev sheet is currently working on.
    # phase is what part of their process they are in.
    # targetDateEt is the time that should be used on any 'staleness' checks

    d, phase = checks.current_time_and_phase()

    if d.hour < 8:
        logger.error("[adjusting target date to previous day because hour < 8]")
        d = d - timedelta(days=1)
    d = udatetime.naivedatetime_as_eastern(datetime(d.year, d.month, d.day))

    ds._target_date = d

    df = ds.working
    if df is None: return None

    df["targetDate"] = d.year * 10000 + d.month * 100 + d.day
    df["targetDateEt"] = d
    df["phase"] = phase

    logger.info(f"Running with target date = {d.date()} and phase = {phase}")

    # *** WHEN YOU CHANGE A CHECK THAT IMPACTS WORKING, MAKE SURE TO UPDATE THE EXCEL TRACKING DOCUMENT ***

    cnt = 0
    for row in df.itertuples():
        try:

            checks.total(row, log)
            #checks.total_tests(row, log)
            checks.last_update(row, log)
            checks.last_checked(row, log)
            checks.checkers_initials(row, log)
            checks.positives_rate(row, log)
            checks.death_rate(row, log)
            checks.less_recovered_than_positive(row, log)
            checks.pendings_rate(row, log)

            df_history = ds.history[ds.history.state == row.state]
            has_changed = checks.increasing_values(row, df_history, log, config)
            if has_changed:
                checks.expected_positive_increase(row, df_history, log, "working", config)

            #checks.delta_vs_cumulative(row, df_history, log, config)


            if not ds.county_rollup is None:
                df_county_rollup = ds.county_rollup[ds.county_rollup.state == row.state]
                if  not df_county_rollup.empty:
                    checks.counties_rollup_to_state(row, df_county_rollup, log)

        except Exception as ex:
            logger.exception(ex)
            log.internal(row.state, f"{ex}")

        if cnt != 0 and cnt % 10 == 0:
            logger.info(f"  processed {cnt} states")
        cnt += 1

    logger.info(f"  processed {cnt} states")

    checks.missing_tests(log)


    # run loop at end, insted of during run
    if config.plot_models and config.save_results:
        cnt = 0
        for row in df.itertuples():
            try:
                forecast = load_forecast_hd5(config.results_dir, row.state, row.targetDate)
                if forecast is None:
                    logger.warning(f"Could not load forecast for {row.state}/{row.targetDate}")
                else:
                    plot_to_file(forecast, f"{config.images_dir}/working", checks.FIT_THRESHOLDS)
            except Exception as ex:
                logger.exception(ex)
                log.internal(row.state, f"{ex}")
        if cnt != 0 and cnt % 10 == 0:
            logger.info(f"  plotted {cnt} states")
        cnt += 1
        logger.info(f"  plotted {cnt} states")

    log.consolidate()
    return log


def check_current(ds: DataSource, config: QCConfig) -> ResultLog:
    """
    Check the current published results
    """

    log = ResultLog()

    df = ds.current
    if df is None: return None

    publish_date = 20200403
    logger.warning(f" ** current-date is hard-coded to {publish_date}")
    logger.warning(f" ** because the API does not tell us the date the results were published")

    # setup run settings equivalent to publish date at 5PM
    s = str(publish_date)
    y,m,d = int(s[0:4]), int(s[4:6]), int(s[6:8])
    publish_timestamp = udatetime.naivedatetime_as_eastern(datetime(y, m, d, 12+5))

    ds._target_date = publish_timestamp

    df["targetDate"] = publish_date
    df["targetDateEt"] = publish_timestamp
    df["lastCheckEt"] = df["targetDateEt"]
    df["phase"] = "publish"

    for row in df.itertuples():
        checks.total(row, log)
        checks.last_update(row, log)
        checks.positives_rate(row, log)
        checks.death_rate(row, log)
        checks.pendings_rate(row, log)

        df_history = ds.history[ds.history.state == row.state]
        has_changed = checks.increasing_values(row, df_history, log, config)
        if has_changed:
            checks.expected_positive_increase(row, df_history, log, "current", config)

        if not ds.county_rollup is None:
            df_county_rollup = ds.county_rollup[ds.county_rollup.state == row.state]
            if not df_county_rollup.empty:
                checks.counties_rollup_to_state(row, df_county_rollup, log)

    log.consolidate()
    return log


def check_history(ds: DataSource) -> ResultLog:
    """
    Check the history
    """

    log = ResultLog()

    df = ds.history
    if df is None: return None

    for state in df["state"].drop_duplicates().values:
        state_df = df.loc[df["state"] == state]
        checks.monotonically_increasing(state_df, log)

    log.consolidate()
    return log

