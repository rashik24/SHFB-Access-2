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
    tracts_gdf = gpd.read_file(TRACT_SHP)[["GEOID", "geometry","NAMELSADCO"]]
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

#st.subheader("🗺️ Access Score Map (Clickable Tracts)")

# # --- Prepare Data
# geoids = filtered_df["GEOID"].astype(str).unique()
# plot_df = tracts_gdf[tracts_gdf["GEOID"].isin(geoids)].merge(
#     filtered_df[["GEOID", "Access_Score", "County", "Top_Agencies"]],
#     on="GEOID", how="left"
# )
# plot_df["Access_Score"] = plot_df["Access_Score"].fillna(0.0)
# plot_df["County"] = plot_df["County"].fillna("Unknown")

# # --- Filter target counties
# target_counties = [
#     "Alamance","Alexander","Alleghany","Ashe","Caldwell","Caswell",
#     "Davidson","Davie","Forsyth","Guilford","Iredell","Randolph",
#     "Rockingham","Stokes","Surry","Watauga","Wilkes","Yadkin"
# ]
# plot_df = plot_df[plot_df["County"].str.title().isin(target_counties)]
# =========================================================================
# 🌍 CLEAN SHAPEFILE + FILTER TO TARGET COUNTIES
# =========================================================================
import json
import geopandas as gpd
import folium
from folium.features import GeoJsonTooltip
from streamlit_folium import st_folium

# --- Clean county names (from NAMELSADCO)
tracts_clean = tracts_gdf.copy()

tracts_clean["County_clean"] = (
    tracts_clean["NAMELSADCO"]
    .astype(str)
    .str.strip()
    .str.replace(r"\s*county$", "", case=False, regex=True)
    .str.title()
)

# --- Filter to your target 17 counties
target_counties = [
    "Alamance","Alexander","Alleghany","Ashe","Caldwell","Caswell",
    "Davidson","Davie","Forsyth","Guilford","Iredell","Randolph",
    "Rockingham","Stokes","Surry","Watauga","Wilkes","Yadkin"
]
tracts_filtered = tracts_clean[tracts_clean["County_clean"].isin(target_counties)].copy()

# --- Merge shapefile with Access + Agency info
plot_df = tracts_filtered.merge(
    filtered_df[["GEOID", "Access_Score", "County", "Top_Agencies"]],
    on="GEOID", how="left"
)

# --- Fill blanks
plot_df["Access_Score"] = plot_df["Access_Score"].fillna(0.0).round(2)
plot_df["County"] = plot_df["County"].fillna(plot_df["County_clean"])
plot_df["Top_Agencies"] = plot_df["Top_Agencies"].fillna("[]")

# --- CRS sanity check
if plot_df.crs and plot_df.crs.to_string().lower() != "epsg:4326":
    plot_df = plot_df.to_crs(epsg=4326)

# =========================================================================
# 🗺️ INTERACTIVE FOLIUM MAP
# =========================================================================
#st.subheader("🗺️ Interactive Access Score Map (Clickable GEOIDs)")

# --- Initialize map
m = folium.Map(location=[36.0, -80.0], zoom_start=7, tiles="cartodb positron")

# --- Normalize color scale
vmin, vmax = 0, float(plot_df["Access_Score"].max())
if not np.isfinite(vmax) or vmax <= vmin:
    vmax = vmin + 1.0

# --- Color function for access scores
colormap = folium.LinearColormap(
    colors=["#f7fcb9", "#31a354"],  # light → dark green
    vmin=vmin, vmax=vmax,
    caption="Access Score"
)

def style_function(feature):
    score = feature["properties"].get("Access_Score", 0)
    return {
        "fillOpacity": 0.7,
        "weight": 0.3,
        "color": "gray",
        "fillColor": colormap(score if score is not None else 0),
    }

# --- Add polygons
folium.GeoJson(
    plot_df,
    name="Access Score Map",
    style_function=style_function,
    tooltip=GeoJsonTooltip(
        fields=["GEOID", "County", "Access_Score"],
        aliases=["GEOID:", "County:", "Access Score:"],
        localize=True
    )
).add_to(m)

colormap.add_to(m)

# --- Display map in Streamlit
map_output = st_folium(m, width=700, height=600)

# =========================================================================
# 🏢 SHOW CLICKED GEOID’S TOP AGENCIES
# =========================================================================
st.subheader("🏢 Top Agencies for Selected GEOID")

if map_output and map_output.get("last_active_drawing"):
    try:
        clicked_geoid = map_output["last_active_drawing"]["properties"].get("GEOID")
        if clicked_geoid:
            st.success(f"Selected GEOID: {clicked_geoid}")

            row = plot_df[plot_df["GEOID"] == clicked_geoid]
            if not row.empty:
                agencies_raw = row.iloc[0]["Top_Agencies"]
                agencies = json.loads(agencies_raw) if isinstance(agencies_raw, str) else agencies_raw

                if agencies:
                    df_ag = pd.DataFrame(agencies)
                    df_ag["Agency_Contribution"] = df_ag["Agency_Contribution"].round(2)
                    st.dataframe(df_ag, use_container_width=True)
                else:
                    st.warning("No agencies found for this GEOID.")
            else:
                st.warning("No matching GEOID in the dataset.")
    except Exception as e:
        st.error(f"⚠️ Error reading GEOID click: {e}")
else:
    st.info("Click on a tract to view top agencies.")


# =========================================================================
# 📊 SUMMARY + TOP/BOTTOM TRACTS
# =========================================================================
st.subheader("🏆 Top and Bottom Tracts by Access Score")

col1, col2 = st.columns(2)

# Top 10 tracts
col1.write("**Top 10 Tracts**")
top10 = (
    filtered_df.nlargest(10, "Access_Score")[["GEOID", "County", "Access_Score"]]
    .copy()
    .reset_index(drop=True)
)
top10["Access_Score"] = top10["Access_Score"].round(2)
col1.dataframe(top10)

# Bottom 10 tracts
col2.write("**Bottom 10 Tracts**")
bottom10 = (
    filtered_df.nsmallest(10, "Access_Score")[["GEOID", "County", "Access_Score"]]
    .copy()
    .reset_index(drop=True)
)
bottom10["Access_Score"] = bottom10["Access_Score"].round(2)
col2.dataframe(bottom10)
