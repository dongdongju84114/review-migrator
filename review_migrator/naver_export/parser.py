from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_naver_export(path: str | Path) -> pd.DataFrame:
    input_path = Path(path)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    suffix = input_path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        dataframe = pd.read_excel(input_path, dtype=object)
    elif suffix in {".csv", ".tsv"}:
        sep = "\t" if suffix == ".tsv" else ","
        dataframe = pd.read_csv(input_path, dtype=object, sep=sep)
    else:
        raise ValueError(f"unsupported export format: {suffix}")

    dataframe = dataframe.dropna(how="all")
    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    return dataframe

