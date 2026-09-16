# GAIN PMI dashboard

One live dashboard over two SurveyCTO forms, fortified rice seed distribution and rice crop health monitoring, joined per farmer.

## Data flow

```
SurveyCTO REST API
  -> Google Apps Script, time driven trigger every 15 minutes, one form per run
    -> Google Sheet, four tabs: distribution, crop_health, farmer_master, meta
      -> Streamlit app, reads the sheet, public URL, no account needed to view
```

New submissions reach the dashboard without any manual upload. The overview page shows when each form was last pulled.

Why the sheet sits in the middle: SurveyCTO rate limits a full pull to one request per server per 300 seconds, and the limit spans forms rather than applying to each one. An app that fetched both forms on a cache miss would always fail on the second. Apps Script absorbs that limit upstream by refreshing one form per run and alternating, so the app itself is never rate limited.

## The join

The two forms are joined on `unique_farmer_id`, trimmed and upper cased. One identifier in the sample data only matched after that cleaning.

`country` and `region` validate the join rather than drive it. Where the two forms disagree about a farmer's location, or where a farmer's own repeat visits disagree with each other, the farmer is flagged rather than silently corrected. Three farmers are flagged in the sample data.

`farmer_master` is a full outer join, so farmers present in only one form survive into the dashboard as `distribution_only` or `crop_health_only` rather than disappearing.

## Decisions worth knowing

- Crop health carries more than one row per farmer by design, one per growth stage visit. Only a repeated growth stage for the same farmer is treated as an accidental resubmission.
- Where a farmer submitted the same form twice, the most recent submission wins. One distribution pair in the sample disagreed on `quantity_kg`, so this rule changes a reported number and is not cosmetic.
- Plant height is only ever compared within a growth stage, because stage drives height.
- Channel and symptom fields are multi-select, so their totals exceed the farmer and visit counts. The pages that show them say so.
- There is no baseline and no control group here. Nothing in the dashboard is a treatment effect.

The full list is in [docs/assumptions.md](docs/assumptions.md), and the profiling that produced these decisions is in [docs/data-profile.md](docs/data-profile.md).

## Repo layout

```
app.py                     Streamlit dashboard
src/scto_client.py         SurveyCTO REST client
src/profile_data.py        Phase one profiling, writes docs/data-profile.md
src/transform.py           Cleaning, dedupe and the farmer_master join
apps_script/Code.gs        The same transform, running on a 15 minute trigger
tests/                     Transform and dashboard tests
docs/                      Data profile and assumptions
```

`src/transform.py` and `apps_script/Code.gs` implement the same rules in two languages. The Python version is the tested reference and was checked field by field against the Apps Script output on the real data before the pipeline went live.

## Running locally

```
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
SHEET_ID=<google sheet id> .venv/bin/streamlit run app.py
```

Profiling the forms directly from the API needs `SCTO_USER` and `SCTO_PASS` in the environment:

```
PYTHONPATH=src .venv/bin/python src/profile_data.py
```

## Tests

```
.venv/bin/python -m pytest tests/
```

The tests assert the things that would actually break: that the join does not multiply rows when a farmer has several crop health visits, that duplicate submissions resolve to the intended row, that link status covers orphans on both sides, that dirty numeric values fail loudly rather than becoming silent nulls, and that every dashboard page renders.
