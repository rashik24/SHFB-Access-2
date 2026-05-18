import streamlit as st
import pandas as pd
import geopandas as gpd
import numpy as np
import json

# =========================================================================
# 📂 FILE LOCATIONS
# =========================================================================
#PRECOMPUTED_FILE = "precomputed_access_scores_SHFB.parquet"
PRECOMPUTED_FILE = "precomputed_access_scores.parquet"
TRACT_SHP        = "cb_2023_37_tract_500k.shp"
GEO_MAP_FILE     = "GeoID RUCA.csv"


# =========================================================================
# ⚡ OPTIMIZED LOADERS
# =========================================================================
@st.cache_resource(show_spinner=False)
def load_static_geo():
    geo_map = pd.read_csv(GEO_MAP_FILE, dtype=str, usecols=["GEOID_x", "County_x"])
    tracts_gdf = gpd.read_file(TRACT_SHP)[["GEOID", "geometry","NAMELSADCO"]]
    return geo_map, tracts_gdf

@st.cache_resource(show_spinner=False)
def load_scores():
    return pd.read_parquet(PRECOMPUTED_FILE)

geo_map, tracts_gdf = load_static_geo()
pre_df = load_scores()


# =========================================================================
# 🎛️ FILTERS
# =========================================================================
st.title("🗺️ SHFB Access Score Dashboard")
st.sidebar.header("🔧 Filters")

urban_sel = st.sidebar.selectbox("Urban Threshold (minutes)", sorted(pre_df["urban_threshold"].unique()))
rural_sel = st.sidebar.selectbox("Rural Threshold (minutes)", sorted(pre_df["rural_threshold"].unique()))

week_sel  = st.sidebar.selectbox("Select Week", ["All"] + sorted(pre_df["week"].unique()))
day_sel   = st.sidebar.selectbox("Select Day", ["All"] + sorted(pre_df["day"].unique()))
# Build AM/PM hour labels
hour_options = ["All"] + [f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}" for h in range(24)]
hour_sel = st.sidebar.selectbox("Select Hour", hour_options)

def parse_hour(h_label):
    """Convert '3 PM' → 15, '12 AM' → 0, etc."""
    if h_label == "All":
        return "All"
    value, period = h_label.split()
    value = int(value)
    if period == "AM":
        return 0 if value == 12 else value
    else:  # PM
        return 12 if value == 12 else value + 12
hour_value = parse_hour(hour_sel)

after_hours = st.sidebar.checkbox("Show After Hours (≥5 PM)", value=False)


# =========================================================================
# 🎯 FILTER BASE DATA
# =========================================================================
df = pre_df.copy()

df = df[(df["urban_threshold"] == urban_sel) & (df["rural_threshold"] == rural_sel)]

if week_sel != "All":
    df = df[df["week"] == week_sel]

if day_sel != "All":
    df = df[df["day"] == day_sel]

if hour_value != "All" and not after_hours:
    df = df[df["hour"] == hour_value]


if after_hours:
    df = df[df["hour"] >= 17]

if df.empty:
    st.warning("No data available.")
    st.stop()


# =========================================================================
# 📊 AVERAGE OVER UNSELECTED DIMENSIONS
# =========================================================================
filtered_df = (
    df.groupby("GEOID", as_index=False)
      .agg({
          "Access_Score": "mean",
          "Top_Agencies": "first"
      })
)

filtered_df["Access_Score"] = filtered_df["Access_Score"].round(2)


# =========================================================================
# 🏷️ TITLE SUFFIX
# =========================================================================
parts = []
parts.append(f"Week {week_sel}" if week_sel != "All" else "Avg Weeks")
parts.append(day_sel if day_sel != "All" else "Avg Days")

if after_hours:
    parts.append("After Hours ≥5PM")
else:
    parts.append(hour_sel if hour_sel != "All" else "Avg Hours")


title_suffix = " | ".join(parts)


# =========================================================================
# 🌍 MERGE COUNTY INFO
# =========================================================================
geo_map_subset = geo_map.rename(columns={"GEOID_x": "GEOID"})
filtered_df = filtered_df.merge(
    geo_map_subset[["GEOID", "County_x"]],
    on="GEOID",
    how="left"
)
filtered_df.rename(columns={"County_x": "County"}, inplace=True)


# =========================================================================
# 🌍 SHAPEFILE CLEANING + MERGE
# =========================================================================
tracts_clean = tracts_gdf.copy()
tracts_clean["County_clean"] = (
    tracts_clean["NAMELSADCO"]
    .astype(str)
    .str.strip()
    .str.replace(r"\s*county$", "", case=False, regex=True)
    .str.title()
)

target_counties = [
    "Alamance","Alexander","Alleghany","Ashe","Caldwell","Caswell",
    "Davidson","Davie","Forsyth","Guilford","Iredell","Randolph",
    "Rockingham","Stokes","Surry","Watauga","Wilkes","Yadkin"
]

tracts_filtered = tracts_clean[tracts_clean["County_clean"].isin(target_counties)].copy()

plot_df = tracts_filtered.merge(
    filtered_df[["GEOID", "Access_Score", "County", "Top_Agencies"]],
    on="GEOID",
    how="left"
)

plot_df["Access_Score"] = plot_df["Access_Score"].fillna(0.0).round(2)
plot_df["County"] = plot_df["County"].fillna(plot_df["County_clean"])
plot_df["Top_Agencies"] = plot_df["Top_Agencies"].fillna("[]")

if plot_df.crs and plot_df.crs.to_string().lower() != "epsg:4326":
    plot_df = plot_df.to_crs(epsg=4326)


# =========================================================================
# 🌍 FOLIUM MAP
# =========================================================================
import folium
from folium.features import GeoJsonTooltip
from streamlit_folium import st_folium

m = folium.Map(location=[36.0, -80.0], zoom_start=7, tiles="cartodb positron")

# vmin, vmax = 0, float(plot_df["Access_Score"].max())
# if not np.isfinite(vmax) or vmax <= vmin:
#     vmax = vmin + 1

# colormap = folium.LinearColormap(
#     colors=["#31a354", "#f7fcb9"],
#     vmin=vmin, vmax=vmax,
#     caption="Access Score"
# )

# def style_function(feature):
#     score = feature["properties"].get("Access_Score", 0)
#     return {
#         "fillOpacity": 0.7,
#         "weight": 0.3,
#         "color": "gray",
#         "fillColor": colormap(score),
#     }
vmin = 0
vmax = float(plot_df["Access_Score"].quantile(0.95))

if not np.isfinite(vmax) or vmax <= vmin:
    vmax = vmin + 1

colormap = folium.LinearColormap(
    #colors=["#f7fcb9", "#addd8e", "#31a354", "#006837"],
      colors=["#99000d", "#cb181d", "#fb6a4a", "#fee5d9"],
    vmin=vmin,
    vmax=vmax,
    caption="Access Score"
)

def style_function(feature):
    score = feature["properties"].get("Access_Score", 0)
    score = min(score, vmax)

    return {
        "fillOpacity": 0.75,
        "weight": 0.3,
        "color": "gray",
        "fillColor": colormap(score),
    }
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

map_output = st_folium(m, width=700, height=600)


# =========================================================================
# 🏢 CLICKED GEOID → AGENCIES
# =========================================================================
st.subheader("🏢 Top Agencies for Selected GEOID")

if map_output and map_output.get("last_active_drawing"):
    try:
        geoid = map_output["last_active_drawing"]["properties"].get("GEOID")
        if geoid:
            st.success(f"Selected GEOID: {geoid}")
            row = plot_df[plot_df["GEOID"] == geoid]
            if not row.empty:
                raw = row.iloc[0]["Top_Agencies"]
                agencies = json.loads(raw) if isinstance(raw, str) else raw

                if agencies:
                    df_ag = pd.DataFrame(agencies)
                    df_ag["Agency_Contribution"] = df_ag["Agency_Contribution"].round(2)
                    st.dataframe(df_ag, use_container_width=True)
                else:
                    st.warning("No agencies found.")
            else:
                st.warning("GEOID not present in dataset.")
    except Exception as e:
        st.error(f"Error reading click: {e}")
else:
    st.info("Click on a census tract to view agency info.")


# =========================================================================
# 📊 TOP / BOTTOM 10
# =========================================================================
st.subheader("🏆 Top and Bottom Tracts by Access Score")

col1, col2 = st.columns(2)

top10 = filtered_df.nlargest(10, "Access_Score")[["GEOID", "County", "Access_Score"]]
bottom10 = filtered_df.nsmallest(10, "Access_Score")[["GEOID", "County", "Access_Score"]]

col1.write("**Top 10 Tracts**")
col1.dataframe(top10.reset_index(drop=True))

col2.write("**Bottom 10 Tracts**")
col2.dataframe(bottom10.reset_index(drop=True))
