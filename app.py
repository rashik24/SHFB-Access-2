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
# ⚡ PLOTLY CHOROPLETH MAPBOX — POLYGON GEOIDs (CLICKABLE + WORKING)
# =========================================================================
import plotly.express as px
import plotly.graph_objects as go
from streamlit_plotly_events import plotly_events
import json
import geopandas as gpd
from shapely.geometry import Point

st.subheader("🗺️ Interactive Access Score Map (Tract Polygons)")

# --- Convert CRS if needed (Plotly expects EPSG:4326)
if tracts_gdf.crs and tracts_gdf.crs.to_string().lower() != "epsg:4326":
    tracts_gdf = tracts_gdf.to_crs(epsg=4326)

# --- Merge your computed data
plot_df = tracts_gdf.merge(
    filtered_df[["GEOID", "Access_Score", "County", "Top_Agencies"]],
    on="GEOID", how="left"
)
plot_df["Access_Score"] = plot_df["Access_Score"].fillna(0.0)
plot_df["County"] = plot_df["County"].fillna("Unknown")

# --- Create GeoJSON (and ensure GEOID key)
tracts_geojson = json.loads(plot_df.to_json())

# --- Choropleth map
fig = px.choropleth_mapbox(
    plot_df,
    geojson=tracts_geojson,
    locations="GEOID",
    featureidkey="properties.GEOID",
    color="Access_Score",
    color_continuous_scale="YlGn",
    hover_data={"GEOID": True, "County": True, "Access_Score": ':.2f'},
    mapbox_style="carto-positron",
    zoom=6,
    center={"lat": plot_df.geometry.centroid.y.mean(), "lon": plot_df.geometry.centroid.x.mean()},
    opacity=0.8,
    height=650,
)

fig.update_layout(
    margin={"r": 0, "t": 40, "l": 0, "b": 0},
    coloraxis_colorbar=dict(title="Access Score"),
    title=f"Access Score — {title_suffix}<br>Urban={urban_sel} min | Rural={rural_sel} min",
)

# --- Display & capture clicks
selected_points = plotly_events(
    fig,
    click_event=True,
    hover_event=False,
    override_height=650,
    key="geo_map_click"
)

st.plotly_chart(fig, use_container_width=True)

# =========================================================================
# 🏢 SHOW TOP AGENCIES + HIGHLIGHT SELECTED POLYGON
# =========================================================================
if selected_points:
    try:
        clicked = selected_points[0]
        lon, lat = clicked["x"], clicked["y"]
        clicked_point = Point(lon, lat)

        # Find which polygon contains the clicked point
        within_mask = plot_df.geometry.contains(clicked_point)
        if within_mask.any():
            clicked_row = plot_df.loc[within_mask].iloc[0]
        else:
            # Fallback: nearest centroid if not inside any polygon
            centroids = plot_df.geometry.centroid
            clicked_row = plot_df.loc[((centroids.x - lon)**2 + (centroids.y - lat)**2).idxmin()]

        geoid_clicked = clicked_row["GEOID"]
        st.success(f"Selected GEOID: {geoid_clicked} (County: {clicked_row['County']})")

        # --- Highlight selected tract
        highlight_layer = go.Choroplethmapbox(
            geojson=tracts_geojson,
            locations=[geoid_clicked],
            featureidkey="properties.GEOID",
            z=[clicked_row["Access_Score"]],
            colorscale=[[0, "red"], [1, "red"]],
            showscale=False,
            marker_line_width=2.5,
            marker_line_color="red",
            opacity=0.6,
            name="Selected GEOID"
        )
        fig.add_trace(highlight_layer)
        st.plotly_chart(fig, use_container_width=True)

        # --- Top agencies
        agencies = json.loads(clicked_row["Top_Agencies"]) if isinstance(
            clicked_row["Top_Agencies"], str) else clicked_row["Top_Agencies"]

        if agencies:
            df_ag = pd.DataFrame(agencies)
            df_ag["Agency_Contribution"] = df_ag["Agency_Contribution"].round(3)
            df_ag = df_ag.sort_values("Agency_Contribution", ascending=False)
            st.write("**Top Agencies for this tract:**")
            st.dataframe(df_ag, use_container_width=True)
            st.bar_chart(df_ag.set_index("Agency_Name")["Agency_Contribution"])
        else:
            st.warning("No agency data for this tract.")
    except Exception as e:
        st.error(f"Error displaying top agencies: {e}")

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

