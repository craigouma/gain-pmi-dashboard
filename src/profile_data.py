import json
from pathlib import Path

import pandas as pd

from scto_client import FORM_IDS, fetch_form

DATA_DIR = Path("data")
DOCS_DIR = Path("docs")
SCTO_DATE_FORMAT = "%b %d, %Y %I:%M:%S %p"
SCTO_METADATA_COLS = {
    "CompletionDate", "SubmissionDate", "instanceID",
    "formdef_version", "review_quality", "review_status", "KEY",
}


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
    parsed = pd.to_datetime(df[col], format=SCTO_DATE_FORMAT)
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


def duplicate_conflicts(df: pd.DataFrame, ids: pd.Series) -> int:
    compare_cols = [c for c in df.columns if c not in SCTO_METADATA_COLS]
    working = df[compare_cols].assign(_id=ids)
    conflicts = 0
    for _, group in working[working["_id"].duplicated(keep=False)].groupby("_id"):
        if group[compare_cols].nunique(dropna=False).gt(1).any():
            conflicts += 1
    return conflicts


def same_stage_repeats(crop: pd.DataFrame, crop_ids: pd.Series) -> int:
    try:
        stage_col = find_column(crop, "growth_stage")
    except ValueError:
        return 0
    counts = pd.DataFrame({"_id": crop_ids, "_stage": crop[stage_col]}).groupby(["_id", "_stage"]).size()
    return int((counts > 1).sum())


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
        "distribution_duplicate_conflicts": duplicate_conflicts(dist, dist_ids),
        "crop_health_rows": len(crop),
        "crop_health_distinct_ids": int(crop_ids.nunique()),
        "crop_health_duplicate_ids": crop_ids[crop_ids.duplicated(keep=False)].value_counts().to_dict(),
        "crop_health_same_stage_duplicate_pairs": same_stage_repeats(crop, crop_ids),
        "linked": len(dist_set & crop_set),
        "distribution_only": len(dist_set - crop_set),
        "crop_health_only": len(crop_set - dist_set),
        "id_whitespace_or_case_variants": int((dist_raw != dist_ids).sum() + (crop_raw != crop_ids).sum()),
        "country_disagreements": geo_disagreement(dist, crop, dist_id_col, crop_id_col, "country"),
        "region_disagreements": geo_disagreement(dist, crop, dist_id_col, crop_id_col, "region"),
    }


def render_findings(diagnostics: dict) -> list[str]:
    findings = [
        f"{diagnostics['linked']} farmer IDs are linked across both forms. "
        f"{diagnostics['distribution_only']} appear in distribution only and "
        f"{diagnostics['crop_health_only']} appear in crop health only.",
        f"Crop health carries {diagnostics['crop_health_rows']} rows for "
        f"{diagnostics['crop_health_distinct_ids']} distinct farmers, one row per growth stage visit by design. "
        f"{diagnostics['crop_health_same_stage_duplicate_pairs']} farmer and growth stage pairs are repeated, "
        "which looks like accidental resubmission rather than a second visit and needs a dedupe rule in phase 2.",
        f"Distribution has {len(diagnostics['distribution_duplicate_ids'])} duplicated farmer ID(s), of which "
        f"{diagnostics['distribution_duplicate_conflicts']} carry conflicting values across the duplicate rows, "
        "for example a different quantity_kg on each submission. This must be resolved before the join, not silently summed.",
        f"{diagnostics['country_disagreements']} linked farmers have a country value that disagrees between forms, "
        f"and {diagnostics['region_disagreements']} disagree on region. Country and region validate the join, they do not drive it.",
        f"{diagnostics['id_whitespace_or_case_variants']} raw farmer ID value(s) needed strip and uppercase to match, "
        "confirming the cleaning rule is load bearing, not optional.",
    ]
    return findings


def render_report(dist: pd.DataFrame, crop: pd.DataFrame, diagnostics: dict) -> str:
    dist_start, dist_end = submission_range(dist)
    crop_start, crop_end = submission_range(crop)

    lines = ["# Data profile", ""]

    lines.append("## Findings")
    for finding in render_findings(diagnostics):
        lines.append(f"- {finding}")
    lines.append("")

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

    lines.append("## Join diagnostics, raw")
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
