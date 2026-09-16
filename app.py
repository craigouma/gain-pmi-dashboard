import os

import altair as alt
import pandas as pd
import requests
import streamlit as st

PALETTE = {
    "ink": "#14202E",
    "primary": "#1B3A5C",
    "secondary": "#2E5E8C",
    "muted": "#5A6672",
    "border": "#D7DCE1",
    "page": "#F5F6F8",
    "surface": "#FFFFFF",
    "good": "#2E6B4F",
    "watch": "#A8761F",
    "risk": "#9B2C2C",
}

GROWTH_STAGE_ORDER = ["seedling", "vegetative", "flowering", "grainfill", "maturity"]

CHANNEL_LABELS = {
    "channel_ngo": "NGO",
    "channel_direct": "Direct",
    "channel_govt": "Government",
    "channel_coop": "Cooperative",
    "channel_agrovet": "Agrovet",
}

SYMPTOM_LABELS = {
    "symptom_yellow": "Yellowing",
    "symptom_stunted": "Stunted growth",
    "symptom_wilting": "Wilting",
    "symptom_discoloration": "Discoloration",
    "symptom_spots": "Spots",
    "symptom_none": "None observed",
}

BOOLEAN_COLUMNS = {
    "distribution": ["is_delivered", *CHANNEL_LABELS],
    "crop_health": ["has_pest_disease", *SYMPTOM_LABELS],
    "farmer_master": [
        "country_mismatch", "region_mismatch", "geo_mismatch",
        "is_delivered", "has_pest_disease", *CHANNEL_LABELS,
    ],
}

NUMERIC_COLUMNS = {
    "distribution": ["quantity_kg"],
    "crop_health": ["plant_height_cm", "height_z_within_stage"],
    "farmer_master": [
        "quantity_kg", "n_crop_health_visits", "latest_plant_height_cm",
        "latest_height_z_within_stage", "days_between_submissions",
    ],
}

DATE_COLUMNS = {
    "distribution": ["submission_date"],
    "crop_health": ["submission_date"],
    "farmer_master": ["distribution_submission_date", "first_crop_health_date", "last_crop_health_date"],
}


def sheet_id() -> str:
    from_env = os.environ.get("SHEET_ID")
    if from_env:
        return from_env
    try:
        return st.secrets["SHEET_ID"]
    except Exception as exc:
        raise RuntimeError("SHEET_ID must be set as an environment variable or in Streamlit secrets") from exc


@st.cache_data(ttl=60, show_spinner=False)
def fetch_tab(tab: str, has_header: bool) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id()}/gviz/tq?tqx=out:csv&sheet={tab}"
    response = requests.get(url, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(
            f"{tab}: HTTP {response.status_code} reading the sheet. "
            "Check the sheet is shared with anyone who has the link."
        )
    if response.text.lstrip().startswith("<"):
        raise RuntimeError(
            f"{tab}: the sheet returned HTML rather than CSV. "
            "Check the sheet is shared with anyone who has the link."
        )
    from io import StringIO
    if has_header:
        return pd.read_csv(StringIO(response.text))
    return pd.read_csv(StringIO(response.text), header=None, names=["key", "value"])


def to_boolean(series: pd.Series) -> pd.Series:
    normalised = series.astype(str).str.strip().str.lower()
    return normalised.map({"true": True, "false": False}).astype("boolean")


def to_datetime(series: pd.Series, field: str) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    unparsed = series.notna() & parsed.isna()
    if unparsed.any():
        raise RuntimeError(f"{field}: could not parse {series[unparsed].unique()[:3].tolist()}")
    return parsed


def typed_tab(tab: str) -> pd.DataFrame:
    df = fetch_tab(tab, has_header=True).copy()
    for column in BOOLEAN_COLUMNS[tab]:
        df[column] = to_boolean(df[column])
    for column in NUMERIC_COLUMNS[tab]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in DATE_COLUMNS[tab]:
        df[column] = to_datetime(df[column], f"{tab}.{column}")
    return df


def load_meta() -> dict:
    meta = fetch_tab("meta", has_header=False)
    return dict(zip(meta["key"], meta["value"]))


def melt_flags(df: pd.DataFrame, labels: dict, value_name: str) -> pd.DataFrame:
    present = [column for column in labels if column in df.columns]
    long = df.melt(id_vars=["unique_farmer_id"], value_vars=present, var_name="flag", value_name="selected")
    long = long[long["selected"] == True]
    long[value_name] = long["flag"].map(labels)
    return long


def rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else float("nan")


def style(chart: alt.Chart) -> alt.Chart:
    return chart.configure_view(strokeWidth=0).configure_axis(
        labelColor=PALETTE["muted"],
        titleColor=PALETTE["ink"],
        gridColor=PALETTE["border"],
        domainColor=PALETTE["border"],
        tickColor=PALETTE["border"],
        labelFontSize=12,
        titleFontSize=12,
    ).configure_legend(
        labelColor=PALETTE["ink"], titleColor=PALETTE["ink"], labelFontSize=12, titleFontSize=12,
    )


def bar(df: pd.DataFrame, x: str, y: str, x_title: str, y_title: str, sort=None, height: int = 280) -> alt.Chart:
    return alt.Chart(df, height=height).mark_bar(color=PALETTE["primary"], cornerRadiusEnd=4, size=22).encode(
        x=alt.X(x, title=x_title, sort=sort, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(y, title=y_title, scale=alt.Scale(zero=True)),
        tooltip=list(df.columns),
    )


def sidebar_filters(farmer_master: pd.DataFrame, crop_health: pd.DataFrame) -> dict:
    st.sidebar.header("Filters")
    countries = sorted(farmer_master["country"].dropna().unique())
    regions = sorted(farmer_master["region"].dropna().unique())
    varieties = sorted(farmer_master["seed_variety"].dropna().unique())
    statuses = sorted(farmer_master["link_status"].dropna().unique())
    stages = [stage for stage in GROWTH_STAGE_ORDER if stage in set(crop_health["growth_stage"])]

    selected = {
        "country": st.sidebar.multiselect("Country", countries, default=countries),
        "region": st.sidebar.multiselect("Region", regions, default=regions),
        "seed_variety": st.sidebar.multiselect("Seed variety", varieties, default=varieties),
        "link_status": st.sidebar.multiselect("Link status", statuses, default=statuses),
        "growth_stage": st.sidebar.multiselect("Growth stage", stages, default=stages),
        "delivery": st.sidebar.selectbox("Delivery status", ["All", "Delivered", "Not delivered"]),
        "channel": st.sidebar.selectbox("Distribution channel", ["All", *CHANNEL_LABELS.values()]),
    }

    dates = pd.concat([
        farmer_master["distribution_submission_date"], crop_health["submission_date"],
    ]).dropna()
    if not dates.empty:
        first, last = dates.min().date(), dates.max().date()
        selected["date_range"] = st.sidebar.date_input("Submission date range", value=(first, last))
    else:
        selected["date_range"] = ()
    return selected


def apply_filters(frames: dict, filters: dict) -> dict:
    farmer_master = frames["farmer_master"]
    mask = (
        farmer_master["country"].isin(filters["country"])
        & farmer_master["region"].isin(filters["region"])
        & farmer_master["link_status"].isin(filters["link_status"])
    )
    if filters["seed_variety"]:
        mask &= farmer_master["seed_variety"].isin(filters["seed_variety"]) | farmer_master["seed_variety"].isna()
    if filters["delivery"] == "Delivered":
        mask &= farmer_master["is_delivered"] == True
    elif filters["delivery"] == "Not delivered":
        mask &= farmer_master["is_delivered"] == False
    if filters["channel"] != "All":
        column = next(key for key, label in CHANNEL_LABELS.items() if label == filters["channel"])
        mask &= farmer_master[column] == True
    if len(filters["date_range"]) == 2:
        start, end = filters["date_range"]
        day = farmer_master["distribution_submission_date"].dt.date
        mask &= day.isna() | ((day >= start) & (day <= end))

    kept = farmer_master[mask]
    ids = set(kept["unique_farmer_id"])
    crop_health = frames["crop_health"]
    crop_health = crop_health[
        crop_health["unique_farmer_id"].isin(ids) & crop_health["growth_stage"].isin(filters["growth_stage"])
    ]
    distribution = frames["distribution"]
    distribution = distribution[distribution["unique_farmer_id"].isin(ids)]
    return {"farmer_master": kept, "crop_health": crop_health, "distribution": distribution}


def render_overview(frames: dict, meta: dict) -> None:
    farmer_master, crop_health, distribution = frames["farmer_master"], frames["crop_health"], frames["distribution"]
    st.subheader("Programme overview")

    reached = farmer_master[farmer_master["link_status"] != "crop_health_only"]
    linked = farmer_master[farmer_master["link_status"] == "linked"]
    with_visits = farmer_master[farmer_master["n_crop_health_visits"] > 0]
    pest_farmers = with_visits[with_visits["has_pest_disease"] == True]
    delivered = reached[reached["is_delivered"] == True]

    linkage_rate = rate(len(linked), len(farmer_master))
    delivery_rate = rate(len(delivered), len(reached))
    pest_rate = rate(len(pest_farmers), len(with_visits))

    st.markdown(
        f"""
Across all submissions received to date, {len(linked)} of {len(farmer_master)} farmer records are linked
across both forms, a linkage rate of {linkage_rate:.0%} (n={len(farmer_master)} farmers).
Seed reached {len(reached)} farmers carrying {distribution['quantity_kg'].sum():,.0f} kg in total,
and delivery is marked complete for {delivery_rate:.0%} of them (n={len(reached)} farmers).
Crop health monitoring has captured {len(crop_health)} visits across {crop_health['unique_farmer_id'].nunique()}
farmers, and pest or disease is present for {pest_rate:.0%} of the farmers visited (n={len(with_visits)} farmers).
Geographic disagreement between the two forms affects {int(farmer_master['geo_mismatch'].sum())} farmers and is
listed on the data quality page. This is a small sample of dummy data, so differences between groups may be noise.
"""
    )

    left, middle, right = st.columns(3)
    left.metric("Farmers reached", f"{len(reached):,}")
    left.caption(f"Farmers with a distribution record, n={len(farmer_master)} farmer records")
    middle.metric("Quantity distributed", f"{distribution['quantity_kg'].sum():,.0f} kg")
    middle.caption(f"All submissions to date, n={len(distribution)} distribution records")
    right.metric("Crop health visits", f"{len(crop_health):,}")
    right.caption(f"All submissions to date, across {crop_health['unique_farmer_id'].nunique()} farmers")

    left, middle, right = st.columns(3)
    left.metric("Delivery completion rate", f"{delivery_rate:.0%}")
    left.caption(f"n={len(reached)} farmers with a distribution record")
    middle.metric("Linkage rate", f"{linkage_rate:.0%}")
    middle.caption(f"n={len(farmer_master)} farmer records across both forms")
    right.metric("Pest or disease rate", f"{pest_rate:.0%}")
    right.caption(f"n={len(with_visits)} farmers with at least one crop health visit")

    st.markdown("##### Distribution volume by region")
    st.caption("Total kilograms distributed, all submissions to date")
    by_region = distribution.groupby("region", as_index=False)["quantity_kg"].sum()
    if not by_region.empty:
        st.altair_chart(
            style(bar(by_region, "region:N", "quantity_kg:Q", "Region", "Quantity (kg)",
                      sort=alt.EncodingSortField(field="quantity_kg", order="descending"))),
            use_container_width=True,
        )

    st.markdown("##### Delivery status by region")
    st.caption("Farmers with a distribution record, all submissions to date")
    status = reached.assign(
        delivery_status=reached["is_delivered"].map({True: "Delivered", False: "Not delivered"}).astype(str)
    )
    composition = status.groupby(["region", "delivery_status"], as_index=False)["unique_farmer_id"].nunique()
    if not composition.empty:
        st.altair_chart(
            style(alt.Chart(composition, height=280).mark_bar(cornerRadiusEnd=4, size=22).encode(
                x=alt.X("region:N", title="Region", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("unique_farmer_id:Q", title="Farmers", scale=alt.Scale(zero=True)),
                color=alt.Color("delivery_status:N", title="Delivery status", scale=alt.Scale(
                    domain=["Delivered", "Not delivered"], range=[PALETTE["good"], PALETTE["risk"]])),
                tooltip=["region", "delivery_status", "unique_farmer_id"],
            )),
            use_container_width=True,
        )

    st.markdown("##### Submissions over time")
    st.caption("Submissions per day for each form, distinguished by line style as well as shade")
    daily = pd.concat([
        distribution.assign(form="Seed distribution", day=distribution["submission_date"].dt.date),
        crop_health.assign(form="Crop health", day=crop_health["submission_date"].dt.date),
    ])[["form", "day", "unique_farmer_id"]]
    counts = daily.groupby(["form", "day"], as_index=False).size().rename(columns={"size": "submissions"})
    if not counts.empty:
        st.altair_chart(
            style(alt.Chart(counts, height=280).mark_line(point=True, strokeWidth=2).encode(
                x=alt.X("day:T", title="Submission date"),
                y=alt.Y("submissions:Q", title="Submissions", scale=alt.Scale(zero=True)),
                color=alt.Color("form:N", title="Form", scale=alt.Scale(
                    domain=["Seed distribution", "Crop health"], range=[PALETTE["primary"], PALETTE["muted"]])),
                strokeDash=alt.StrokeDash("form:N", title="Form"),
                tooltip=["form", "day", "submissions"],
            )),
            use_container_width=True,
        )

    st.caption(
        f"Data last refreshed {meta.get('last_refreshed_eat', 'unknown')} EAT. "
        f"Seed distribution form {meta.get('distribution_last_refreshed_eat', 'unknown')}, "
        f"crop health form {meta.get('crop_health_last_refreshed_eat', 'unknown')}."
    )


def render_distribution(frames: dict) -> None:
    distribution = frames["distribution"]
    st.subheader("Seed distribution")
    if distribution.empty:
        st.info("No distribution records match the current filters.")
        return

    st.markdown("##### Quantity by seed variety")
    st.caption("Total kilograms distributed, all submissions to date")
    by_variety = distribution.groupby("seed_variety", as_index=False)["quantity_kg"].sum()
    st.altair_chart(
        style(bar(by_variety, "seed_variety:N", "quantity_kg:Q", "Seed variety", "Quantity (kg)")),
        use_container_width=True,
    )

    st.markdown("##### Quantity by distribution channel")
    st.caption(
        "Total kilograms distributed, all submissions to date. Channel is multi-select, so a farmer can appear "
        "under more than one channel and channel totals exceed the farmer count."
    )
    channels = melt_flags(distribution, CHANNEL_LABELS, "channel")
    channel_quantity = channels.merge(
        distribution[["unique_farmer_id", "quantity_kg"]], on="unique_farmer_id"
    ).groupby("channel", as_index=False)["quantity_kg"].sum()
    if not channel_quantity.empty:
        st.altair_chart(
            style(bar(channel_quantity, "channel:N", "quantity_kg:Q", "Channel", "Quantity (kg)",
                      sort=alt.EncodingSortField(field="quantity_kg", order="descending"))),
            use_container_width=True,
        )

    st.markdown("##### Delivery completion by channel")
    st.caption("Share of farmers in each channel marked delivered, with n per channel")
    delivery_by_channel = channels.merge(
        distribution[["unique_farmer_id", "is_delivered"]], on="unique_farmer_id"
    ).groupby("channel").agg(
        farmers=("unique_farmer_id", "nunique"),
        delivered=("is_delivered", lambda values: int((values == True).sum())),
    ).reset_index()
    if not delivery_by_channel.empty:
        delivery_by_channel["completion_rate"] = (
            delivery_by_channel["delivered"] / delivery_by_channel["farmers"]
        )
        st.dataframe(
            delivery_by_channel.rename(columns={
                "channel": "Channel", "farmers": "Farmers (n)", "delivered": "Delivered",
                "completion_rate": "Completion rate",
            }).style.format({"Completion rate": "{:.0%}"}),
            use_container_width=True, hide_index=True,
        )

    st.markdown("##### Reported challenges")
    st.caption("Count of submissions reporting each challenge, all submissions to date")
    challenges = distribution[["region", "distribution_challenges"]].dropna()
    if challenges.empty:
        st.info("No challenges reported in the current selection.")
    else:
        exploded = challenges.assign(
            challenge=challenges["distribution_challenges"].str.split(";")
        ).explode("challenge")
        exploded["challenge"] = exploded["challenge"].str.strip()
        exploded = exploded[exploded["challenge"] != ""]
        counts = exploded.groupby("challenge", as_index=False).size().rename(columns={"size": "submissions"})
        st.altair_chart(
            style(alt.Chart(counts, height=max(240, 26 * len(counts))).mark_bar(
                color=PALETTE["primary"], cornerRadiusEnd=4, size=18
            ).encode(
                x=alt.X("submissions:Q", title="Submissions", scale=alt.Scale(zero=True)),
                y=alt.Y("challenge:N", title="Challenge", sort="-x"),
                tooltip=["challenge", "submissions"],
            )),
            use_container_width=True,
        )
        st.caption("Challenges by region")
        st.dataframe(
            exploded.groupby(["region", "challenge"], as_index=False).size()
            .rename(columns={"region": "Region", "challenge": "Challenge", "size": "Submissions"}),
            use_container_width=True, hide_index=True,
        )

    render_farmer_table(distribution, "distribution")


def render_crop_health(frames: dict) -> None:
    crop_health = frames["crop_health"]
    st.subheader("Crop health")
    if crop_health.empty:
        st.info("No crop health visits match the current filters.")
        return

    st.markdown("##### Pest or disease incidence by region")
    st.caption("Share of crop health visits recording pest or disease, with n visits per region")
    by_region = crop_health.groupby("region").agg(
        visits=("unique_farmer_id", "size"),
        with_pest=("has_pest_disease", lambda values: int((values == True).sum())),
    ).reset_index()
    by_region["incidence"] = by_region["with_pest"] / by_region["visits"]
    st.altair_chart(
        style(alt.Chart(by_region, height=280).mark_bar(color=PALETTE["primary"], cornerRadiusEnd=4, size=22).encode(
            x=alt.X("region:N", title="Region", sort="-y", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("incidence:Q", title="Incidence rate", axis=alt.Axis(format="%"), scale=alt.Scale(zero=True)),
            tooltip=["region", alt.Tooltip("incidence:Q", format=".0%"), "visits", "with_pest"],
        )),
        use_container_width=True,
    )

    st.markdown("##### Pest or disease incidence by growth stage")
    st.caption("Share of crop health visits recording pest or disease, with n visits per stage")
    by_stage = crop_health.groupby("growth_stage").agg(
        visits=("unique_farmer_id", "size"),
        with_pest=("has_pest_disease", lambda values: int((values == True).sum())),
    ).reset_index()
    by_stage["incidence"] = by_stage["with_pest"] / by_stage["visits"]
    st.altair_chart(
        style(alt.Chart(by_stage, height=280).mark_bar(color=PALETTE["primary"], cornerRadiusEnd=4, size=22).encode(
            x=alt.X("growth_stage:N", title="Growth stage", sort=GROWTH_STAGE_ORDER, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("incidence:Q", title="Incidence rate", axis=alt.Axis(format="%"), scale=alt.Scale(zero=True)),
            tooltip=["growth_stage", alt.Tooltip("incidence:Q", format=".0%"), "visits", "with_pest"],
        )),
        use_container_width=True,
    )

    st.markdown("##### Observed symptoms")
    st.caption(
        "Count of visits recording each symptom, all submissions to date. Symptoms are multi-select, so totals "
        "exceed the number of visits."
    )
    symptoms = melt_flags(crop_health, SYMPTOM_LABELS, "symptom")
    symptom_counts = symptoms.groupby("symptom", as_index=False).size().rename(columns={"size": "visits"})
    if not symptom_counts.empty:
        st.altair_chart(
            style(alt.Chart(symptom_counts, height=280).mark_bar(
                color=PALETTE["primary"], cornerRadiusEnd=4, size=18
            ).encode(
                x=alt.X("visits:Q", title="Visits", scale=alt.Scale(zero=True)),
                y=alt.Y("symptom:N", title="Symptom", sort="-x"),
                tooltip=["symptom", "visits"],
            )),
            use_container_width=True,
        )

    st.markdown("##### Plant height by growth stage")
    st.caption(
        "Height is compared only within growth stage, never pooled across stages. The box shows the spread of "
        "observed heights, the table gives the mean with its n."
    )
    st.altair_chart(
        style(alt.Chart(crop_health, height=300).mark_boxplot(color=PALETTE["primary"], size=30).encode(
            x=alt.X("growth_stage:N", title="Growth stage", sort=GROWTH_STAGE_ORDER, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("plant_height_cm:Q", title="Plant height (cm)", scale=alt.Scale(zero=True)),
        )),
        use_container_width=True,
    )
    summary = crop_health.groupby("growth_stage")["plant_height_cm"].agg(["count", "mean", "std"]).reset_index()
    summary["growth_stage"] = pd.Categorical(summary["growth_stage"], GROWTH_STAGE_ORDER, ordered=True)
    st.dataframe(
        summary.sort_values("growth_stage").rename(columns={
            "growth_stage": "Growth stage", "count": "Visits (n)",
            "mean": "Mean height (cm)", "std": "Standard deviation (cm)",
        }).style.format({"Mean height (cm)": "{:.1f}", "Standard deviation (cm)": "{:.1f}"}),
        use_container_width=True, hide_index=True,
    )

    render_farmer_table(crop_health, "crop_health")


def render_integrated(frames: dict) -> None:
    farmer_master, crop_health = frames["farmer_master"], frames["crop_health"]
    st.subheader("Integrated view")
    if crop_health.empty or farmer_master.empty:
        st.info("No linked records match the current filters.")
        return

    joined = crop_health.merge(
        farmer_master[["unique_farmer_id", "seed_variety", "quantity_kg", "is_delivered"]],
        on="unique_farmer_id", how="inner",
    )

    st.markdown("##### Mean plant height by seed variety, within growth stage")
    st.caption(
        "Compared only within growth stage. Bars show the mean, the line through each bar is the 95 percent "
        "confidence interval, and n is the number of visits behind each bar."
    )
    by_variety_stage = joined.dropna(subset=["seed_variety"])
    if by_variety_stage.empty:
        st.info("No visits with a linked seed variety in the current selection.")
    else:
        base = alt.Chart(by_variety_stage)
        bars = base.mark_bar(color=PALETTE["primary"], cornerRadiusEnd=4, size=22).encode(
            x=alt.X("seed_variety:N", title="Seed variety", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("mean(plant_height_cm):Q", title="Mean plant height (cm)", scale=alt.Scale(zero=True)),
        )
        intervals = base.mark_errorbar(extent="ci", color=PALETTE["ink"]).encode(
            x=alt.X("seed_variety:N"), y=alt.Y("plant_height_cm:Q", title="Mean plant height (cm)"),
        )
        labels = base.mark_text(dy=-6, color=PALETTE["muted"], fontSize=11).encode(
            x=alt.X("seed_variety:N"),
            y=alt.Y("mean(plant_height_cm):Q"),
            text=alt.Text("count():Q", format="d"),
        )
        st.altair_chart(
            style((bars + intervals + labels).properties(height=240).facet(
                column=alt.Column("growth_stage:N", title="Growth stage", sort=GROWTH_STAGE_ORDER),
            )),
            use_container_width=False,
        )
        counts = by_variety_stage.groupby(["growth_stage", "seed_variety"])["plant_height_cm"].agg(
            ["count", "mean", "std"]
        ).reset_index()
        counts["growth_stage"] = pd.Categorical(counts["growth_stage"], GROWTH_STAGE_ORDER, ordered=True)
        st.dataframe(
            counts.sort_values(["growth_stage", "seed_variety"]).rename(columns={
                "growth_stage": "Growth stage", "seed_variety": "Seed variety", "count": "Visits (n)",
                "mean": "Mean height (cm)", "std": "Standard deviation (cm)",
            }).style.format({"Mean height (cm)": "{:.1f}", "Standard deviation (cm)": "{:.1f}"}),
            use_container_width=True, hide_index=True,
        )

    st.markdown("##### Pest or disease rate by seed variety and by channel")
    st.caption("Share of farmers with pest or disease recorded at any visit, with n farmers behind each rate")
    visited = farmer_master[farmer_master["n_crop_health_visits"] > 0]
    by_variety = visited.dropna(subset=["seed_variety"]).groupby("seed_variety").agg(
        farmers=("unique_farmer_id", "nunique"),
        with_pest=("has_pest_disease", lambda values: int((values == True).sum())),
    ).reset_index()
    by_variety["rate"] = by_variety["with_pest"] / by_variety["farmers"]

    channel_rows = melt_flags(visited, CHANNEL_LABELS, "channel").merge(
        visited[["unique_farmer_id", "has_pest_disease"]], on="unique_farmer_id"
    )
    by_channel = channel_rows.groupby("channel").agg(
        farmers=("unique_farmer_id", "nunique"),
        with_pest=("has_pest_disease", lambda values: int((values == True).sum())),
    ).reset_index()
    by_channel["rate"] = by_channel["with_pest"] / by_channel["farmers"]

    left, right = st.columns(2)
    if not by_variety.empty:
        left.dataframe(
            by_variety.rename(columns={
                "seed_variety": "Seed variety", "farmers": "Farmers (n)",
                "with_pest": "With pest or disease", "rate": "Rate",
            }).style.format({"Rate": "{:.0%}"}),
            use_container_width=True, hide_index=True,
        )
    if not by_channel.empty:
        right.dataframe(
            by_channel.rename(columns={
                "channel": "Channel", "farmers": "Farmers (n)",
                "with_pest": "With pest or disease", "rate": "Rate",
            }).style.format({"Rate": "{:.0%}"}),
            use_container_width=True, hide_index=True,
        )
    st.caption("Channel is multi-select, so the channel rows sum to more than the farmer count.")

    st.markdown("##### Quantity distributed against plant height")
    st.caption(
        "Each point is one crop health visit, split by growth stage. Growth stage affects both figures, so read "
        "this within a stage only. This is an association, not evidence that quantity changes height."
    )
    scatter_data = joined.dropna(subset=["quantity_kg", "plant_height_cm"])
    if scatter_data.empty:
        st.info("No visits with both quantity and height in the current selection.")
    else:
        st.altair_chart(
            style(alt.Chart(scatter_data).mark_circle(size=70, color=PALETTE["primary"], opacity=0.75).encode(
                x=alt.X("quantity_kg:Q", title="Quantity distributed (kg)", scale=alt.Scale(zero=True)),
                y=alt.Y("plant_height_cm:Q", title="Plant height (cm)", scale=alt.Scale(zero=True)),
                tooltip=["unique_farmer_id", "growth_stage", "quantity_kg", "plant_height_cm"],
            ).properties(width=200, height=200).facet(
                column=alt.Column("growth_stage:N", title="Growth stage", sort=GROWTH_STAGE_ORDER),
            )),
            use_container_width=False,
        )

    st.markdown("##### Regional watchlist")
    st.caption(
        "Regions ranked for follow up. The score is the mean of the three component rates shown beside it, so the "
        "underlying numbers stay visible rather than hidden inside the score."
    )
    st.dataframe(build_watchlist(farmer_master), use_container_width=True, hide_index=True)


def build_watchlist(farmer_master: pd.DataFrame) -> pd.DataFrame:
    grouped = farmer_master.groupby("region")
    watchlist = grouped.agg(
        farmers=("unique_farmer_id", "nunique"),
        linked=("link_status", lambda values: int((values == "linked").sum())),
        with_distribution=("link_status", lambda values: int((values != "crop_health_only").sum())),
        delivered=("is_delivered", lambda values: int((values == True).sum())),
        visited=("n_crop_health_visits", lambda values: int((values > 0).sum())),
        with_pest=("has_pest_disease", lambda values: int((values == True).sum())),
    ).reset_index()

    watchlist["linkage_rate"] = watchlist["linked"] / watchlist["farmers"]
    watchlist["delivery_rate"] = watchlist["delivered"] / watchlist["with_distribution"].replace(0, pd.NA)
    watchlist["pest_rate"] = watchlist["with_pest"] / watchlist["visited"].replace(0, pd.NA)
    watchlist["follow_up_score"] = (
        (1 - watchlist["linkage_rate"].fillna(0))
        + (1 - watchlist["delivery_rate"].fillna(0))
        + watchlist["pest_rate"].fillna(0)
    ) / 3

    return watchlist.sort_values("follow_up_score", ascending=False).rename(columns={
        "region": "Region", "farmers": "Farmers (n)", "delivery_rate": "Delivery completion",
        "pest_rate": "Pest or disease rate", "linkage_rate": "Linkage rate",
        "follow_up_score": "Follow up score",
    })[[
        "Region", "Farmers (n)", "Delivery completion", "Pest or disease rate", "Linkage rate", "Follow up score",
    ]].style.format({
        "Delivery completion": "{:.0%}", "Pest or disease rate": "{:.0%}",
        "Linkage rate": "{:.0%}", "Follow up score": "{:.2f}",
    })


def render_data_quality(frames: dict, meta: dict) -> None:
    farmer_master = frames["farmer_master"]
    st.subheader("Data quality and assumptions")

    st.markdown("##### Linkage across the two forms")
    st.caption("Farmer records by link status, all submissions to date")
    linkage = farmer_master.groupby("link_status", as_index=False)["unique_farmer_id"].nunique()
    linkage["link_status"] = linkage["link_status"].map({
        "linked": "Linked to both forms",
        "distribution_only": "Distribution only",
        "crop_health_only": "Crop health only",
    })
    if not linkage.empty:
        st.altair_chart(
            style(alt.Chart(linkage, height=220).mark_bar(
                color=PALETTE["primary"], cornerRadiusEnd=4, size=26
            ).encode(
                x=alt.X("unique_farmer_id:Q", title="Farmer records", scale=alt.Scale(zero=True)),
                y=alt.Y("link_status:N", title="Link status", sort="-x"),
                tooltip=["link_status", "unique_farmer_id"],
            )),
            use_container_width=True,
        )

    st.markdown("##### Duplicate submissions resolved")
    st.caption(
        "Resolved before the sheet was written, keeping the most recent submission, so they do not appear as "
        "duplicate rows in the tables above."
    )
    st.dataframe(
        pd.DataFrame([
            {"Form": "Seed distribution", "Duplicates resolved": meta.get("distribution_duplicates_dropped", "unknown")},
            {"Form": "Crop health", "Duplicates resolved": meta.get("crop_health_duplicates_dropped", "unknown")},
        ]),
        use_container_width=True, hide_index=True,
    )

    st.markdown("##### Country or region disagreement")
    st.caption("Farmers whose two forms disagree on location, or whose own repeat visits disagree with each other")
    mismatches = farmer_master[farmer_master["geo_mismatch"] == True][[
        "unique_farmer_id", "country", "region", "country_mismatch", "region_mismatch", "link_status",
    ]]
    if mismatches.empty:
        st.info("No geographic disagreement in the current selection.")
    else:
        st.dataframe(
            mismatches.rename(columns={
                "unique_farmer_id": "Farmer ID", "country": "Country", "region": "Region",
                "country_mismatch": "Country disagrees", "region_mismatch": "Region disagrees",
                "link_status": "Link status",
            }),
            use_container_width=True, hide_index=True,
        )

    st.markdown("##### Missing value rate by field")
    st.caption("Share of rows with no value recorded, by field, all submissions to date")
    st.dataframe(missing_value_rates(frames), use_container_width=True, hide_index=True)

    st.markdown("##### Assumptions")
    st.markdown(
        """
- The two forms are joined on unique_farmer_id after trimming whitespace and converting to upper case. One
  identifier in the sample only matched after this cleaning.
- Country and region validate the join rather than drive it. Disagreement between the forms is reported above
  as a monitoring finding, not silently corrected.
- Where a farmer submitted the same form twice, the most recent submission is kept. For crop health this applies
  only to a repeated growth stage, since separate growth stage visits are expected and are not duplicates.
- Submission timestamps carry no time zone in the API response and are treated as East Africa Time.
- Channel and symptom fields are multi-select, so their totals exceed the number of farmers and visits.
- Plant height is compared only within growth stage, because stage drives height.
- No baseline and no control group exist here, so nothing on this page is a treatment effect. These are
  associations that show where to look, not what caused what.
- Seed delivery is marked complete on every distribution record in this dummy dataset, so the delivery
  completion rate does not vary. Expect that to change with real submissions.
- Each form refreshes on alternating cycles, so one side of the joined table can be up to one cycle behind the
  other. The refresh times for both forms are shown on the overview page.
"""
    )


def missing_value_rates(frames: dict) -> pd.DataFrame:
    rows = []
    for name, label in (("distribution", "Seed distribution"), ("crop_health", "Crop health")):
        frame = frames[name]
        for column in frame.columns:
            rows.append({
                "Form": label,
                "Field": column,
                "Rows (n)": len(frame),
                "Missing rate": frame[column].isna().mean() if len(frame) else float("nan"),
            })
    rates = pd.DataFrame(rows)
    return rates[rates["Missing rate"] > 0].sort_values("Missing rate", ascending=False).style.format(
        {"Missing rate": "{:.0%}"}
    )


def render_farmer_table(frame: pd.DataFrame, key: str) -> None:
    st.markdown("##### Farmer level records")
    query = st.text_input("Search by farmer ID or region", key=f"search_{key}").strip().lower()
    table = frame
    if query:
        haystack = table["unique_farmer_id"].astype(str).str.lower() + " " + table["region"].astype(str).str.lower()
        table = table[haystack.str.contains(query, regex=False)]
    st.caption(f"{len(table)} of {len(frame)} rows shown")
    st.dataframe(table, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="GAIN PMI dashboard", layout="wide")
    st.title("Fortified rice seed distribution and crop health")

    try:
        frames = {tab: typed_tab(tab) for tab in ("distribution", "crop_health", "farmer_master")}
        meta = load_meta()
    except RuntimeError as exc:
        st.error(str(exc))
        return

    filters = sidebar_filters(frames["farmer_master"], frames["crop_health"])
    filtered = apply_filters(frames, filters)

    overview, distribution, crop_health, integrated, quality = st.tabs([
        "Programme overview", "Seed distribution", "Crop health", "Integrated view", "Data quality",
    ])
    with overview:
        render_overview(filtered, meta)
    with distribution:
        render_distribution(filtered)
    with crop_health:
        render_crop_health(filtered)
    with integrated:
        render_integrated(filtered)
    with quality:
        render_data_quality(filtered, meta)


if __name__ == "__main__":
    main()
