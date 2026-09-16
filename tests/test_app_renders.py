import json
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from transform import build_farmer_master, clean_crop_health, clean_distribution

DISTRIBUTION_SHEET_COLUMNS = [
    "unique_farmer_id", "country", "region", "submission_date", "seed_variety", "variety_other",
    "is_delivered", "quantity_kg", "distribution_challenges", "channel_ngo", "channel_direct",
    "channel_govt", "channel_coop", "channel_agrovet",
]
CROP_HEALTH_SHEET_COLUMNS = [
    "unique_farmer_id", "country", "region", "submission_date", "growth_stage", "plant_height_cm",
    "height_z_within_stage", "has_pest_disease", "additional_observations", "symptom_yellow",
    "symptom_stunted", "symptom_wilting", "symptom_none", "symptom_discoloration", "symptom_spots",
]
META_ROWS = [
    ("last_refreshed_eat", "2026-09-16 11:00:21"),
    ("distribution_last_refreshed_eat", "2026-09-16 10:53:25"),
    ("distribution_rows", "48"),
    ("distribution_duplicates_dropped", "1"),
    ("farmer_master_rows", "50"),
    ("crop_health_last_refreshed_eat", "2026-09-16 11:00:21"),
    ("crop_health_rows", "99"),
    ("crop_health_duplicates_dropped", "2"),
]


def as_sheet_csv(df: pd.DataFrame, columns: list[str]) -> str:
    out = df.reindex(columns=columns).copy()
    for column in out.columns:
        if pd.api.types.is_bool_dtype(out[column]) or out[column].dtype == "boolean":
            out[column] = out[column].map({True: "TRUE", False: "FALSE"})
        elif pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out.to_csv(index=False)


@pytest.fixture(scope="module")
def sheet_payloads() -> dict:
    distribution = clean_distribution(pd.DataFrame(json.loads((ROOT / "data/distribution.json").read_text())))
    crop_health = clean_crop_health(pd.DataFrame(json.loads((ROOT / "data/crop_health.json").read_text())))
    farmer_master = build_farmer_master(distribution, crop_health)
    return {
        "distribution": as_sheet_csv(distribution, DISTRIBUTION_SHEET_COLUMNS),
        "crop_health": as_sheet_csv(crop_health, CROP_HEALTH_SHEET_COLUMNS),
        "farmer_master": as_sheet_csv(farmer_master, list(farmer_master.columns)),
        "meta": "\n".join(f"{key},{value}" for key, value in META_ROWS) + "\n",
    }


def fake_get(payloads: dict):
    def _get(url, timeout=None):
        tab = url.split("sheet=")[-1]

        class Response:
            status_code = 200
            text = payloads[tab]

        return Response()

    return _get


@pytest.fixture(autouse=True)
def clear_streamlit_cache():
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.fixture
def app(sheet_payloads, monkeypatch) -> AppTest:
    monkeypatch.setenv("SHEET_ID", "test-sheet")
    with patch("requests.get", fake_get(sheet_payloads)):
        harness = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        harness.run()
        yield harness


def test_app_runs_without_exception(app):
    assert not app.exception, [str(error) for error in app.exception]


def test_every_page_renders(app):
    assert len(app.tabs) >= 5
    headings = " ".join(block.value for block in app.subheader)
    for expected in ("Programme overview", "Seed distribution", "Crop health", "Integrated view", "Data quality"):
        assert expected in headings


def test_overview_reports_linkage_with_its_n(app):
    prose = " ".join(block.value for block in app.markdown)
    assert "linkage rate of 96%" in prose
    assert "n=50 farmers" in prose


def test_sidebar_exposes_every_report_level_filter(app):
    labels = [widget.label for widget in app.sidebar.multiselect] + [
        widget.label for widget in app.sidebar.selectbox
    ]
    for expected in ("Country", "Region", "Seed variety", "Link status", "Growth stage",
                     "Delivery status", "Distribution channel"):
        assert expected in labels


def test_date_range_is_the_first_sidebar_control(app):
    assert app.sidebar.selectbox[0].label == "Submission date range"
    assert "All time" in app.sidebar.selectbox[0].options


def test_section_measure_selectors_exist(app):
    keys = [widget.key for widget in app.sidebar.selectbox]
    for expected in ("dist_metric", "dist_dim", "crop_metric", "crop_dim", "watch_sort"):
        assert expected in keys


def test_changing_the_measure_rerenders_without_exception(app):
    app.sidebar.selectbox(key="crop_metric").select("Mean plant height (cm)").run()
    assert not app.exception, [str(error) for error in app.exception]
    headings = " ".join(block.value for block in app.markdown)
    assert "Mean plant height (cm) by" in headings


def test_changing_the_breakdown_rerenders_without_exception(app):
    app.sidebar.selectbox(key="dist_dim").select("Seed variety").run()
    assert not app.exception, [str(error) for error in app.exception]
    headings = " ".join(block.value for block in app.markdown)
    assert "by seed variety" in headings


def test_missing_sheet_id_fails_explicitly(sheet_payloads, monkeypatch):
    monkeypatch.delenv("SHEET_ID", raising=False)
    with patch("requests.get", fake_get(sheet_payloads)):
        harness = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        harness.run()
    assert harness.error, "app should surface an explicit error when SHEET_ID is unset"
