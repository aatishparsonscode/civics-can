import streamlit as st
import zipfile
import json
import io
import pandas as pd
import folium
from streamlit_folium import st_folium
import base64
import os

from folium.plugins import MarkerCluster

CLASS_MAP = {
    0: "Longitudinal Crack (D00)",
    1: "Transverse Crack (D10)",
    2: "Alligator Crack (D20)",
    3: "Pothole (D40)"
}

# ---------------------------
# CONFIG
# ---------------------------
st.set_page_config(layout="wide", initial_sidebar_state="collapsed")
st.title("Road Survey Visualization")

# ---------------------------
# Sidebar: Load multiple ZIPs (fallback to assets folder)
# ---------------------------
uploaded_zips = None

if not uploaded_zips:
    assets_folder = "assets/"
    try:
        uploaded_zips = []
        for fname in os.listdir(assets_folder):
            if fname.endswith(".zip"):
                with open(os.path.join(assets_folder, fname), "rb") as f:
                    uploaded_zips.append(io.BytesIO(f.read()))
    except Exception as e:
        st.error(f"No uploads and no assets found. {e}")
        st.stop()

# ---------------------------
# Load all surveys
# ---------------------------
all_detections = []
all_roughness = []

if "images_cache" not in st.session_state:
    st.session_state["images_cache"] = {}

for idx, uploaded in enumerate(uploaded_zips):
    survey_name = getattr(uploaded, 'name', f"Survey_{idx+1}")
    if survey_name.endswith(".zip"):
        survey_name = survey_name[:-4]

    try:
        with zipfile.ZipFile(uploaded) as z:
            print(f"✅ Processing {survey_name}: {z.namelist()}")

            with z.open("metadata.json") as meta_file:
                metadata = json.load(meta_file)

            detections = metadata.get("detections", [])
            for d in detections:
                d["survey"] = survey_name
            all_detections.extend(detections)

            roughness = metadata.get("roughness", [])
            for r in roughness:
                r["survey"] = survey_name
            all_roughness.extend(roughness)

            # Cache images
            image_files = [f for f in z.namelist() if f.lower().endswith(".jpg")]
            for image_file in image_files:
                with z.open(image_file) as img_file:
                    img_bytes = img_file.read()
                    st.session_state["images_cache"][(survey_name, image_file)] = img_bytes

    except Exception as e:
        st.error(f"Failed to read {survey_name}: {e}")

# ---------------------------
# Build DataFrames
# ---------------------------
det_df = pd.DataFrame(all_detections)
if not det_df.empty:
    det_df["class"] = det_df["class"].map(CLASS_MAP)

rough_df = pd.DataFrame(all_roughness)

# Drop rows without coordinates
if not det_df.empty:
    det_df = det_df.dropna(subset=["latitude", "longitude"])
if not rough_df.empty:
    rough_df = rough_df.dropna(subset=["latitude", "longitude"])

if det_df.empty and rough_df.empty:
    st.warning("No valid detection or roughness data found in any ZIP!")
    st.stop()

# ---------------------------
# Sidebar filters
# ---------------------------
det_surveys = det_df["survey"].unique() if "survey" in det_df.columns else []
rough_surveys = rough_df["survey"].unique() if "survey" in rough_df.columns else []
all_surveys = sorted(set(det_surveys).union(rough_surveys))

selected_surveys = st.sidebar.multiselect(
    "Select surveys to display",
    options=all_surveys,
    default=all_surveys
)

show_detections = st.sidebar.checkbox("Show Detections", value=True)
show_roughness = st.sidebar.checkbox("Show Roughness", value=True)

# Apply filters
if not det_df.empty:
    det_df = det_df[det_df["survey"].isin(selected_surveys)]
if not rough_df.empty:
    rough_df = rough_df[rough_df["survey"].isin(selected_surveys)]

if not show_detections:
    det_df = det_df.iloc[0:0]
if not show_roughness:
    rough_df = rough_df.iloc[0:0]

if det_df.empty and rough_df.empty:
    st.warning("No data for selected surveys after filtering.")
    st.stop()

# ---------------------------
# Map center
# ---------------------------
all_lats = pd.Series(dtype=float)
all_lons = pd.Series(dtype=float)

if not det_df.empty:
    all_lats = pd.concat([all_lats, det_df["latitude"]])
    all_lons = pd.concat([all_lons, det_df["longitude"]])
if not rough_df.empty:
    all_lats = pd.concat([all_lats, rough_df["latitude"]])
    all_lons = pd.concat([all_lons, rough_df["longitude"]])

if all_lats.empty or all_lons.empty:
    st.warning("No valid coordinates found after filtering.")
    st.stop()

center_lat = all_lats.mean()
center_lon = all_lons.mean()

# ---------------------------
# Create Folium Map
# ---------------------------
m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=16,
    max_zoom=30,  # allow zooming in much further
    min_zoom=2    # optional: allow zooming far out
    
)

# Add Marker Clusters
detection_cluster = MarkerCluster(name="Detections").add_to(m)
roughness_cluster = MarkerCluster(name="Roughness").add_to(m)

# ---------------------------
# Add detections with clustering
# ---------------------------
if not det_df.empty:
    for _, row in det_df.iterrows():
        frame_num = row["frame"]
        survey_name = row["survey"]

        popup_html = f"""
        <b>Coordinates:</b> {row['latitude']:.5f}, {row['longitude']:.5f}<br>
        """

        img_bytes = None
        frame_num_str = str(int(frame_num))
        for (survey, filename), img in st.session_state["images_cache"].items():
            if survey == survey_name and filename.lower().rstrip(".jpg").endswith(frame_num_str):
                img_bytes = img
                break

        if img_bytes:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            img_tag = f'<img src="data:image/jpeg;base64,{b64}" width="600">'
            popup_html += img_tag
        else:
            popup_html += "<i>(Image missing)</i>"

        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            popup=folium.Popup(popup_html, max_width=600),
            icon=folium.Icon(color="red", icon="exclamation-triangle", prefix="fa")
        ).add_to(detection_cluster)

# ---------------------------
# Add roughness with clustering
# ---------------------------
if not rough_df.empty:
    for _, row in rough_df.iterrows():
        survey_name = row["survey"]
        popup_html = f"""
        <b>Coordinates:</b> {row['latitude']:.5f}, {row['longitude']:.5f}<br>
        <b>Magnitude:</b> {row['magnitude_xy']:.2f}
        """

        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            popup=folium.Popup(popup_html, max_width=600),
            icon=folium.Icon(color="orange", icon="car", prefix="fa")
        ).add_to(roughness_cluster)

# Add layer control only if there's at least one layer
if not det_df.empty or not rough_df.empty:
    folium.LayerControl().add_to(m)

# ---------------------------
# Show map
# ---------------------------
st.subheader("Map View")
st_data = st_folium(m, width=None, height=600, use_container_width=True)

# ---------------------------
# Show tables
# ---------------------------
with st.expander("Detections Table"):
    if not det_df.empty:
        st.dataframe(det_df[["latitude", "longitude", "class"]])
    else:
        st.info("No detections data to display.")

with st.expander("Roughness Table"):
    if not rough_df.empty:
        st.dataframe(rough_df[["latitude", "longitude", "magnitude_xy"]])
    else:
        st.info("No roughness data to display.")
