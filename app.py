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
# ⚡ ULTRA-FAST INTERACTIVE ACCESS SCORE MAP (CENTROID VERSION)
# =========================================================================
from streamlit_folium import st_folium
import folium
import json
from shapely.geometry import Point

st.subheader("🗺️ Fast Interactive Access Score Map")

# --- 1️⃣ Reduce geometry load: precompute centroids
tracts_centroids = tracts_gdf.copy()
tracts_centroids["geometry"] = tracts_centroids["geometry"].centroid

# --- 2️⃣ Merge access + agency data
plot_df = tracts_centroids.merge(
    filtered_df[["GEOID", "Access_Score", "County", "Top_Agencies"]],
    on="GEOID", how="left"
)
plot_df["Access_Score"] = plot_df["Access_Score"].fillna(0.0)
plot_df["County"] = plot_df["County"].fillna("Unknown")

# --- 3️⃣ Create folium map
m = folium.Map(location=[35.6, -79.5], zoom_start=7, tiles="cartodbpositron")

# --- 4️⃣ Normalize colors
vmin, vmax = plot_df["Access_Score"].min(), plot_df["Access_Score"].max()
cmap = plt.get_cmap("YlGn")
norm = plt.Normalize(vmin=vmin, vmax=vmax)

# --- 5️⃣ Add colored centroid circles
for _, row in plot_df.iterrows():
    color = mpl.colors.rgb2hex(cmap(norm(row["Access_Score"])))
    popup_html = f"<b>GEOID:</b> {row['GEOID']}<br><b>County:</b> {row['County']}<br>"
    try:
        agencies = json.loads(row["Top_Agencies"]) if isinstance(row["Top_Agencies"], str) else row["Top_Agencies"]
        if agencies:
            popup_html += "<b>Top Agencies:</b><ul>"
            for ag in agencies:
                popup_html += f"<li>{ag['Name']} ({ag['Agency_Contribution']:.2f})</li>"
            popup_html += "</ul>"
    except Exception:
        popup_html += "<i>No agency data.</i>"

    folium.CircleMarker(
        location=[row.geometry.y, row.geometry.x],
        radius=5,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.9,
        popup=folium.Popup(popup_html, max_width=300),
    ).add_to(m)

# --- 6️⃣ Display map
map_output = st_folium(m, width=800, height=600)

# --- 7️⃣ Optional click: detect nearest centroid (lightweight)
if map_output and "last_clicked" in map_output and map_output["last_clicked"]:
    lat, lon = map_output["last_clicked"]["lat"], map_output["last_clicked"]["lng"]
    dists = ((plot_df.geometry.y - lat)**2 + (plot_df.geometry.x - lon)**2)
    closest_row = plot_df.loc[dists.idxmin()]
    st.success(f"Selected GEOID: {closest_row['GEOID']} (County: {closest_row['County']})")

    # Show top agencies table
    try:
        agencies = json.loads(closest_row["Top_Agencies"]) if isinstance(closest_row["Top_Agencies"], str) else closest_row["Top_Agencies"]
        if agencies:
            st.write("**Top Agencies:**")
            df_ag = pd.DataFrame(agencies)
            df_ag["Agency_Contribution"] = df_ag["Agency_Contribution"].round(3)
            st.dataframe(df_ag, use_container_width=True)
    except Exception:
        st.warning("No agency data for this tract.")


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

