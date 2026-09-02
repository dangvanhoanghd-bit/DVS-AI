from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

def diagnose(path: str | Path) -> dict:
    df = pd.read_csv(path)
    result = {
        "rows": len(df),
        "status": df.get(
            "entry_status",
            pd.Series(dtype=str),
        ).value_counts(dropna=False).to_dict(),
    }
    if "opportunity_score" in df:
        result["opportunity_ge_28"] = int(
            (df["opportunity_score"] >= 28.0).sum()
        )
        result["opportunity_ge_52"] = int(
            (df["opportunity_score"] >= 52.0).sum()
        )
    if {
        "opportunity_score",
        "opportunity_rank",
        "direction_confirmation_gate",
    }.issubset(df.columns):
        result["shadow_discovery_candidates"] = int(
            (
                (df["opportunity_score"] >= 28.0)
                & (df["opportunity_rank"] <= 12)
                & df["direction_confirmation_gate"].isin(
                    ["WATCH", "CONFIRMED"]
                )
            ).sum()
        )
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    args = parser.parse_args()
    for key, value in diagnose(args.csv).items():
        print(f"{key}: {value}")

if __name__ == "__main__":
    main()
