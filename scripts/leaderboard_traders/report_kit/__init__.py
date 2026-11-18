"""Shared paths + report helpers for the leaderboard-trader research tools.

Raw ledgers live under data/leaderboard/<account>/raw/ (gitignored machine
output); finished markdown lives under docs/leaderboard-traders/ledgers/.
"""
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RAW_ROOT = REPO_ROOT / "data" / "leaderboard"
DOCS_ROOT = REPO_ROOT / "docs" / "leaderboard-traders" / "ledgers"


def analysis_target(csv_path: str, suffix: str) -> pathlib.Path:
    """Where the <csv-stem><suffix> report goes for a ledger CSV.

    data/leaderboard/<account>/raw/ ledgers report into
    docs/leaderboard-traders/ledgers/<account>/analysis/; a legacy
    docs ledgers/<account>/raw/ ledger reports into its sibling analysis/
    folder; anything else stays next to the CSV.
    """
    src = pathlib.Path(csv_path).resolve()
    try:
        rel = src.relative_to(RAW_ROOT.resolve())
    except ValueError:
        rel = None
    if rel is not None and len(rel.parts) >= 3 and rel.parts[1] == "raw":
        out_dir = DOCS_ROOT / rel.parts[0] / "analysis"
    elif src.parent.name == "raw" and src.parent.parent.parent.name == "ledgers":
        out_dir = src.parent.parent / "analysis"
    else:
        out_dir = src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{src.stem}{suffix}"


class Tee:
    """Duplicates stdout into the analysis file."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


__all__ = [
    "REPO_ROOT",
    "RAW_ROOT",
    "DOCS_ROOT",
    "analysis_target",
    "Tee",
]
