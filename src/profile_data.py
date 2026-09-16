import json
from pathlib import Path

import pandas as pd

from scto_client import FORM_IDS, fetch_form

DATA_DIR = Path("data")
DOCS_DIR = Path("docs")


def load_form(form_key: str, use_cache: bool = True) -> pd.DataFrame:
    cache_path = DATA_DIR / f"{form_key}.json"
    if use_cache and cache_path.exists():
        records = json.loads(cache_path.read_text())
    else:
        records = fetch_form(FORM_IDS[form_key])
        DATA_DIR.mkdir(exist_ok=True)
        cache_path.write_text(json.dumps(records))
    return pd.DataFrame(records)


def find_column(df: pd.DataFrame, field: str) -> str:
    matches = [c for c in df.columns if c.split(".")[-1].lower() == field.lower()]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one column matching {field!r}, found {matches}")
    return matches[0]


def clean_id(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.upper()


def column_profile(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "dtype": df.dtypes.astype(str),
        "null_rate": df.isna().mean().round(4),
        "n_unique": df.nunique(dropna=True),
    })


def submission_range(df: pd.DataFrame) -> tuple[str, str]:
    col = find_column(df, "SubmissionDate")
    parsed = pd.to_datetime(df[col], errors="coerce")
    return str(parsed.min()), str(parsed.max())


def geo_disagreement(dist: pd.DataFrame, crop: pd.DataFrame, dist_id_col: str, crop_id_col: str, field: str) -> int:
    try:
        d_col = find_column(dist, field)
        c_col = find_column(crop, field)
    except ValueError:
        return 0
    left = pd.DataFrame({
        "unique_farmer_id": clean_id(dist[dist_id_col]),
        f"dist_{field}": dist[d_col].astype(str).str.strip().str.upper(),
    })
    right = pd.DataFrame({
        "unique_farmer_id": clean_id(crop[crop_id_col]),
        f"crop_{field}": crop[c_col].astype(str).str.strip().str.upper(),
    })
    merged = left.merge(right, on="unique_farmer_id")
    return int((merged[f"dist_{field}"] != merged[f"crop_{field}"]).sum())


def join_diagnostics(dist: pd.DataFrame, crop: pd.DataFrame) -> dict:
    dist_id_col = find_column(dist, "unique_farmer_id")
    crop_id_col = find_column(crop, "unique_farmer_id")

    dist_raw = dist[dist_id_col].astype(str)
    crop_raw = crop[crop_id_col].astype(str)
    dist_ids = clean_id(dist[dist_id_col])
    crop_ids = clean_id(crop[crop_id_col])

    dist_set, crop_set = set(dist_ids), set(crop_ids)

    return {
        "distribution_rows": len(dist),
        "distribution_distinct_ids": int(dist_ids.nunique()),
        "distribution_duplicate_ids": dist_ids[dist_ids.duplicated(keep=False)].value_counts().to_dict(),
        "crop_health_rows": len(crop),
        "crop_health_distinct_ids": int(crop_ids.nunique()),
        "crop_health_duplicate_ids": crop_ids[crop_ids.duplicated(keep=False)].value_counts().to_dict(),
        "linked": len(dist_set & crop_set),
        "distribution_only": len(dist_set - crop_set),
        "crop_health_only": len(crop_set - dist_set),
        "id_whitespace_or_case_variants": int((dist_raw != dist_ids).sum() + (crop_raw != crop_ids).sum()),
        "country_disagreements": geo_disagreement(dist, crop, dist_id_col, crop_id_col, "country"),
        "region_disagreements": geo_disagreement(dist, crop, dist_id_col, crop_id_col, "region"),
    }


def render_report(dist: pd.DataFrame, crop: pd.DataFrame, diagnostics: dict) -> str:
    dist_start, dist_end = submission_range(dist)
    crop_start, crop_end = submission_range(crop)

    lines = ["# Data profile", ""]

    for label, df in (("Distribution", dist), ("Crop health", crop)):
        lines.append(f"## {label}")
        lines.append(f"Shape: {df.shape[0]} rows, {df.shape[1]} columns")
        lines.append("")
        lines.append(column_profile(df).to_markdown())
        lines.append("")

    lines.append("## Submission date range")
    lines.append(f"Distribution: {dist_start} to {dist_end}")
    lines.append(f"Crop health: {crop_start} to {crop_end}")
    lines.append("")

    lines.append("## Join diagnostics")
    for key, value in diagnostics.items():
        lines.append(f"{key}: {value}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    dist = load_form("distribution")
    crop = load_form("crop_health")
    diagnostics = join_diagnostics(dist, crop)
    report = render_report(dist, crop, diagnostics)
    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "data-profile.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
