import streamlit as st
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np
import json

# =========================================================================
# 📂 FILE LOCATIONS
# =========================================================================
PRECOMPUTED_FILE = "precomputed_access_scores.parquet"
TRACT_SHP        = "cb_2023_37_tract_500k.shp"
GEO_MAP_FILE     = "GeoID RUCA.csv"

# =========================================================================
# ⚡ OPTIMIZED LOADERS
# =========================================================================
@st.cache_resource(show_spinner=False)
def load_static_geo():
    """Load static geometry once and cache it."""
    geo_map = pd.read_csv(GEO_MAP_FILE, dtype=str, usecols=["GEOID_x", "County_x"])
    tracts_gdf = gpd.read_file(TRACT_SHP)[["GEOID", "geometry"]]
    return geo_map, tracts_gdf

@st.cache_resource(show_spinner=False)
def load_scores():
    """Load precomputed access scores (parquet)."""
    return pd.read_parquet(PRECOMPUTED_FILE)

geo_map, tracts_gdf = load_static_geo()
pre_df = load_scores()

# =========================================================================
# 🎛️ SIDEBAR FILTERS
# =========================================================================
st.title("🗺️ SHFB Access Score Dashboard")

st.sidebar.header("🔧 Filters")

urban_sel = st.sidebar.selectbox("Urban Threshold (minutes)", sorted(pre_df["urban_threshold"].unique()))
rural_sel = st.sidebar.selectbox("Rural Threshold (minutes)", sorted(pre_df["rural_threshold"].unique()))
week_sel  = st.sidebar.selectbox("Select Week", sorted(pre_df["week"].unique()))
day_sel   = st.sidebar.selectbox("Select Day", sorted(pre_df["day"].unique()))
hour_sel  = st.sidebar.slider("Select Hour", 0, 23, 10)
after_hours = st.sidebar.checkbox("Show After Hours (≥5 PM)", value=False)

cmap_choice = st.sidebar.selectbox(
    "Select Colormap", ["Greens", "YlGn", "BuGn", "YlGnBu", "viridis"]
)

# =========================================================================
# 🔍 FILTER THE DATA
# =========================================================================
if after_hours:
    filtered_df = pre_df[
        (pre_df["urban_threshold"] == urban_sel) &
        (pre_df["rural_threshold"] == rural_sel) &
        (pre_df["week"] == week_sel) &
        (pre_df["day"] == day_sel) &
        (pre_df["hour"] >= 17)
    ].copy()
    title_suffix = f"After Hours (≥5PM), Week {week_sel}, {day_sel}"
else:
    filtered_df = pre_df[
        (pre_df["urban_threshold"] == urban_sel) &
        (pre_df["rural_threshold"] == rural_sel) &
        (pre_df["week"] == week_sel) &
        (pre_df["day"] == day_sel) &
        (pre_df["hour"] == hour_sel)
    ].copy()
    title_suffix = f"Week {week_sel}, {day_sel}, {hour_sel:02d}:00"

if filtered_df.empty:
    st.warning("No data available for this combination.")
    st.stop()

# =========================================================================
# 🌍 MERGE WITH COUNTY INFO
# =========================================================================
geo_map_subset = geo_map.rename(columns={"GEOID_x": "GEOID"})
filtered_df = filtered_df.merge(geo_map_subset[["GEOID", "County_x"]], on="GEOID", how="left")
filtered_df.rename(columns={"County_x": "County"}, inplace=True)

# =========================================================================
# =========================================================================
# 🌍 CLICKABLE STATIC-STYLE MAP (USING FOLIUM)
# =========================================================================
import folium
from folium.features import GeoJsonTooltip, GeoJsonPopup
from streamlit_folium import st_folium
import json

st.subheader("🗺️ Access Score Map (Clickable Tracts)")

# --- Prepare Data
geoids = filtered_df["GEOID"].astype(str).unique()
plot_df = tracts_gdf[tracts_gdf["GEOID"].isin(geoids)].merge(
    filtered_df[["GEOID", "Access_Score", "County", "Top_Agencies"]],
    on="GEOID", how="left"
)
plot_df["Access_Score"] = plot_df["Access_Score"].fillna(0.0)
plot_df["County"] = plot_df["County"].fillna("Unknown")

# --- Filter target counties
target_counties = [
    "Alamance","Alexander","Alleghany","Ashe","Caldwell","Caswell",
    "Davidson","Davie","Forsyth","Guilford","Iredell","Randolph",
    "Rockingham","Stokes","Surry","Watauga","Wilkes","Yadkin"
]
plot_df = plot_df[plot_df["County"].str.title().isin(target_counties)]

# --- CRS check
if plot_df.crs and plot_df.crs.to_string().lower() != "epsg:4326":
    plot_df = plot_df.to_crs(epsg=4326)

# --- Build popup text inside DataFrame
def make_popup_html(row):
    geoid = row["GEOID"]
    county = row["County"]
    score = round(row["Access_Score"], 3)
    agencies = row["Top_Agencies"]

    try:
        ag_list = json.loads(agencies) if isinstance(agencies, str) else agencies
        ag_html = "".join(
            f"<li>{a['Name']} — {a['Agency_Contribution']:.3f}</li>" for a in ag_list[:3]
        )
    except Exception:
        ag_html = "<i>No agency data</i>"

    return f"""
    <b>GEOID:</b> {geoid}<br>
    <b>County:</b> {county}<br>
    <b>Access Score:</b> {score}<br>
    <b>Top Agencies:</b><ul>{ag_html}</ul>
    """

plot_df["popup_html"] = plot_df.apply(make_popup_html, axis=1)

# --- Convert to GeoJSON safely
tracts_geojson = json.loads(plot_df.to_json())

# --- Build folium map
center_lat = plot_df.geometry.centroid.y.mean()
center_lon = plot_df.geometry.centroid.x.mean()
m = folium.Map(location=[center_lat, center_lon], zoom_start=7, tiles="cartodbpositron")

vmin, vmax = plot_df["Access_Score"].min(), plot_df["Access_Score"].max()
colormap = folium.LinearColormap(
    colors=["#ffffcc", "#78c679", "#238443"],
    vmin=vmin, vmax=vmax, caption="Access Score"
)

geo_layer = folium.GeoJson(
    tracts_geojson,
    name="Access Scores",
    style_function=lambda feature: {
        "fillColor": colormap(feature["properties"]["Access_Score"]),
        "color": "black",
        "weight": 0.3,
        "fillOpacity": 0.7,
    },
    tooltip=GeoJsonTooltip(
        fields=["GEOID", "County", "Access_Score"],
        aliases=["GEOID:", "County:", "Access Score:"],
        localize=True,
        sticky=False,
    ),
    popup=GeoJsonPopup(
        fields=["popup_html"],
        aliases=[""],
        labels=False,
        localize=True,
        parse_html=True,
    ),
)

geo_layer.add_to(m)
colormap.add_to(m)

map_output = st_folium(m, width=750, height=620)

# =========================================================================
# 🏢 SHOW CLICKED TRACT’S TOP AGENCIES BELOW
# =========================================================================
if map_output and map_output.get("last_active_drawing"):
    geoid_clicked = map_output["last_active_drawing"]["properties"].get("GEOID")
    if geoid_clicked:
        st.success(f"Selected GEOID: {geoid_clicked}")
        row = filtered_df.loc[filtered_df["GEOID"] == geoid_clicked].head(1)
        if not row.empty:
            top_agencies = row["Top_Agencies"].iloc[0]
            try:
                agencies = json.loads(top_agencies) if isinstance(top_agencies, str) else top_agencies
                df_ag = pd.DataFrame(agencies)
                st.dataframe(df_ag, use_container_width=True)
            except Exception as e:
                st.warning(f"Could not parse agencies for this GEOID: {e}")

# =========================================================================
# 📊 SUMMARY + TOP/BOTTOM TRACTS
# =========================================================================
st.subheader("📊 Summary Statistics")
summary = filtered_df["Access_Score"].describe().to_frame().T
st.dataframe(summary)

st.subheader("🏆 Top and Bottom Tracts by Access Score")
col1, col2 = st.columns(2)
col1.write("**Top 10 Tracts**")
col1.dataframe(filtered_df.nlargest(10, "Access_Score")[["GEOID", "County", "Access_Score"]].reset_index(drop=True))
col2.write("**Bottom 10 Tracts**")
col2.dataframe(filtered_df.nsmallest(10, "Access_Score")[["GEOID", "County", "Access_Score"]].reset_index(drop=True))

