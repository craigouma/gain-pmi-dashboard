import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transform import (
    build_farmer_master,
    clean_crop_health,
    clean_distribution,
    coerce_binary,
    coerce_numeric,
)

DISTRIBUTION_CHANNEL_RAW_COLS = [
    "distribution_channel_ngo", "distribution_channel_direct",
    "distribution_channel_govt", "distribution_channel_coop", "distribution_channel_agrovet",
]
SYMPTOM_RAW_COLS = [
    "symptoms_observed_yellow", "symptoms_observed_stunted", "symptoms_observed_wilting",
    "symptoms_observed_none", "symptoms_observed_discoloration", "symptoms_observed_spots",
]


def distribution_row(**overrides) -> dict:
    row = {
        "unique_farmer_id": "FRM-001",
        "country": "ken",
        "region": "Kisumu",
        "SubmissionDate": "Sep 13, 2026 1:00:00 PM",
        "seed_variety": "a",
        "variety_other": None,
        "seed_delivered": "1",
        "quantity_kg": "100",
        "distribution_challenges": "",
        **{col: None for col in DISTRIBUTION_CHANNEL_RAW_COLS},
    }
    row.update(overrides)
    return row


def crop_health_row(**overrides) -> dict:
    row = {
        "unique_farmer_id": "FRM-001",
        "country": "ken",
        "region": "Kisumu",
        "SubmissionDate": "Sep 13, 2026 3:00:00 PM",
        "growth_stage": "vegetative",
        "plant_height_cm": "50",
        "pest_disease_present": "0",
        "additional_observations": "",
        **{col: None for col in SYMPTOM_RAW_COLS},
    }
    row.update(overrides)
    return row


def test_clean_distribution_dedupes_keeping_latest_submission():
    raw = pd.DataFrame([
        distribution_row(SubmissionDate="Sep 13, 2026 2:22:07 PM", quantity_kg="325"),
        distribution_row(SubmissionDate="Sep 13, 2026 2:22:57 PM", quantity_kg="233"),
    ])
    clean = clean_distribution(raw)
    assert len(clean) == 1
    assert clean.loc[0, "quantity_kg"] == 233


def test_clean_crop_health_keeps_distinct_growth_stage_visits():
    raw = pd.DataFrame([
        crop_health_row(growth_stage="vegetative", plant_height_cm="40"),
        crop_health_row(growth_stage="flowering", plant_height_cm="70"),
    ])
    clean = clean_crop_health(raw)
    assert len(clean) == 2
    assert clean["unique_farmer_id"].nunique() == 1


def test_clean_crop_health_dedupes_same_stage_resubmission():
    raw = pd.DataFrame([
        crop_health_row(SubmissionDate="Sep 13, 2026 4:02:58 PM", growth_stage="vegetative", plant_height_cm="39.6"),
        crop_health_row(SubmissionDate="Sep 13, 2026 4:04:37 PM", growth_stage="vegetative", plant_height_cm="39.6"),
        crop_health_row(SubmissionDate="Sep 13, 2026 4:05:08 PM", growth_stage="grainfill", plant_height_cm="104"),
    ])
    clean = clean_crop_health(raw)
    assert len(clean) == 2
    assert set(clean["growth_stage"]) == {"vegetative", "grainfill"}


def test_build_farmer_master_does_not_multiply_rows_on_repeat_visits():
    dist_raw = pd.DataFrame([distribution_row(unique_farmer_id=f"FRM-{i:03d}") for i in range(3)])
    crop_raw = pd.DataFrame([
        crop_health_row(unique_farmer_id="FRM-000", growth_stage="vegetative"),
        crop_health_row(unique_farmer_id="FRM-000", growth_stage="flowering"),
        crop_health_row(unique_farmer_id="FRM-000", growth_stage="grainfill"),
        crop_health_row(unique_farmer_id="FRM-001", growth_stage="vegetative"),
    ])
    dist = clean_distribution(dist_raw)
    crop = clean_crop_health(crop_raw)
    master = build_farmer_master(dist, crop)

    assert len(master) == 3
    assert master["unique_farmer_id"].is_unique


def test_build_farmer_master_link_status_covers_both_orphan_sides():
    dist_raw = pd.DataFrame([
        distribution_row(unique_farmer_id="FRM-LINKED"),
        distribution_row(unique_farmer_id="FRM-DIST-ONLY"),
    ])
    crop_raw = pd.DataFrame([
        crop_health_row(unique_farmer_id="FRM-LINKED"),
        crop_health_row(unique_farmer_id="FRM-CROP-ONLY"),
    ])
    dist = clean_distribution(dist_raw)
    crop = clean_crop_health(crop_raw)
    master = build_farmer_master(dist, crop).set_index("unique_farmer_id")

    assert master.loc["FRM-LINKED", "link_status"] == "linked"
    assert master.loc["FRM-DIST-ONLY", "link_status"] == "distribution_only"
    assert master.loc["FRM-CROP-ONLY", "link_status"] == "crop_health_only"
    assert len(master) == 3


def test_build_farmer_master_flags_within_form_country_inconsistency():
    dist_raw = pd.DataFrame([distribution_row(unique_farmer_id="FRM-001", country="ken")])
    crop_raw = pd.DataFrame([
        crop_health_row(unique_farmer_id="FRM-001", country="ken", growth_stage="vegetative"),
        crop_health_row(unique_farmer_id="FRM-001", country="nga", growth_stage="flowering"),
    ])
    dist = clean_distribution(dist_raw)
    crop = clean_crop_health(crop_raw)
    master = build_farmer_master(dist, crop).set_index("unique_farmer_id")

    assert bool(master.loc["FRM-001", "country_mismatch"]) is True
    assert bool(master.loc["FRM-001", "geo_mismatch"]) is True


def test_coerce_numeric_raises_on_dirty_value():
    with pytest.raises(ValueError):
        coerce_numeric(pd.Series(["12", "not-a-number"]), "quantity_kg")


def test_coerce_numeric_passes_through_clean_values():
    result = coerce_numeric(pd.Series(["12", "30.5"]), "quantity_kg")
    assert result.tolist() == [12.0, 30.5]


def test_coerce_binary_raises_on_unexpected_value():
    with pytest.raises(ValueError):
        coerce_binary(pd.Series(["1", "maybe"]), "seed_delivered")


def test_height_z_undefined_for_single_observation_stage():
    raw = pd.DataFrame([
        crop_health_row(unique_farmer_id="FRM-001", growth_stage="vegetative", plant_height_cm="40"),
        crop_health_row(unique_farmer_id="FRM-002", growth_stage="flowering", plant_height_cm="70"),
    ])
    clean = clean_crop_health(raw)
    assert clean["height_z_within_stage"].isna().all()
