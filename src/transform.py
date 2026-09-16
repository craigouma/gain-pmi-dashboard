from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

SCTO_DATE_FORMAT = "%b %d, %Y %I:%M:%S %p"
EAT = ZoneInfo("Africa/Nairobi")

CHANNEL_COLS = {
    "distribution_channel_ngo": "channel_ngo",
    "distribution_channel_direct": "channel_direct",
    "distribution_channel_govt": "channel_govt",
    "distribution_channel_coop": "channel_coop",
    "distribution_channel_agrovet": "channel_agrovet",
}
SYMPTOM_COLS = {
    "symptoms_observed_yellow": "symptom_yellow",
    "symptoms_observed_stunted": "symptom_stunted",
    "symptoms_observed_wilting": "symptom_wilting",
    "symptoms_observed_none": "symptom_none",
    "symptoms_observed_discoloration": "symptom_discoloration",
    "symptoms_observed_spots": "symptom_spots",
}


def clean_id(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.upper()


def clean_label(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip()


def parse_submission_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, format=SCTO_DATE_FORMAT).dt.tz_localize(EAT)


def coerce_numeric(series: pd.Series, field: str) -> pd.Series:
    coerced = pd.to_numeric(series, errors="coerce")
    bad = series[coerced.isna() & series.notna()]
    if len(bad):
        raise ValueError(f"{field}: non-numeric values {sorted(bad.unique().tolist())}")
    return coerced


def coerce_binary(series: pd.Series, field: str) -> pd.Series:
    allowed = {"0": False, "1": True}
    bad = set(series.dropna().unique()) - set(allowed)
    if bad:
        raise ValueError(f"{field}: unexpected values {sorted(bad)}")
    return series.map(allowed).astype("boolean")


def coerce_flag(series: pd.Series) -> pd.Series:
    return series.eq("1").astype("boolean")


def dedupe_keep_latest(df: pd.DataFrame, subset: list[str]) -> pd.DataFrame:
    return df.sort_values("submission_date").drop_duplicates(subset=subset, keep="last").reset_index(drop=True)


def add_height_z_within_stage(df: pd.DataFrame) -> pd.DataFrame:
    mean = df.groupby("growth_stage")["plant_height_cm"].transform("mean")
    std = df.groupby("growth_stage")["plant_height_cm"].transform("std")
    z = (df["plant_height_cm"] - mean) / std
    return df.assign(height_z_within_stage=z.where(std > 0))


def clean_distribution(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({
        "unique_farmer_id": clean_id(raw["unique_farmer_id"]),
        "country": clean_label(raw["country"]).str.lower(),
        "region": clean_label(raw["region"]).str.title(),
        "submission_date": parse_submission_date(raw["SubmissionDate"]),
        "seed_variety": clean_label(raw["seed_variety"]).str.lower(),
        "variety_other": raw["variety_other"].where(raw["variety_other"].notna()),
        "is_delivered": coerce_binary(raw["seed_delivered"], "seed_delivered"),
        "quantity_kg": coerce_numeric(raw["quantity_kg"], "quantity_kg"),
        "distribution_challenges": raw["distribution_challenges"].mask(raw["distribution_challenges"] == ""),
    })
    for raw_col, clean_col in CHANNEL_COLS.items():
        df[clean_col] = coerce_flag(raw[raw_col])
    return dedupe_keep_latest(df, subset=["unique_farmer_id"])


def clean_crop_health(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({
        "unique_farmer_id": clean_id(raw["unique_farmer_id"]),
        "country": clean_label(raw["country"]).str.lower(),
        "region": clean_label(raw["region"]).str.title(),
        "submission_date": parse_submission_date(raw["SubmissionDate"]),
        "growth_stage": clean_label(raw["growth_stage"]).str.lower(),
        "plant_height_cm": coerce_numeric(raw["plant_height_cm"], "plant_height_cm"),
        "has_pest_disease": coerce_binary(raw["pest_disease_present"], "pest_disease_present"),
        "additional_observations": raw["additional_observations"].mask(raw["additional_observations"] == ""),
    })
    for raw_col, clean_col in SYMPTOM_COLS.items():
        df[clean_col] = coerce_flag(raw[raw_col])
    df = dedupe_keep_latest(df, subset=["unique_farmer_id", "growth_stage"])
    return add_height_z_within_stage(df)


def _crop_health_summary(crop_health: pd.DataFrame) -> pd.DataFrame:
    ordered = crop_health.sort_values("submission_date")
    return ordered.groupby("unique_farmer_id").agg(
        n_crop_health_visits=("submission_date", "count"),
        first_crop_health_date=("submission_date", "first"),
        last_crop_health_date=("submission_date", "last"),
        latest_growth_stage=("growth_stage", "last"),
        latest_plant_height_cm=("plant_height_cm", "last"),
        latest_height_z_within_stage=("height_z_within_stage", "last"),
        has_pest_disease=("has_pest_disease", "any"),
        crop_country=("country", "first"),
        crop_country_consistent=("country", lambda s: s.nunique() == 1),
        crop_region=("region", "first"),
        crop_region_consistent=("region", lambda s: s.nunique() == 1),
    ).reset_index().astype({
        "has_pest_disease": "boolean",
        "crop_country_consistent": "boolean",
        "crop_region_consistent": "boolean",
    })


def build_farmer_master(distribution: pd.DataFrame, crop_health: pd.DataFrame) -> pd.DataFrame:
    dist_ids = set(distribution["unique_farmer_id"])
    crop_ids = set(crop_health["unique_farmer_id"])

    master = pd.DataFrame({"unique_farmer_id": sorted(dist_ids | crop_ids)})
    master["link_status"] = np.select(
        [master["unique_farmer_id"].isin(dist_ids) & master["unique_farmer_id"].isin(crop_ids),
         master["unique_farmer_id"].isin(dist_ids)],
        ["linked", "distribution_only"],
        default="crop_health_only",
    )

    dist_cols = [
        "unique_farmer_id", "country", "region", "submission_date", "seed_variety",
        "is_delivered", "quantity_kg", *CHANNEL_COLS.values(),
    ]
    master = master.merge(distribution[dist_cols], on="unique_farmer_id", how="left")
    master = master.rename(columns={"submission_date": "distribution_submission_date"})
    master = master.merge(_crop_health_summary(crop_health), on="unique_farmer_id", how="left")

    linked = master["link_status"] == "linked"
    master["country"] = master["country"].fillna(master["crop_country"])
    master["region"] = master["region"].fillna(master["crop_region"])
    master["country_mismatch"] = (
        ~master["crop_country_consistent"].fillna(True)
        | (linked & (master["country"] != master["crop_country"]))
    )
    master["region_mismatch"] = (
        ~master["crop_region_consistent"].fillna(True)
        | (linked & (master["region"] != master["crop_region"]))
    )
    master["geo_mismatch"] = master["country_mismatch"] | master["region_mismatch"]
    master["days_between_submissions"] = (
        master["first_crop_health_date"] - master["distribution_submission_date"]
    ).dt.days
    master["n_crop_health_visits"] = master["n_crop_health_visits"].fillna(0).astype(int)

    return master.drop(columns=["crop_country", "crop_country_consistent", "crop_region", "crop_region_consistent"])
