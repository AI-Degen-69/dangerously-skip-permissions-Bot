import csv
import os
import pathlib
import sys
import numpy as np
import pandas as pd
SECTION_WIDTH = 74
def md(frame, floatfmt=".4f"):
    """Markdown table without the tabulate dependency."""
    frame = frame.copy()
    for c in frame.columns:
        if pd.api.types.is_float_dtype(frame[c]):
            frame[c] = frame[c].map(lambda v: f"{v:{floatfmt}}")
    head = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    sep = "|" + "|".join("---" for _ in frame.columns) + "|"
    rows = ["| " + " | ".join(str(v) for v in r) + " |" for r in frame.itertuples(index=False)]
    return "\n".join([head, sep] + rows)
def _section(title):
    """Draw a banner above a Markdown section heading.

    The report is both streamed to the terminal and saved as Markdown, so a
    plain `=` rule gives the terminal the same break as the puller while the
    `##` heading stays intact in the saved file.
    """
    print()
    print("=" * SECTION_WIDTH)
    print(f"\n## {title}\n")
def _kv(label, value):
    """A padded `label   value` line, matching the puller's status blocks."""
    print(f"  {label:<17}{value}")
