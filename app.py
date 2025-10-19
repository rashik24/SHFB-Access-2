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

# # =========================================================================
# # 🖼️ MAP PLOT
# # =========================================================================
# geoids = filtered_df["GEOID"].astype(str).unique()
# plot_df = tracts_gdf[tracts_gdf["GEOID"].isin(geoids)].merge(
#     filtered_df[["GEOID", "Access_Score", "County"]], on="GEOID", how="left"
# )
# plot_df["Access_Score"] = plot_df["Access_Score"].fillna(0.0)
# plot_df["County"] = plot_df["County"].fillna("Unknown")

# vmin, vmax = 0, float(plot_df["Access_Score"].max())
# if not np.isfinite(vmax) or vmax <= vmin:
#     vmax = vmin + 1.0

# norm = mpl.colors.Normalize(vmin=vmin, vmax=vmax)
# cmap_obj = plt.get_cmap(cmap_choice)

# fig, ax = plt.subplots(figsize=(8, 8))
# plot_df.plot(
#     column="Access_Score",
#     cmap=cmap_obj,
#     norm=norm,
#     linewidth=0,
#     edgecolor="none",
#     legend=True,
#     legend_kwds={"label": "Access Score", "shrink": 0.7},
#     ax=ax
# )
# ax.set_axis_off()
# ax.set_title(
#     f"Access Score — {title_suffix}\nUrban={urban_sel} | Rural={rural_sel}",
#     fontsize=13
# )
# st.pyplot(fig)

# from streamlit_folium import st_folium
# import folium
# import json
# =========================================================================
# ⚡ PLOTLY CHOROPLETH MAPBOX — POLYGON GEOIDs (FAST + CLICKABLE)
# =========================================================================
import plotly.express as px
import plotly.graph_objects as go
from streamlit_plotly_events import plotly_events
import json

st.subheader("🗺️ Interactive Access Score Map (Tract Polygons)")

# --- Prepare GeoJSON
tracts_geojson = json.loads(tracts_gdf.to_json())

# --- Merge access + agency data
plot_df = tracts_gdf.merge(
    filtered_df[["GEOID", "Access_Score", "County", "Top_Agencies"]],
    on="GEOID", how="left"
)
plot_df["Access_Score"] = plot_df["Access_Score"].fillna(0.0)
plot_df["County"] = plot_df["County"].fillna("Unknown")

# --- Build choropleth map
fig = px.choropleth_mapbox(
    plot_df,
    geojson=tracts_geojson,
    locations="GEOID",
    color="Access_Score",
    color_continuous_scale="YlGn",
    hover_data={"GEOID": True, "County": True, "Access_Score": ':.2f'},
    mapbox_style="carto-positron",
    zoom=6,
    center={"lat": 35.5, "lon": -79.5},
    opacity=0.8,
    height=650,
)

fig.update_layout(
    margin={"r": 0, "t": 40, "l": 0, "b": 0},
    coloraxis_colorbar=dict(title="Access Score"),
    title=f"Access Score — {title_suffix}<br>Urban={urban_sel} min | Rural={rural_sel} min",
)

# --- Capture click event
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
        # The click event gives coordinates — find closest GEOID polygon
        lon, lat = clicked["x"], clicked["y"]
        plot_df["dist"] = plot_df.geometry.centroid.distance(
            plot_df.geometry.centroid.iloc[0].__class__(lon, lat)
        )
        clicked_row = plot_df.loc[plot_df["dist"].idxmin()]

        geoid_clicked = clicked_row["GEOID"]
        st.success(f"Selected GEOID: {geoid_clicked} (County: {clicked_row['County']})")

        # --- Highlight selected GEOID boundary
        highlight_layer = go.Choroplethmapbox(
            geojson=tracts_geojson,
            locations=[geoid_clicked],
            z=[clicked_row["Access_Score"]],
            colorscale=[[0, "red"], [1, "red"]],
            showscale=False,
            marker_line_width=2.5,
            marker_line_color="red",
            opacity=0.8,
            name="Selected GEOID"
        )
        fig.add_trace(highlight_layer)
        st.plotly_chart(fig, use_container_width=True)

        # --- Display Top Agencies
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

