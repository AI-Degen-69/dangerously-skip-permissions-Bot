"""Shared replay constants (run ids, windows, log path)."""

from . import constants as C
from .runs import LOG_PATH as LOOP_LOG
from .runs import RUNS_DIR as _DEFAULT_RUNS_DIR

__all__ = [
    "BASELINE_RUN",
    "FOUR_RUNS",
    "LOOP_LOG",
    "STRATEGY_HYDROGEN",
    "STRATEGY_V26",
    "STRATEGY_V27",
    "WINDOW_S",
    "_DEFAULT_RUNS_DIR",
]


WINDOW_S = int(C.WINDOW_S)
STRATEGY_V26 = "dangerously-skip-permissions-v2.6"
STRATEGY_V27 = "dangerously-skip-permissions-v2.7"
STRATEGY_HYDROGEN = "hydrogen-v1.9"
BASELINE_RUN = "run_20261113_080232_paper_dsp_v2_6"

FOUR_RUNS = [
    "run_20261110_183056_paper_dsp_v2_5",
    "run_20261113_080232_paper_dsp_v2_6",
    "run_20261113_061914_paper_dsp_v2_6",
    "run_20261113_073610_paper_dsp_v2_6",
]
