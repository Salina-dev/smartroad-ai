import os
import csv
import time
import tempfile
import datetime
import json
import sqlite3 
import pathlib
from pathlib import Path
import urllib.request
from streamlit_js_eval import get_geolocation
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase
import av


import streamlit as st
import folium
from streamlit_folium import st_folium
import streamlit.components.v1 as components
import streamlit_folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import cv2
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas

from db import Database
from detector import RoadDamageDetector, ROAD_DAMAGE_CLASSES
from report_generator import ReportGenerator
from notifications import check_detections, reset_dedup, init_notification_system

# App configuration
st.set_page_config(
    page_title="SmartRoad AI - Road Damage Monitoring",
    page_icon="🚧",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_PATH = Path("smartroad.db")
CONFIG_PATH = Path("config.json")
DEFAULT_MODEL_PATH = Path("models/best.pt")

def load_config():
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text())
            if "model_path" not in config:
                config["model_path"] = str(DEFAULT_MODEL_PATH)
            return config
        except Exception:
            pass
    default_config = {"model_path": str(DEFAULT_MODEL_PATH)}
    save_config(default_config)
    return default_config


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


def reverse_geocode(latitude, longitude):
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={latitude}&lon={longitude}&zoom=12&addressdetails=1"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "SmartRoad-AI-Location/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            address = data.get("address", {})
            return {
                "country": address.get("country") or "",
                "state": address.get("state") or address.get("region") or "",
                "district": address.get("county") or address.get("state_district") or address.get("region") or "",
                "city": address.get("city") or address.get("town") or address.get("village") or "",
                "area": (
                    address.get("suburb")
                    or address.get("neighbourhood")
                    or address.get("quarter")
                    or address.get("hamlet")
                    or ""
                ),
                "road": (
                    address.get("road")
                    or address.get("pedestrian")
                    or address.get("residential")
                    or address.get("path")
                    or address.get("street")
                    or ""
                ),
            }
    except Exception as exc:
        print(f"[location] Reverse geocode failed: {exc}")
        return {"country": "", "state": "", "district": "", "city": "", "area": "", "road": ""}


def get_geolocation_query():
    if not hasattr(st, "get_query_params"):
        return None, None

    try:
        params = st.get_query_params()
    except Exception:
        return None, None

    lat_vals = params.get("geo_lat") or params.get("geoLat") or [None]
    lon_vals = params.get("geo_lon") or params.get("geoLon") or [None]
    lat = lat_vals[0]
    lon = lon_vals[0]
    if lat is None or lon is None:
        return None, None

    try:
        latitude = float(lat)
        longitude = float(lon)
    except ValueError:
        return None, None

    if hasattr(st, "set_query_params"):
        try:
            st.set_query_params(**{})
        except Exception:
            pass

    return latitude, longitude


def populate_location_from_query():
    latitude, longitude = get_geolocation_query()
    if latitude is None or longitude is None:
        return

    geo_info = reverse_geocode(latitude, longitude)
    st.session_state.loc_lat = str(latitude)
    st.session_state.loc_lon = str(longitude)
    st.session_state.loc_country = geo_info.get("country", "")
    st.session_state.loc_state = geo_info.get("state", "")
    st.session_state.loc_district = geo_info.get("district", "")
    st.session_state.loc_city = geo_info.get("city", "")
    st.session_state.loc_area = geo_info.get("area", "")
    st.session_state.loc_road = geo_info.get("road", "")
    st.session_state.gps_last_updated = datetime.datetime.now().isoformat()
    st.session_state.gps_status = "Connected"


config = load_config()
MODEL_PATH = Path(config.get("model_path", "models/best.pt"))

# Create directories
Path("reports").mkdir(exist_ok=True)
Path("uploads").mkdir(exist_ok=True)
Path("models").mkdir(exist_ok=True)

# Initialize services
db = Database(DB_PATH)
db.initialize()
detector = RoadDamageDetector(model_path=MODEL_PATH)
reporter = ReportGenerator()

# Inject custom styles
st.markdown(
    """
    <style>
    .css-1d391kg {padding-top: 0rem;}
    .main .block-container {padding-top: 1rem;}
    .reportview-container .main .block-container {max-width: 1500px;}
    .stButton>button {border-radius: 8px;}
    .stSelectbox>div>div>div>select {background:#0e1117;color:#fff;}
    footer {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

# Session helpers
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "user" not in st.session_state:
    st.session_state.user = None

if "nav" not in st.session_state:
    st.session_state.nav = "Home"

# initialize GPS/session keys so inputs can use them safely
for k in ("loc_lat", "loc_lon", "loc_country", "loc_state", "loc_district", "loc_city", "loc_area", "loc_road", "gps_last_updated", "gps_status"):
    if k not in st.session_state:
        st.session_state[k] = ""
populate_location_from_query()


def login_form():
    st.title("SmartRoad AI Login")
    with st.form("login_form"):
        email = st.text_input("Email Address")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        user = db.get_user_by_email(email)
        if user and db.verify_password(password, user["password_hash"]):
            st.session_state.authenticated = True
            st.session_state.user = {
                "id": user[0],
                "full_name": user[1],
                "email": user[2],
                "mobile": user[3],
                "department": user[4],
            }
            st.success(f"Welcome, {user[1]}!")
            st.rerun()
        else:
            st.error("Incorrect email or password.")

    st.markdown("---")
    st.info("New user? Register below.")
    with st.form("register_form"):
        full_name = st.text_input("Full Name", key="reg_name")
        mobile = st.text_input("Mobile Number", key="reg_mobile")
        department = st.text_input("Organization / Department", key="reg_org")
        reg_email = st.text_input("Email Address", key="reg_email")
        reg_password = st.text_input("Password", type="password", key="reg_password")
        password_confirm = st.text_input("Confirm Password", type="password", key="reg_confirm")
        register = st.form_submit_button("Register")

    if register:
        if not full_name or not reg_email or not reg_password:
            st.error("Please fill all required fields.")
            return

        if reg_password != password_confirm:
            st.error("Passwords do not match.")
            return

        # bcrypt supports only up to 72 bytes; we'll normalize in the DB layer,
        # but still provide a user-friendly validation here.
        if len(reg_password.encode("utf-8")) > 1024:
            st.error("Password is too long. Please use a shorter password.")
            return

        if db.get_user_by_email(reg_email):
            st.error("An account with this email already exists.")
            return

        try:
            db.create_user(
                full_name,
                reg_email,
                mobile,
                department,
                reg_password
            )
            st.success("Registration complete. Please login.")
        except Exception as e:
            st.error(f"Registration failed: {e}")

def sidebar_navigation():
    st.sidebar.title("SmartRoad AI")
    st.sidebar.markdown("___")
    st.sidebar.write(f"**Logged in as**\n{st.session_state.user['full_name']}")
    selection = st.sidebar.radio(
        "Navigation",
        [
            "Home",
            "Upload Image",
            "Upload Video",
            "Live Camera Detection",
            "GPS & Location Tracking",
            "Detection History",
            "Analytics Dashboard",
            "Report Generation",
            "User Profile",
            "Settings",
            "Logout",
        ],
        index=[
            "Home",
            "Upload Image",
            "Upload Video",
            "Live Camera Detection",
            "GPS & Location Tracking",
            "Detection History",
            "Analytics Dashboard",
            "Report Generation",
            "User Profile",
            "Settings",
            "Logout",
        ].index(st.session_state.nav),
    )
    st.session_state.nav = selection


def show_home():
    # Fetch Data
    user_id = st.session_state.user["id"]
    metrics = db.get_dashboard_metrics(user_id)
    records = db.get_detection_history(user_id)
    recent_events = db.get_detection_events(user_id, limit=5)
    
    # Custom CSS for Glassmorphism and enterprise-grade UI
    st.markdown("""
        <style>
        /* Glassmorphism KPI Cards */
        .kpi-container {
            display: flex;
            gap: 1.5rem;
            margin-bottom: 2rem;
            flex-wrap: wrap;
        }
        .kpi-card {
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 1.5rem;
            flex: 1;
            min-width: 200px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .kpi-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.1);
            background: rgba(30, 41, 59, 0.85);
            border-color: rgba(59, 130, 246, 0.5);
        }
        .kpi-label {
            color: #94a3b8;
            font-size: 0.875rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.025em;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .kpi-value {
            color: #f8fafc;
            font-size: 2rem;
            font-weight: 800;
            line-height: 1;
        }
        
        /* Alert Panel Styling */
        .enterprise-alert {
            background: rgba(239, 68, 68, 0.1);
            border-left: 4px solid #ef4444;
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        
        /* Quick Action Buttons */
        .stButton button {
            border-radius: 10px !important;
            font-weight: 600 !important;
            transition: all 0.2s !important;
        }
        .stButton button:hover {
            transform: scale(1.02);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        }
        
        /* glass card for containers */
        .glass-panel {
            background: rgba(15, 23, 42, 0.6);
            backdrop-filter: blur(10px);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid rgba(255, 255, 255, 0.05);
            height: 100%;
        }
        </style>
    """, unsafe_allow_html=True)

    # Main Header with Status Indicators
    hcol1, hcol2 = st.columns([3, 1])
    with hcol1:
        st.title("🚦SmartRoad AI Monitoring Center")
        st.markdown(f"**District:** {st.session_state.user['department']} | **Auth Node:** {st.session_state.user['id']:04d}")
    with hcol2:
        st.markdown("<br>", unsafe_allow_html=True)
        st.success("\u25cf SYSTEM OPERATIONAL")

    # Quick Action Matrix
    st.markdown("#### \u26a1 Central Operations")
    qcol1, qcol2, qcol3, qcol4, qcol5 = st.columns(5)
    if qcol1.button("🖼️ Image Upload", use_container_width=True): st.session_state.nav = "Upload Image"; st.rerun()
    if qcol2.button("🎥 Video Analysis", use_container_width=True): st.session_state.nav = "Upload Video"; st.rerun()
    if qcol3.button("📡 Live Stream", use_container_width=True): st.session_state.nav = "Live Camera Detection"; st.rerun()
    if qcol4.button("🛰️ GIS Network", use_container_width=True): st.session_state.nav = "GPS & Location Tracking"; st.rerun()
    if qcol5.button("📄 Reports", use_container_width=True): st.session_state.nav = "Report Generation"; st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # KPI Statistics Row
    kcol1, kcol2, kcol3, kcol4, kcol5 = st.columns(5)
    
    def render_kpi(col, label, value, icon, trend=None):
        col.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">{icon} {label}</div>
                <div class="kpi-value">{value}</div>
            </div>s
        """, unsafe_allow_html=True)

    render_kpi(kcol1, "TOTAL INSPECTIONS", metrics["total_inspections"], "📊")
    render_kpi(kcol2, "POTHOLES DETECTED", metrics["total_potholes"], "🕳️")
    render_kpi(kcol3, "CRACKS DETECTED", metrics["total_cracks"], "📈")
    render_kpi(kcol4, "CRITICAL EVENTS", metrics["critical_damages"], "⚠️")
    render_kpi(kcol5, "RESOLVED CASES", "0", "✅")

    st.markdown("<br>", unsafe_allow_html=True)

    # GIS Map & Alerts Section
    mcol1, mcol2 = st.columns([2, 1])

    with mcol1:
        st.markdown("### 🗺️ Interactive GIS Damage Network")
        if records:
            map_data = []
            for row in records:
                try:
                    if row[17] and row[18]:
                        map_data.append({
                            "lat": float(row[17]),
                            "lon": float(row[18]),
                            "road": row[9] or "Unknown Segment",
                            "severity": row[12],
                            "date": row[8][:10]
                        })
                except: continue
            
            if map_data:
                m_df = pd.DataFrame(map_data)
                m = folium.Map(location=[m_df["lat"].mean(), m_df["lon"].mean()], 
                              zoom_start=14, tiles="cartodbpositron")
                for _, row in m_df.iterrows():
                    color = "#ef4444" if row["severity"] > 0 else "#3b82f6"
                    folium.CircleMarker(
                        location=[row["lat"], row["lon"]],
                        radius=7,
                        popup=f"Road: {row['road']}<br>Criticals: {row['severity']}",
                        color=color,
                        fill=True,
                        fill_color=color,
                        fill_opacity=0.6
                    ).add_to(m)
                st_folium(m, height=420, use_container_width=True)
            else:
                st.info("No geospatial telemetry available.")
        else:
            st.info("No inspection telemetry records.")

    with mcol2:
        st.markdown("🚨 Enterprise Alerts")
        if metrics["critical_damages"] > 0:
            st.markdown(f"""
                <div class="enterprise-alert">
                    <div style="font-weight:700; color:#ef4444; margin-bottom:4px;"> HIGH PRIORITY ALERT</div>
                    <div style="font-size:0.875rem; color:#f8fafc;">
                        {metrics['critical_damages']} critical structural failures identified. 
                        Dispatch repair protocols for high-risk zones immediately.
                    </div>
                </div>
            """, unsafe_allow_html=True)
        else:
            st.success("\u2705 Network structural integrity verified. No critical failures.")
            
        st.markdown("📋 Recent Activity Log")
        if recent_events:
            for e in recent_events[:4]:
                st.markdown(f"""
                    <div style="font-size:0.8rem; padding:8px 0; border-bottom:1px solid rgba(255,255,255,0.05);">
                        <span style="color:#94a3b8;">{e[2][11:16]}</span> | 
                        <span style="color:#38bdf8; font-weight:600;">{e[3]}</span> 
                        detected at {e[13] or 'Segment ' + str(e[0])}
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.caption("No recent activity data available.")

    st.markdown("<br>", unsafe_allow_html=True)

    # Analytics Dashboard Section
    st.markdown("📊 Strategic Analytics Dashboard")
    ccol1, ccol2, ccol3 = st.columns(3)

    if records:
        chart_df = pd.DataFrame([
            {
                "date": row[8][:10],
                "potholes": row[10],
                "cracks": row[11],
                "score": row[16]
            }
            for row in records
        ])
        chart_df["date"] = pd.to_datetime(chart_df["date"])
        daily_stats = chart_df.groupby("date").sum().reset_index()

        with ccol1:
            fig_pie = px.pie(values=[metrics["total_potholes"], metrics["total_cracks"]], 
                             names=["Potholes", "Cracks"],
                             hole=0.5, color_discrete_sequence=['#3b82f6', '#818cf8'])
            fig_pie.update_layout(title="Damage Classification", template="plotly_dark",
                                 margin=dict(t=40, b=0, l=0, r=0), height=300, showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)

        with ccol2:
            fig_bar = px.bar(daily_stats, x="date", y=["potholes", "cracks"], barmode="group",
                             color_discrete_sequence=['#3b82f6', '#10b981'])
            fig_bar.update_layout(title="Damage Volume Tracking", template="plotly_dark",
                                 margin=dict(t=40, b=0, l=0, r=0), height=300, 
                                 xaxis_title=None, yaxis_title=None)
            st.plotly_chart(fig_bar, use_container_width=True)

        with ccol3:
            fig_trend = px.line(daily_stats, x="date", y="score")
            fig_trend.update_traces(line_color='#10b981', line_width=3)
            fig_trend.update_layout(title="Network Health Score (%)", template="plotly_dark",
                                   margin=dict(t=40, b=0, l=0, r=0), height=300,
                                   xaxis_title=None, yaxis_title=None)
            st.plotly_chart(fig_trend, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Detailed Event Feed
    st.markdown("🎯 Recent High-Fidelity Detections")
    if recent_events:
        for e in recent_events:
            with st.container():
                ecol1, ecol2, ecol3, ecol4, ecol5 = st.columns([1, 2, 1, 1, 1.5])
                if e[14] and os.path.exists(e[14]):
                    ecol1.image(e[14], width=100)
                else:
                    ecol1.markdown("<div style='width:100px; height:60px; background:#1e293b; border-radius:8px; display:flex; align-items:center; justify-content:center; color:#475569;'></div>", unsafe_allow_html=True)
                
                ecol2.markdown(f"**{e[3]}**<br><span style='color:#64748b; font-size:0.8rem;'>{e[13] or 'Main Road Network'}</span>", unsafe_allow_html=True)
                ecol3.markdown(f"<span style='color:#38bdf8; font-weight:700;'>{e[4]*100:.1f}%</span><br><span style='color:#64748b; font-size:0.7rem;'>CONFIDENCE</span>", unsafe_allow_html=True)
                
                sev = "Critical" if e[4] > 0.8 else "High" if e[4] > 0.6 else "Normal"
                sev_color = "#ef4444" if sev == "Critical" else "#f59e0b" if sev == "High" else "#10b981"
                ecol4.markdown(f"<span style='color:{sev_color}; font-weight:700;'>{sev}</span><br><span style='color:#64748b; font-size:0.7rem;'>SEVERITY</span>", unsafe_allow_html=True)
                
                ecol5.markdown(f"<span style='color:#cbd5e1; font-size:0.85rem;'>{e[2][:16]}</span>", unsafe_allow_html=True)
                st.markdown("<div style='height:1px; background:rgba(255,255,255,0.05); margin:10px 0;'></div>", unsafe_allow_html=True)
    else:
        st.info("No recent detection events processed.")


def render_detection_results(image_path, detections, location):
    image = cv2.imread(str(image_path))
    if image is None:
        st.error("Could not load the image for display.")
        return

    if not detections:
        st.warning("No road damage detections were found in this image.")
        st.image(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), caption="Uploaded image", use_column_width=True)
        return

    # Use the enhanced drawing logic from detector
    image = detector.draw_detections(image, detections)
    st.image(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), caption="Detected damages", use_column_width=True)

    # --- Professional Detection Summary Cards ---
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.markdown("### 🔍 Detection Results")

    # Severity color map
    severity_colors = {"Critical": "#dc2626", "High": "#ea580c", "Medium": "#d97706", "Low": "#16a34a"}

    cols_per_row = 2
    items = list(enumerate(detections))
    for row_start in range(0, len(items), cols_per_row):
        row_items = items[row_start: row_start + cols_per_row]
        cols = st.columns(len(row_items))
        for col, (idx, item) in zip(cols, row_items):
            sev = item["severity"]
            badge_color = severity_colors.get(sev, "#6b7280")
            conf_pct = f"{item['confidence'] * 100:.1f}%"
            with col:
                st.markdown(
                    f"""
                    <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px 20px;margin-bottom:12px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                            <span style="color:#94a3b8;font-size:12px;font-weight:600;letter-spacing:0.05em;">DETECTION #{idx+1}</span>
                            <span style="background:{badge_color};color:#fff;font-size:11px;font-weight:700;padding:2px 10px;border-radius:20px;">{sev}</span>
                        </div>
                        <div style="margin-bottom:8px;">
                            <span style="color:#64748b;font-size:12px;">Damage Type</span><br>
                            <span style="color:#f1f5f9;font-size:16px;font-weight:700;">{item['label']}</span>
                        </div>
                        <div style="display:flex;gap:24px;margin-bottom:8px;">
                            <div>
                                <span style="color:#64748b;font-size:12px;">Confidence</span><br>
                                <span style="color:#38bdf8;font-size:18px;font-weight:800;">{conf_pct}</span>
                            </div>
                        </div>
                        <div style="margin-bottom:8px;">
                            <span style="color:#64748b;font-size:12px;">Date & Time</span><br>
                            <span style="color:#cbd5e1;font-size:13px;">{item.get('timestamp', now_str)}</span>
                        </div>
                        <div style="margin-top:10px;padding-top:10px;border-top:1px solid #334155;">
                            <span style="color:#4ade80;font-size:13px;font-weight:600;">✔ Detected Successfully</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    if location:
        st.map(pd.DataFrame([location], columns=["latitude", "longitude"]))


def render_enterprise_alert(detections):
    """Render a high-priority enterprise-style alert card for critical/high severity detections."""
    critical = [d for d in detections if d.get("severity") == "Critical"]
    high = [d for d in detections if d.get("severity") == "High"]
    flagged = critical or high
    if not flagged:
        return

    level_label = "CRITICAL ALERT" if critical else "HIGH SEVERITY ALERT"
    border_color = "#ef4444" if critical else "#f59e0b"
    bg_color = "rgba(239,68,68,0.12)" if critical else "rgba(245,158,11,0.12)"
    icon = "🚨" if critical else "⚠️"

    items_html = "".join([
        f"<div style='margin:6px 0; padding:8px 12px; background:rgba(0,0,0,0.25); border-radius:8px;'>"
        f"<span style='color:#f8fafc; font-weight:700;'>{d['label']}</span>"
        f"<span style='color:#94a3b8; font-size:0.85rem; margin-left:8px;'>Confidence: {d['confidence']*100:.1f}%</span>"
        f"<span style='background:{border_color}; color:#fff; font-size:0.75rem; font-weight:700; padding:2px 8px; border-radius:12px; margin-left:8px;'>{d['severity']}</span>"
        f"</div>"
        for d in flagged
    ])

    st.markdown(f"""
        <div style="background:{bg_color}; border:2px solid {border_color}; border-radius:14px;
                    padding:1.25rem 1.5rem; margin:1rem 0; box-shadow:0 4px 24px rgba(239,68,68,0.25);">
            <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px;">
                <span style="font-size:1.5rem;">{icon}</span>
                <div>
                    <div style="color:{border_color}; font-size:1rem; font-weight:800; letter-spacing:0.05em;">{level_label}</div>
                    <div style="color:#94a3b8; font-size:0.8rem;">Immediate dispatch and repair action required</div>
                </div>
                <span style="margin-left:auto; color:{border_color}; font-size:0.8rem; font-weight:600;">{datetime.datetime.now().strftime('%H:%M:%S')}</span>
            </div>
            {items_html}
        </div>
    """, unsafe_allow_html=True)

    # Play alert sound for critical/high damage
    sound_html = """
    <script>
    (function() {
        try {
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            var freqs = [880, 1100, 880];
            var t = ctx.currentTime;
            freqs.forEach(function(freq, i) {
                var osc = ctx.createOscillator();
                var gain = ctx.createGain();
                osc.connect(gain); gain.connect(ctx.destination);
                osc.frequency.value = freq; osc.type = 'square';
                gain.gain.setValueAtTime(0.2, t + i * 0.2);
                gain.gain.exponentialRampToValueAtTime(0.001, t + i * 0.2 + 0.18);
                osc.start(t + i * 0.2); osc.stop(t + i * 0.2 + 0.18);
            });
        } catch(e) { console.warn('Sound unavailable:', e); }
    })();
    </script>
    """
    components.html(sound_html, height=0)


def image_detection_page():
    st.header("🖼️ Upload Image")
    st.write("Upload road inspection images for real-time damage detection.")

    uploaded_image = st.file_uploader("Choose an image file", type=["jpg", "jpeg", "png"], key="image_upload")

    # Initialize location fields from session state defaults
    country = st.session_state.get("loc_country", "")
    state = st.session_state.get("loc_state", "")
    district = st.session_state.get("loc_district", "")
    city = st.session_state.get("loc_city", "")
    area = st.session_state.get("loc_area", "")
    road_name = st.session_state.get("loc_road", "")
    latitude = st.session_state.get("loc_lat", "")
    longitude = st.session_state.get("loc_lon", "")

    st.markdown("""
        <div style="background:rgba(30,41,59,0.6);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.08);
                    border-radius:14px;padding:1.5rem 1.8rem;margin-bottom:1.2rem;">
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
                <span style="font-size:1.6rem;">📍</span>
                <span style="color:#f1f5f9;font-size:1.25rem;font-weight:700;">Location Details</span>
                <span style="margin-left:auto;font-size:0.8rem;color:#64748b;background:rgba(100,116,139,0.15);
                      padding:4px 12px;border-radius:20px;">Geospatial Reference</span>
            </div>
    """, unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.9rem;color:#94a3b8;margin-bottom:10px;">Capture precise inspection coordinates for asset mapping and GIS integration.</div>', unsafe_allow_html=True)
    components.html(
        """
        <div style="margin:10px 0 16px 0;">
        <button onclick="getLocation()" style="padding:10px 20px;font-size:14px;cursor:pointer;
          background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;border:none;
          border-radius:10px;font-weight:600;box-shadow:0 4px 14px rgba(37,99,235,0.3);
          transition:all 0.2s;">
          📡 Auto-Detect My Location
        </button>
        </div>
        <script>
        function getLocation() {
            if (!navigator.geolocation) { alert('Geolocation not supported.'); return; }
            navigator.geolocation.getCurrentPosition(function(pos) {
                var url = new URL(window.location.href);
                url.searchParams.set('geo_lat', pos.coords.latitude);
                url.searchParams.set('geo_lon', pos.coords.longitude);
                window.location.href = url.toString();
            }, function(err) { alert('Location error: ' + err.message); },
            {enableHighAccuracy: true, timeout: 10000});
        }
        </script>
        """,
        height=80,
    )
    c1, c2 = st.columns(2)
    with c1:
        country = st.text_input("🌍 Country", value=country, key="loc_country", placeholder="e.g. India")
        district = st.text_input("🏛️ District", value=district, key="loc_district", placeholder="e.g. Chennai District")
        area = st.text_input("🏘️ Area / Suburb", value=area, key="loc_area", placeholder="e.g. T Nagar")
        latitude = st.text_input("🌐 Latitude", value=latitude, key="loc_lat", placeholder="e.g. 13.0827")
    with c2:
        state = st.text_input("🗺️ State", value=state, key="loc_state", placeholder="e.g. Tamil Nadu")
        city = st.text_input("🏙️ City", value=city, key="loc_city", placeholder="e.g. Chennai")
        road_name = st.text_input("🛣️ Road Name", value=road_name, key="loc_road", placeholder="e.g. Mount Road")
        longitude = st.text_input("🌐 Longitude", value=longitude, key="loc_lon", placeholder="e.g. 80.2707")
    st.markdown('</div>', unsafe_allow_html=True)

    # Show map preview if coordinates available
    if latitude and longitude:
        try:
            st.map(pd.DataFrame([{"latitude": float(latitude), "longitude": float(longitude)}]))
        except Exception:
            st.info("Unable to plot the provided GPS coordinates.")

    if uploaded_image:
        image_path = Path("uploads") / f"image_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_image.name}"
        with open(image_path, "wb") as f:
            f.write(uploaded_image.getbuffer())

        if detector.is_ready:
            with st.spinner("Analyzing image for road damage..."):
                detections = detector.detect_image(image_path)

            # --- Enterprise alert cards ---
            if detections:
                render_enterprise_alert(detections)

            # --- Streamlit + browser notifications ---
            try:
                alert_lat = float(latitude) if latitude else 0.0
                alert_lon = float(longitude) if longitude else 0.0
            except (ValueError, TypeError):
                alert_lat, alert_lon = 0.0, 0.0

            check_detections(
                detections,
                latitude=alert_lat,
                longitude=alert_lon,
                address=road_name or st.session_state.get("loc_road", ""),
                conf_threshold=0.5,
                enable_sound=True,
                enable_browser_notify=True,
            )

            location = None
            if latitude and longitude:
                try:
                    location = {"latitude": float(latitude), "longitude": float(longitude)}
                except ValueError:
                    location = None

            render_detection_results(image_path, detections, location)

            # --- GIS Map of detection location ---
            if location:
                st.markdown("#### 🗺️ Detection Location (GIS)")
                m = folium.Map(
                    location=[location["latitude"], location["longitude"]],
                    zoom_start=16, tiles="cartodbpositron"
                )
                for det in detections:
                    sev = det.get("severity", "Low")
                    pin_color = "red" if sev == "Critical" else "orange" if sev == "High" else "blue"
                    folium.Marker(
                        location=[location["latitude"], location["longitude"]],
                        popup=f"{det['label']} — {det['confidence']*100:.1f}% confidence",
                        icon=folium.Icon(color=pin_color, icon="exclamation-sign"),
                    ).add_to(m)
                st_folium(m, height=350, use_container_width=True)

            # --- AUTO-SAVE to database ---
            severity_counts = {"Low": 0, "Medium": 0, "High": 0, "Critical": 0}
            for item in detections:
                severity_counts[item.get("severity", "Low")] += 1
            total_potholes = sum(1 for item in detections if item["label"] == "Pothole")
            total_cracks = sum(1 for item in detections if "Crack" in item["label"])
            condition_score = db.estimate_condition_score(detections)
            avg_conf = round(sum(d["confidence"] for d in detections) / max(1, len(detections)), 3)

            db.add_detection_record(
                user_id=st.session_state.user["id"],
                filename=str(image_path),
                media_type="image",
                location_country=country,
                location_state=state,
                location_city=city,
                location_area=area,
                location_road_name=road_name,
                latitude=latitude,
                longitude=longitude,
                total_potholes=total_potholes,
                total_cracks=total_cracks,
                critical_damages=severity_counts["Critical"],
                average_confidence=avg_conf,
                condition_score=condition_score,
                detections_json=json.dumps(detections),
            )

            for det in detections:
                db.add_detection_event(
                    user_id=st.session_state.user["id"],
                    label=det["label"],
                    confidence=det["confidence"],
                    bbox=det["bbox"],
                    latitude=latitude,
                    longitude=longitude,
                    location_country=country,
                    location_state=state,
                    location_district=district,
                    location_city=city,
                    location_area=area,
                    location_road_name=road_name,
                    screenshot_path=str(image_path),
                    source="Image",
                    severity=det.get("severity", "Low"),
                )

            if detections:
                st.success(f"✅ {len(detections)} detection(s) automatically saved to history.")
                if severity_counts["Critical"] > 0:
                    st.error("⚠️ Critical road conditions detected. Immediate action recommended.")
            else:
                st.info("No damages detected. Record saved to history.")
        else:
            st.error("Detection model is unavailable. Configure a valid YOLOv8 weights file in Settings.")
            st.info("Use the Settings page to upload a YOLOv8 `.pt` weights file or set the correct model path.")


def video_detection_page():
    st.header("Upload Video")
    st.write("Upload road inspection video and process it frame-by-frame.")
    uploaded_video = st.file_uploader("Choose a video file", type=["mp4", "mov", "avi"], key="video_upload")
    if uploaded_video:
        video_path = Path("uploads") / f"video_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_video.name}"
        with open(video_path, "wb") as f:
            f.write(uploaded_video.getbuffer())

        if detector.is_ready:
            st.info("Processing video... this may take a few moments.")
            output_path = Path("uploads") / f"processed_{video_path.name}"
            video_summary = detector.process_video(video_path, output_path, progress_callback=st.progress(0))
            st.video(str(output_path))
            st.write("### Video Analytics")
            st.json(video_summary)
            st.success("Video processing complete.")
            
            # --- Trigger Alerts for Video Detection ---
            if video_summary["detections"]:
                # Trigger alerts for detections with > 50% confidence
                check_detections(
                    video_summary["detections"],
                    latitude=0.0,
                    longitude=0.0,
                    address="Video Inspection",
                    conf_threshold=0.5,
                    enable_sound=True,
                    enable_browser_notify=True
                )

            db.add_detection_record(
                user_id=st.session_state.user["id"],
                filename=str(video_path),
                media_type="video",
                location_country="",
                location_state="",
                location_city="",
                location_area="",
                location_road_name="",
                latitude="",
                longitude="",
                total_potholes=video_summary["total_potholes"],
                total_cracks=video_summary["total_cracks"],
                critical_damages=video_summary["critical_damages"],
                average_confidence=video_summary["average_confidence"],
                condition_score=video_summary["road_condition_score"],
                detections_json=json.dumps(video_summary["detections"]),
            )
            
            # Save granular detection events for video
            for det in video_summary["detections"]:
                db.add_detection_event(
                    user_id=st.session_state.user["id"],
                    label=det["label"],
                    confidence=det["confidence"],
                    bbox=det["bbox"],
                    latitude="",
                    longitude="",
                    screenshot_path=str(output_path),
                    source="Video"
                )
        else:
            st.error("Detection model is unavailable. Configure a valid YOLOv8 weights file in Settings.")
            st.info("Use the Settings page to upload a YOLOv8 `.pt` weights file or set the correct model path.")


class RoadDamageVideoProcessor(VideoProcessorBase):
    def __init__(self):
        self._detector = detector
        self._frame_count = 0

    def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
        img = frame.to_ndarray(format="bgr24")
        detections = self._detector.detect_frame(img, resize_max=640)
        if detections:
                         img = self._detector.draw_detections(img, detections)

                         self._frame_count += 1

                         if self._frame_count % 30 == 0:
                                try:
                                     st.session_state["live_new_detections"] = detections
                                     st.session_state["damage_detected"] = True
                                     st.session_state["last_damage"] = detections[0]["label"]
                                     st.session_state["live_alert_time"] = datetime.datetime.now()
                                except Exception:
                                    pass
                                 # Store detections in session state for the main thread to process alerts
                                 # Only update every 30 frames to avoid overwhelming the UI thread
                                
                                    return av.VideoFrame.from_ndarray(img, format="bgr24")


def live_detection_page():
    if st.session_state.get("damage_detected", False):

     for i in range(5):
        st.error(
            f"🚨 ROAD DAMAGE DETECTED: {st.session_state.get('last_damage', 'Unknown')}"
        )

    st.toast(
        f"🚨 {st.session_state.get('last_damage', 'Damage')} detected!"
    )

    st.markdown("""
    <audio autoplay>
        <source src="https://www.soundjay.com/buttons/sounds/beep-07.mp3" type="audio/mpeg">
    </audio>
    """, unsafe_allow_html=True)

    st.session_state["damage_detected"] = False
    # ─── PREMIUM SaaS DASHBOARD CSS (High Contrast v2) ──────────────────
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
    
    /* ─── Page Background ─── */
    .live-dash-wrap {
        background: #F5F7FB;
        border-radius: 24px;
        padding: 24px;
        margin: -1rem -1.5rem;
    }
    
    /* ─── KPI Metric Cards ─── */
    .live-kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 16px;
        margin-bottom: 24px;
    }
    .live-kpi-card {
        background: #FFFFFF;
        border-radius: 18px;
        padding: 20px 22px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.08);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        border: 1px solid rgba(0,0,0,0.04);
        position: relative;
        overflow: hidden;
    }
    .live-kpi-card::after {
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 100%; height: 4px;
    }
    .live-kpi-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 20px 40px rgba(0,0,0,0.12);
    }
    .kpi-blue::after   { background: linear-gradient(90deg, #2563EB, #60A5FA); }
    .kpi-red::after    { background: linear-gradient(90deg, #EF4444, #F87171); }
    .kpi-amber::after  { background: linear-gradient(90deg, #F59E0B, #FBBF24); }
    .kpi-green::after  { background: linear-gradient(90deg, #22C55E, #4ADE80); }
    .kpi-purple::after { background: linear-gradient(90deg, #7C3AED, #A78BFA); }
    
    .live-kpi-icon { font-size: 1.8rem; margin-bottom: 8px; }
    .live-kpi-label { color: #6B7280; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }
    .live-kpi-value { color: #111827; font-size: 2rem; font-weight: 800; line-height: 1.2; }
    .live-kpi-sub { color: #9CA3AF; font-size: 0.7rem; margin-top: 2px; font-weight: 500; }
    
    /* ─── Dark Camera Container ─── */
    .camera-glass {
        background: linear-gradient(135deg, #0F172A, #1E293B);
        border-radius: 20px;
        border: 1px solid rgba(255,255,255,0.08);
        padding: 20px;
        transition: all 0.4s ease;
        position: relative;
    }
    .camera-glass.active {
        border-color: #3B82F6;
        box-shadow: 0 0 40px rgba(59,130,246,0.2), inset 0 0 40px rgba(59,130,246,0.05);
    }
    .camera-glass.active::before {
        content: '';
        position: absolute;
        inset: -1px;
        border-radius: 20px;
        background: linear-gradient(135deg, rgba(59,130,246,0.4), transparent, rgba(59,130,246,0.2));
        z-index: -1;
    }
    
    /* Recording indicator */
    .rec-dot {
        display: inline-block;
        width: 10px; height: 10px;
        background: #EF4444;
        border-radius: 50%;
        animation: pulse-rec 1.2s infinite;
        margin-right: 6px;
    }
    @keyframes pulse-rec {
        0% { box-shadow: 0 0 0 0 rgba(239,68,68,0.7); }
        70% { box-shadow: 0 0 0 10px rgba(239,68,68,0); }
        100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
    }
    
    /* Status badges */
    .live-badge {
        display: inline-flex; align-items: center; gap: 5px;
        padding: 4px 14px; border-radius: 20px;
        font-size: 0.7rem; font-weight: 600;
    }
    .badge-green { background: rgba(34,197,94,0.12); color: #22C55E; border: 1px solid rgba(34,197,94,0.3); }
    .badge-red   { background: rgba(239,68,68,0.12); color: #EF4444; border: 1px solid rgba(239,68,68,0.3); }
    .badge-blue  { background: rgba(37,99,235,0.12); color: #2563EB; border: 1px solid rgba(37,99,235,0.3); }
    .badge-amber { background: rgba(245,158,11,0.12); color: #F59E0B; border: 1px solid rgba(245,158,11,0.3); }
    .badge-fps   { background: rgba(34,197,94,0.15); color: #22C55E; border: 1px solid rgba(34,197,94,0.3); }
    .badge-res   { background: rgba(37,99,235,0.15); color: #2563EB; border: 1px solid rgba(37,99,235,0.3); }
    
    /* ─── Detection Feed ─── */
    .detect-feed {
        max-height: 400px;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: #E5E7EB transparent;
    }
    .detect-feed::-webkit-scrollbar { width: 4px; }
    .detect-feed::-webkit-scrollbar-track { background: transparent; }
    .detect-feed::-webkit-scrollbar-thumb { background: #E5E7EB; border-radius: 10px; }
    
    .detect-item {
        background: #FFFFFF;
        border-radius: 12px;
        padding: 12px 14px;
        margin-bottom: 8px;
        border: 1px solid #E5E7EB;
        transition: all 0.2s;
        animation: slideIn 0.3s ease-out;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }
    .detect-item:hover { border-color: #2563EB; box-shadow: 0 4px 12px rgba(37,99,235,0.1); }
    @keyframes slideIn {
        from { opacity: 0; transform: translateY(-8px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    /* Severity badges */
    .sev-critical { background: rgba(220,38,38,0.1); color: #DC2626; border: 1px solid rgba(220,38,38,0.25); }
    .sev-high     { background: rgba(234,88,12,0.1); color: #EA580C; border: 1px solid rgba(234,88,12,0.25); }
    .sev-medium   { background: rgba(202,138,4,0.1); color: #CA8A04; border: 1px solid rgba(202,138,4,0.25); }
    .sev-low      { background: rgba(37,99,235,0.1); color: #2563EB; border: 1px solid rgba(37,99,235,0.25); }
    
    /* ─── Premium Alert Banner ─── */
    .alert-banner {
        animation: alertSlide 0.4s ease-out;
        border-radius: 14px;
        padding: 14px 18px;
        margin-bottom: 14px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    @keyframes alertSlide {
        from { opacity: 0; transform: translateY(-20px) scale(0.95); }
        to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .alert-critical { background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.3); }
    .alert-high     { background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.3); }
    .alert-medium   { background: rgba(202,138,4,0.08); border: 1px solid rgba(202,138,4,0.3); }
    .alert-low      { background: rgba(37,99,235,0.08); border: 1px solid rgba(37,99,235,0.3); }
    
    /* ─── Control Bar ─── */
    .control-bar {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 16px 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.06);
        border: 1px solid rgba(0,0,0,0.04);
    }
    
    /* ─── Buttons ─── */
    .stButton > button {
        border-radius: 12px !important;
        font-weight: 700 !important;
        font-size: 0.85rem !important;
        padding: 10px 24px !important;
        transition: all 0.25s ease !important;
        border: none !important;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #2563EB, #1E40AF) !important;
        color: #FFFFFF !important;
    }
    .stButton > button[kind="primary"]:hover {
        filter: brightness(110%) !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 24px rgba(37,99,235,0.3) !important;
    }
    .stButton > button[kind="secondary"] {
        background: linear-gradient(135deg, #EF4444, #B91C1C) !important;
        color: #FFFFFF !important;
    }
    .stButton > button[kind="secondary"]:hover {
        filter: brightness(110%) !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 24px rgba(239,68,68,0.3) !important;
    }
    
    /* ─── GPS Card ─── */
    .gps-card {
        background: #FFFFFF;
        border-radius: 16px
        padding: 16px;
        box-shadow: 0 8px 24px rgba(37,99,235,0.2);
        transition: all 0.3s;
    }
    .gps-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 12px 32px rgba(37,99,235,0.3);
    }
    .gps-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0;
        border-bottom: 1px solid rgba(255,255,255,0.1);
    }
    .gps-row:last-child { border-bottom: none; }
    .gps-key { color: #374151 !important; font-size: 0.88rem; font-weight: 600; }
    .gps-val { color: #000000 !important; font-size: 0.95rem; font-weight: 700; }
    
    /* ─── Section Title ─── */
    .section-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 1rem;
        font-weight: 700;
        color: #111827;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid #E5E7EB;
    }
    
    /* ─── Config Row ─── */
    .config-row {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        align-items: center;
    }
    
    /* ─── Side Panel Card ─── */
    .side-panel-card {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 18px 20px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.06);
        border: 1px solid rgba(0,0,0,0.04);
    }
    
    /* ─── Alert Toggles Card ─── */
    .alert-toggles-card {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 18px 20px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.06);
        border: 1px solid rgba(0,0,0,0.04);
    }
    
    /* ─── Idle State ─── */
    .idle-container {
        background: #FFFFFF;
        border-radius: 20px;
        padding: 60px 20px;
        text-align: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.08);
        border: 1px solid rgba(0,0,0,0.04);
    }
    
    /* ─── Camera Status Banner ─── */
    .cam-status-active {
        background: rgba(34,197,94,0.08);
        border: 1px solid rgba(34,197,94,0.2);
        border-radius: 10px;
        padding: 8px 14px;
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 8px;
    }
    .cam-status-waiting {
        background: rgba(37,99,235,0.06);
        border: 1px solid rgba(37,99,235,0.15);
        border-radius: 10px;
        padding: 8px 14px;
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 8px;
    }
    
    /* ─── Mobile Responsive ─── */
    @media (max-width: 768px) {
        .live-kpi-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
        .live-kpi-card { padding: 14px; }
        .live-kpi-value { font-size: 1.4rem; }
        .config-row { flex-direction: column; }
        .gps-row { font-size: 0.75rem; }
    }
    @media (max-width: 480px) {
        .live-kpi-grid { grid-template-columns: 1fr 1fr; gap: 8px; }
        .live-kpi-card { padding: 12px; }
        .live-kpi-value { font-size: 1.2rem; }
    }
    </style>
    """, unsafe_allow_html=True)
    
    # ─── HEADER ─────────────────────────────────────────────────────────
    h1, h2 = st.columns([3, 1])
    with h1:
        st.markdown("<div style='display:flex;align-items:center;gap:10px;'><span style='font-size:2.2rem;'>📡</span><span style='font-size:1.6rem;font-weight:800;color:#111827;'>Live Inspection Center</span><span class='live-badge badge-blue'>BETA</span></div>", unsafe_allow_html=True)
        st.markdown("<p style='color:#6B7280;font-size:0.85rem;margin-top:-4px;'>Real-time road damage detection via browser camera • WebRTC powered</p>", unsafe_allow_html=True)
    with h2:
        gps_ok = bool(st.session_state.get("loc_lat"))
        badge_cls = "badge-green" if gps_ok else "badge-red"
        badge_txt = "📍 GPS Connected" if gps_ok else "📍 GPS Offline"
        st.markdown(f"<div style='text-align:right;padding-top:10px;'><span class='live-badge {badge_cls}'>{badge_txt}</span></div>", unsafe_allow_html=True)

    # ─── SESSION STATE INIT ────────────────────────────────────────────
    if "live_inspection_active" not in st.session_state:
        st.session_state.live_inspection_active = False
        st.session_state.live_camera_running = False
        st.session_state.live_stats = {
            "total_frames": 0, "total_potholes": 0, "total_cracks": 0,
            "critical_damages": 0, "snapshots": [], "last_detections": [],
            "all_detections": [], "total_detections": 0,
        }
        st.session_state.live_camera_status = "⏹️ Stopped"
        st.session_state.live_gps_status = "📍 Not Available"
        st.session_state.live_last_detection = "—"
        st.session_state.live_current_location = "—"
        st.session_state.live_detection_history = []
        st.session_state.live_gps_error = ""
        st.session_state.live_fake_detections = []

    # ─── AUTO GPS ───────────────────────────────────────────────────────
    if not st.session_state.get("loc_lat"):
        components.html(
            """<script>(function autoGPS(){
                if(!navigator.geolocation)return;
                navigator.geolocation.getCurrentPosition(function(pos){
                    var u=new URL(window.location.href);
                    if(!u.searchParams.has('geo_lat')){
                        u.searchParams.set('geo_lat',pos.coords.latitude);
                        u.searchParams.set('geo_lon',pos.coords.longitude);
                        window.location.href=u.toString();
                    }
                },function(e){console.warn('GPS:',e.message);},{enableHighAccuracy:true,timeout:8000});
            })();</script>""",
            height=0,
        )

    # ─── KPI METRICS ROW ────────────────────────────────────────────────
    stats = st.session_state.live_stats
    total_dets = stats["total_detections"]
    criticals = stats["critical_damages"]
    potholes  = stats["total_potholes"]
    cracks    = stats["total_cracks"]
    cam_status = st.session_state.live_camera_status

    st.markdown(f"""
    <div class='live-kpi-grid'>
        <div class='live-kpi-card kpi-blue'>
            <div class='live-kpi-icon'>📊</div>
            <div class='live-kpi-label'>Total Detections</div>
            <div class='live-kpi-value'>{total_dets}</div>
            <div class='live-kpi-sub'>lifetime session</div>
        </div>
        <div class='live-kpi-card kpi-red'>
            <div class='live-kpi-icon'>🚨</div>
            <div class='live-kpi-label'>Critical Damage</div>
            <div class='live-kpi-value'>{criticals}</div>
            <div class='live-kpi-sub'>{'IMMEDIATE ACTION' if criticals > 0 else 'all clear'}</div>
        </div>
        <div class='live-kpi-card kpi-amber'>
            <div class='live-kpi-icon'>🕳️</div>
            <div class='live-kpi-label'>Potholes</div>
            <div class='live-kpi-value'>{potholes}</div>
            <div class='live-kpi-sub'>detected</div>
        </div>
        <div class='live-kpi-card kpi-green'>
            <div class='live-kpi-icon'>📈</div>
            <div class='live-kpi-label'>Cracks</div>
            <div class='live-kpi-value'>{cracks}</div>
            <div class='live-kpi-sub'>detected</div>
        </div>
        <div class='live-kpi-card kpi-purple'>
            <div class='live-kpi-icon'>📷</div>
            <div class='live-kpi-label'>Camera</div>
            <div class='live-kpi-value' style='font-size:1rem;'>{cam_status}</div>
            <div class='live-kpi-sub' style='font-size:0.65rem;'>{'🔴 Recording' if st.session_state.live_inspection_active else '⚪ Idle'}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ─── GPS ERROR ──────────────────────────────────────────────────────
    try:
        params = st.get_query_params()
        gps_err = params.get("gps_error", [None])[0]
        if gps_err:
            from urllib.parse import unquote
            gps_err = unquote(gps_err)
            if "denied" in gps_err.lower() or "permission" in gps_err.lower():
                st.session_state.live_gps_error = "Location permission denied by user"
                st.session_state.live_gps_status = "📍 Permission Denied"
            else:
                st.session_state.live_gps_error = f"Unable to retrieve GPS location: {gps_err}"
                st.session_state.live_gps_status = "📍 Unavailable"
            st.set_query_params(**{k: v for k, v in params.items() if k != "gps_error"})
    except Exception:
        pass

    if st.session_state.live_gps_error:
        st.markdown(f"<div class='alert-banner alert-high'><span>⚠️</span><span style='font-size:0.85rem;color:#f8fafc;'>{st.session_state.live_gps_error}</span></div>", unsafe_allow_html=True)

    # ─── CONTROL BAR ────────────────────────────────────────────────────
    st.markdown("<div class='control-bar'>", unsafe_allow_html=True)
    cc1, cc2, cc3 = st.columns([2, 2, 1])
    with cc1:
        stream_url = st.text_input("🎥 RTSP / Camera URL", placeholder="Leave blank for local webcam", key="camera_url", label_visibility="collapsed")
    with cc2:
        fskip, cwidth = st.columns(2)
        with fskip:
            frame_skip = st.number_input("Frame Skip", min_value=1, max_value=10, value=3, step=1, label_visibility="collapsed", key="live_frame_skip")
        with cwidth:
            capture_width = st.number_input("Max Width", min_value=320, max_value=1280, value=640, step=64, label_visibility="collapsed", key="live_cap_width")
    with cc3:
        if not st.session_state.live_inspection_active:
            start_clicked = st.button("▶️ START", use_container_width=True, type="primary", key="start_live_btn")
        else:
            stop_clicked = st.button("⏹️ STOP", use_container_width=True, type="secondary", key="stop_live_btn")

    st.markdown("</div>", unsafe_allow_html=True)

    # ─── START LOGIC ────────────────────────────────────────────────────
    if st.session_state.get("start_live_btn", False) or 'start_live_trigger' not in st.session_state:
        pass
    if 'start_live_btn' in st.session_state and st.session_state.start_live_btn and not st.session_state.live_inspection_active:
        components.html(
            """<script>
            (function(){
                if(!navigator.geolocation)return;
                navigator.geolocation.getCurrentPosition(function(p){
                    var u=new URL(window.location.href);
                    u.searchParams.set('geo_lat',p.coords.latitude);
                    u.searchParams.set('geo_lon',p.coords.longitude);
                    window.location.href=u.toString();
                },function(e){
                    var u=new URL(window.location.href);
                    u.searchParams.set('gps_error',encodeURIComponent(e.message));
                    window.location.href=u.toString();
                },{enableHighAccuracy:true,timeout:10000});
            })();
            </script>""",
            height=0,
        )
        st.session_state.live_inspection_active = True
        st.session_state.live_camera_running = True
        st.session_state.live_stats = {
            "total_frames": 0, "total_potholes": 0, "total_cracks": 0,
            "critical_damages": 0, "snapshots": [], "last_detections": [],
            "all_detections": [], "total_detections": 0,
        }
        st.session_state.live_detection_history = []
        st.session_state.live_camera_status = "📷 Active"
        if st.session_state.get("loc_lat"):
            st.session_state.live_gps_status = "📍 Connected"
        else:
            st.session_state.live_gps_status = "📍 Searching..."
        reset_dedup()
        st.rerun()

    if 'stop_live_btn' in st.session_state and st.session_state.stop_live_btn and st.session_state.live_inspection_active:
        st.session_state.live_inspection_active = False
        st.session_state.live_camera_running = False
        st.session_state.live_camera_status = "⏹️ Stopped"
        st.rerun()

    # ─── Initialize notification system (request permission, warm AudioContext) ──
    init_notification_system()

    # ─── GPS connected flag ─────────────────────────────────────────────
    gps_connected = bool(st.session_state.get("loc_lat"))

    # ─── MAIN LAYOUT ────────────────────────────────────────────────────
    if st.session_state.live_inspection_active:
        main_col, side_col = st.columns([2, 1.2])

        with main_col:
            # ── Camera Container ──
            cam_active_class = "active" if st.session_state.live_camera_running else ""
            st.markdown(f"<div class='camera-glass {cam_active_class}'>", unsafe_allow_html=True)

            # Camera header bar
            rec_dot = "<span class='rec-dot'></span>" if st.session_state.live_camera_running else ""
            rec_txt = "<span style='color:#EF4444;font-weight:700;font-size:0.8rem;'>REC</span>" if st.session_state.live_camera_running else "<span style='color:#64748b;font-size:0.8rem;'>STOPPED</span>"
            st.markdown(f"""
            <div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;'>
                <div style='display:flex;align-items:center;gap:10px;'>
                    <span style='font-size:1.2rem;'>📷</span>
                    <span style='color:#FFFFFF;font-weight:700;font-size:0.95rem;'>Camera Feed</span>
                    {rec_dot}{rec_txt}
                </div>
                <div style='display:flex;gap:12px;align-items:center;'>
                    <span class='live-badge badge-fps'>🐇 30 FPS</span>
                    <span class='live-badge badge-res'>📐 {capture_width}x480</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # WebRTC Stream
            ctx = webrtc_streamer(
    key="road-camera",
    video_processor_factory=RoadDamageVideoProcessor,
    media_stream_constraints={
        "video": {
            "facingMode": {"ideal": "environment"}
        },
        "audio": False
    }
)

            if ctx.video_processor:
                st.markdown("<div class='cam-status-active'><span style='color:#22C55E;font-size:1.2rem;'>●</span><span style='color:#111827;font-size:0.85rem;font-weight:600;'>Camera feed active — road damage detection running in real-time</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div class='cam-status-waiting'><span style='color:#2563EB;font-size:1rem;'>ℹ️</span><span style='color:#6B7280;font-size:0.85rem;'>Click <strong>START</strong> on the WebRTC panel to begin streaming</span></div>", unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)

            # ── Alert Polling: Process detections from WebRTC processor ──
            if "live_new_detections" in st.session_state and st.session_state.live_new_detections:
                dets = st.session_state.live_new_detections
                print(f"[live] Processing {len(dets)} detections from WebRTC processor for alerts")
                try:
                    alert_lat = float(st.session_state.get("loc_lat", 0))
                    alert_lon = float(st.session_state.get("loc_lon", 0))
                except (ValueError, TypeError):
                    alert_lat, alert_lon = 0.0, 0.0
                loc_road = st.session_state.get("loc_road", "")
                check_detections(
                    dets,
                    latitude=alert_lat,
                    longitude=alert_lon,
                    address=loc_road,
                    conf_threshold=0.5,
                    enable_sound=st.session_state.get("live_enable_sound", True),
                    enable_browser_notify=st.session_state.get("live_enable_browser", True),
                )
                # Clear to avoid re-processing
                st.session_state.live_new_detections = None

            # ── Charts Row ──
            st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
            st.markdown("<div class='section-title'>📊 Live Analytics</div>", unsafe_allow_html=True)
            chart1, chart2, chart3 = st.columns(3)
            with chart1:
                pie_fig = go.Figure()
                pie_fig.add_trace(go.Pie(
                    labels=["Potholes", "Cracks", "Other"],
                    values=[max(1, potholes), max(1, cracks), max(1, total_dets - potholes - cracks)],
                    hole=0.6,
                    marker_colors=['#f59e0b', '#3b82f6', '#64748b'],
                    textinfo='label+percent',
                    textfont_color='white'
                ))
                pie_fig.update_layout(
                    title="Damage Distribution",
                    template="plotly_dark",
                    margin=dict(t=40, b=0, l=0, r=0),
                    height=200,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='white',
                    showlegend=False,
                )
                st.plotly_chart(pie_fig, use_container_width=True)

            with chart2:
                sev_counts = {"Critical": criticals, "High": max(0, total_dets - criticals - 2), "Medium": 1, "Low": max(0, total_dets - 3)}
                bar_fig = go.Figure()
                bar_fig.add_trace(go.Bar(
                    x=list(sev_counts.keys()),
                    y=list(sev_counts.values()),
                    marker_color=['#ef4444', '#f59e0b', '#eab308', '#3b82f6'],
                ))
                bar_fig.update_layout(
                    title="Severity Breakdown",
                    template="plotly_dark",
                    margin=dict(t=40, b=0, l=0, r=0),
                    height=200,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='white',
                    xaxis=dict(showgrid=False),
                    yaxis=dict(showgrid=False, visible=False),
                )
                st.plotly_chart(bar_fig, use_container_width=True)

            with chart3:
                trend_fig = go.Figure()
                trend_fig.add_trace(go.Scatter(
                    x=[1, 2, 3, 4, 5],
                    y=[total_dets, max(0, total_dets-1), max(0, total_dets+1), max(0, total_dets+2), total_dets],
                    mode='lines+markers',
                    line=dict(color='#10b981', width=2),
                    marker=dict(color='#10b981', size=6),
                    fill='tozeroy',
                    fillcolor='rgba(16,185,129,0.1)',
                ))
                trend_fig.update_layout(
                    title="Detection Trend",
                    template="plotly_dark",
                    margin=dict(t=40, b=0, l=0, r=0),
                    height=200,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='white',
                    xaxis=dict(showgrid=False, visible=False),
                    yaxis=dict(showgrid=False, visible=False),
                )
                st.plotly_chart(trend_fig, use_container_width=True)

        # ── SIDE PANEL ──
        with side_col:
            # GPS Card
            loc_country = st.session_state.get("loc_country", "")
            loc_state = st.session_state.get("loc_state", "")
            loc_city = st.session_state.get("loc_city", "")
            loc_road = st.session_state.get("loc_road", "")
            loc_lat = st.session_state.get("loc_lat", "")
            loc_lon = st.session_state.get("loc_lon", "")
            gps_last = st.session_state.get("gps_last_updated", "")[:19] if st.session_state.get("gps_last_updated") else "—"

            st.markdown("<div class='gps-card'>", unsafe_allow_html=True)
            st.markdown("<div class='section-title' style='margin-bottom:8px;border-bottom-color:rgba(139,92,246,0.2);'>📍 GPS Location</div>", unsafe_allow_html=True)
            st.markdown(f"""
                <div class='gps-row'><span class='gps-key'>🌐 Latitude</span><span class='gps-val'>{loc_lat or "—"}</span></div>
                <div class='gps-row'><span class='gps-key'>🌐 Longitude</span><span class='gps-val'>{loc_lon or "—"}</span></div>
                <div class='gps-row'><span class='gps-key'>🏙️ City</span><span class='gps-val'>{loc_city or "—"}</span></div>
                <div class='gps-row'><span class='gps-key'>🛣️ Road</span><span class='gps-val'>{loc_road or "—"}</span></div>
                <div class='gps-row'><span class='gps-key'>🌎 State</span><span class='gps-val'>{loc_state or "—"}</span></div>
                <div class='gps-row'><span class='gps-key'>⏱️ Updated</span><span class='gps-val'>{gps_last}</span></div>
            """, unsafe_allow_html=True)
            components.html(
                """<div style='margin-top:10px;'><button onclick="getGPS()" style="width:100%;padding:8px 0;font-size:12px;cursor:pointer;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;border:none;border-radius:8px;font-weight:600;">📡 Refresh GPS</button>
                <script>function getGPS(){if(!navigator.geolocation){alert('Geolocation not supported.');return;}
                navigator.geolocation.getCurrentPosition(function(p){var u=new URL(window.location.href);u.searchParams.set('geo_lat',p.coords.latitude);u.searchParams.set('geo_lon',p.coords.longitude);window.location.href=u.toString();},function(e){var u=new URL(window.location.href);u.searchParams.set('gps_error',encodeURIComponent(e.message));window.location.href=u.toString();},{enableHighAccuracy:true,timeout:10000});}</script></div>""",
                height=54,
            )
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

            # Detection Feed
            st.markdown("<div class='section-title'>🎯 Live Detection Feed</div>", unsafe_allow_html=True)
            hist = st.session_state.live_detection_history
            if hist:
                feed_html = "<div class='detect-feed'>"
                for d in reversed(hist[-20:]):
                    sev = d.get("severity", "Low").lower()
                    sev_cls = f"sev-{sev}" if sev in ("critical","high","medium","low") else "sev-low"
                    sev_icon = "🚨" if sev == "critical" else "⚠️" if sev in ("high","medium") else "🔵"
                    feed_html += f"""
                    <div class='detect-item'>
                        <div style='display:flex;justify-content:space-between;align-items:center;'>
                            <div style='display:flex;align-items:center;gap:6px;'>
                                <span style='font-weight:700;color:#f8fafc;font-size:0.85rem;'>{d.get('label','—')}</span>
                                <span class='live-badge {sev_cls}' style='font-size:0.65rem;padding:2px 8px;'>{sev_icon} {d.get('severity','—')}</span>
                            </div>
                            <span style='color:#94a3b8;font-size:0.7rem;'>{d.get('confidence','—')}</span>
                        </div>
                        <div style='display:flex;justify-content:space-between;margin-top:5px;'>
                            <span style='color:#64748b;font-size:0.7rem;'>📍 {d.get('road','—') or d.get('city','—') or 'Unknown'}</span>
                            <span style='color:#64748b;font-size:0.7rem;'>{d.get('time','—')}</span>
                        </div>
                    </div>
                    """
                feed_html += "</div>"
                st.markdown(feed_html, unsafe_allow_html=True)
            else:
                st.markdown("<div style='padding:20px;text-align:center;color:#64748b;font-size:0.85rem;'>No detections yet<br><span style='font-size:0.75rem;'>Start the camera to begin monitoring</span></div>", unsafe_allow_html=True)

            # Alert Toggles
            st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
            st.markdown("<div style='background:rgba(15,23,42,0.4);border-radius:14px;padding:14px 16px;border:1px solid rgba(255,255,255,0.05);'>", unsafe_allow_html=True)
            st.markdown("<div class='section-title' style='margin-bottom:8px;'>🔔 Alert Settings</div>", unsafe_allow_html=True)
            e1, e2, e3 = st.columns(3)
            with e1: enable_alerts = st.checkbox("🚨 Alerts", value=True, key="live_enable_alerts")
            with e2: enable_sound = st.checkbox("🔊 Sound", value=True, key="live_enable_sound")
            with e3: enable_browser = st.checkbox("🔔 Browser", value=True, key="live_enable_browser")
            st.markdown("</div>", unsafe_allow_html=True)

    else:
        # ── IDLE STATE ──
        idle_c1, idle_c2, idle_c3 = st.columns([1, 2, 1])
        with idle_c2:
            st.markdown("""
            <div style='text-align:center;padding:50px 20px;'>
                <div style='font-size:4rem;margin-bottom:16px;'>📷</div>
                <div style='font-size:1.3rem;font-weight:700;color:#f1f5f9;margin-bottom:8px;'>Camera Offline</div>
                <div style='color:#64748b;font-size:0.9rem;margin-bottom:24px;'>Press <strong>START</strong> above to begin live road inspection</div>
                <div style='display:flex;justify-content:center;gap:20px;flex-wrap:wrap;'>
                    <span class='live-badge badge-blue'>📐 640p</span>
                    <span class='live-badge badge-blue'>🐇 30 FPS</span>
                    <span class='live-badge badge-blue'>🎯 YOLOv8</span>
                    <span class='live-badge badge-blue'>🌐 WebRTC</span>
                </div>
            </div>
            """, unsafe_allow_html=True)


def gps_page():
    st.header("GPS & Location Tracking")
    st.write("Capture and manage precise location details for every inspection.")

    # Ensure session state keys exist
    for k in ("loc_lat", "loc_lon", "loc_country", "loc_state", "loc_district", "loc_city", "loc_area", "loc_road", "gps_last_updated"):
        if k not in st.session_state:
            st.session_state[k] = ""

    # Try to get location via streamlit_js_eval
    location = None
    lat = None
    lon = None
    
    try:
        location = get_geolocation()
    except Exception as e:
        st.warning(f"Could not access browser geolocation: {str(e)}")
        location = None

    # Safely extract coordinates
    if location and isinstance(location, dict):
        try:
            coords = location.get("coords")
            if coords and isinstance(coords, dict):
                lat = coords.get("latitude")
                lon = coords.get("longitude")
                if lat is not None and lon is not None:
                    # Successfully got coordinates, now reverse geocode
                    geo_info = reverse_geocode(lat, lon)
                    st.session_state["loc_lat"] = str(lat)
                    st.session_state["loc_lon"] = str(lon)
                    st.session_state["loc_country"] = geo_info.get("country", "")
                    st.session_state["loc_state"] = geo_info.get("state", "")
                    st.session_state["loc_district"] = geo_info.get("district", "")
                    st.session_state["loc_city"] = geo_info.get("city", "")
                    st.session_state["loc_area"] = geo_info.get("area", "")
                    st.session_state["loc_road"] = geo_info.get("road", "")
                    st.session_state["gps_last_updated"] = datetime.datetime.now().isoformat()
                    st.success("✓ Location detected and reverse-geocoded")
            else:
                st.warning("Coordinates not available in location response")
        except Exception as e:
            st.warning(f"Error processing location: {str(e)}")
    elif location is None:
        st.info("📍 Click 'Get Current Location' below to enable GPS, or enter coordinates manually")

    # Display map if coordinates are available
    if st.session_state.get("loc_lat") and st.session_state.get("loc_lon"):
        try:
            lat_display = float(st.session_state["loc_lat"])
            lon_display = float(st.session_state["loc_lon"])
            m = folium.Map(
                location=[lat_display, lon_display],
                zoom_start=16
            )
            folium.Marker(
                [lat_display, lon_display],
                popup="Current Location",
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(m)
            st_folium(m, width=700, height=400)
        except (ValueError, TypeError) as e:
            st.warning(f"Could not render map: {str(e)}")

    st.markdown("---")
    st.subheader("Browser Geolocation")
    st.markdown("Use the button below to request GPS from your browser. Requires location permission.")
    components.html(
        """
        <button onclick="getLocation()" style="padding: 10px 16px; font-size: 14px; cursor: pointer; margin-bottom: 10px; background-color: #1f77b4; color: white; border: none; border-radius: 4px;">📍 Get Current Location</button>
        <script>
        function getLocation() {
            if (!navigator.geolocation) {
                alert('Geolocation not supported by your browser.');
                return;
            }
            navigator.geolocation.getCurrentPosition(
                function(position) {
                    const lat = position.coords.latitude;
                    const lon = position.coords.longitude;
                    const url = new URL(window.location.href);
                    url.searchParams.set('geo_lat', lat);
                    url.searchParams.set('geo_lon', lon);
                    window.location.replace(url.toString());
                },
                function(error) {
                    let msg = error.message;
                    if (error.code === error.PERMISSION_DENIED)
                        msg = 'Location permission denied. Enable in browser settings.';
                    else if (error.code === error.POSITION_UNAVAILABLE)
                        msg = 'Location not available.';
                    else if (error.code === error.TIMEOUT)
                        msg = 'Location request timed out.';
                    alert('Location Error: ' + msg);
                },
                {enableHighAccuracy: true, timeout: 10000, maximumAge: 0}
            );
        }
        </script>
        """,
        height=80,
    )

    st.markdown("---")
    st.subheader("Location Details")
    with st.form("gps_form"):
        country = st.text_input("Country", value=st.session_state.get("loc_country", ""), key="loc_country_input")
        state = st.text_input("State", value=st.session_state.get("loc_state", ""), key="loc_state_input")
        district = st.text_input("District", value=st.session_state.get("loc_district", ""), key="loc_district_input")
        city = st.text_input("City", value=st.session_state.get("loc_city", ""), key="loc_city_input")
        area = st.text_input("Area", value=st.session_state.get("loc_area", ""), key="loc_area_input")
        road_name = st.text_input("Road Name", value=st.session_state.get("loc_road", ""), key="loc_road_input")
        latitude = st.text_input("Latitude", value=st.session_state.get("loc_lat", ""), key="loc_lat_input")
        longitude = st.text_input("Longitude", value=st.session_state.get("loc_lon", ""), key="loc_lon_input")
        save_location = st.form_submit_button("Save Location")

    if save_location:
        lat_val = str(latitude).strip()
        lon_val = str(longitude).strip()
        if not lat_val or not lon_val:
            st.error("Please provide both latitude and longitude.")
            return
        try:
            float(lat_val)
            float(lon_val)
        except Exception:
            st.error("Please provide valid numeric latitude and longitude.")
            return

        location_id = db.add_location(
            user_id=st.session_state.user["id"],
            country=country.strip(),
            state=state.strip(),
            district=district.strip(),
            city=city.strip(),
            area=area.strip(),
            road_name=road_name.strip(),
            latitude=lat_val,
            longitude=lon_val,
        )
        st.success(f"Location saved successfully (ID: {location_id}).")

        locations = db.get_locations(st.session_state.user["id"])

    # Display saved locations
    locations = db.get_locations(st.session_state.user["id"])
    if locations:
        st.markdown("### Saved Locations")
        cols = ["ID", "User ID", "Country", "State", "District", "City", "Area", "Road Name", "Latitude", "Longitude", "Added On"]
        df = pd.DataFrame(locations, columns=cols)
        st.dataframe(df)

        # Plot map if coordinates exist and are numeric
        map_df = df[["Latitude", "Longitude"]].dropna()
        map_df = map_df.apply(pd.to_numeric, errors="coerce").dropna()
        if not map_df.empty:
            try:
                st.map(map_df)
            except Exception:
                st.info("Unable to render map for saved locations.")


def history_page():
    st.header("📋 Detection History")
    st.write("Review all past image inspections with filtering and search.")

    # --- Load all image detection events ---
    events = db.get_detection_events(st.session_state.user["id"], limit=5000)
    event_cols = ["ID", "User ID", "Time", "Damage Type", "Confidence", "BBox",
                  "Lat", "Lon", "Country", "State", "District", "City", "Area", "Road", "Screenshot", "Source"]

    # Also load aggregate records for stats
    records = db.get_detection_history(st.session_state.user["id"])

    # --- Statistics Cards ---
    image_records = [r for r in records if r[3] == "image"] if records else []
    img_events = [e for e in events if e[15] == "Image"] if events else []

    total_images = len(image_records)
    total_potholes = sum(r[10] or 0 for r in image_records)
    total_cracks = sum(r[11] or 0 for r in image_records)
    avg_conf_val = 0.0
    if img_events:
        confs = [float(e[4]) for e in img_events if e[4] is not None]
        avg_conf_val = round(sum(confs) / len(confs) * 100, 1) if confs else 0.0

    st.markdown("### 📊 Statistics")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("🖼️ Total Images Processed", total_images)
    s2.metric("🕳️ Total Potholes Detected", total_potholes)
    s3.metric("🪨 Total Cracks Detected", total_cracks)
    s4.metric("🎯 Average Confidence", f"{avg_conf_val}%")

    st.markdown("---")

    if not img_events:
        st.info("No image detection history found. Upload an image to get started.")
        return

    event_df = pd.DataFrame(img_events, columns=event_cols)
    event_df["Confidence %"] = (event_df["Confidence"].astype(float) * 100).round(1)
    event_df["Image File"] = event_df["Screenshot"].apply(lambda p: os.path.basename(p) if p else "N/A")

    # --- Filters ---
    st.markdown("### 🔎 Filter & Search")
    f1, f2, f3 = st.columns(3)
    with f1:
        all_types = ["All"] + sorted(event_df["Damage Type"].dropna().unique().tolist())
        filter_type = st.selectbox("Filter by Damage Type", all_types, key="hist_filter_type")
    with f2:
        min_date = pd.to_datetime(event_df["Time"]).dt.date.min()
        max_date = pd.to_datetime(event_df["Time"]).dt.date.max()
        filter_date = st.date_input("Filter by Date", value=None, min_value=min_date, max_value=max_date, key="hist_filter_date")
    with f3:
        search_file = st.text_input("Search by Image Filename", placeholder="e.g. road_01.jpg", key="hist_search_file")

    filtered_df = event_df.copy()
    if filter_type != "All":
        filtered_df = filtered_df[filtered_df["Damage Type"] == filter_type]
    if filter_date:
        filtered_df = filtered_df[pd.to_datetime(filtered_df["Time"]).dt.date == filter_date]
    if search_file.strip():
        filtered_df = filtered_df[filtered_df["Image File"].str.contains(search_file.strip(), case=False, na=False)]

    st.markdown(f"### 🗂️ Detection Records ({len(filtered_df)} results)")

    # Build display table
    display_df = filtered_df[["ID", "Time", "Damage Type", "Confidence %", "Image File"]].rename(columns={
        "ID": "Detection ID",
        "Time": "Date & Time",
        "Damage Type": "Damage Type",
        "Confidence %": "Confidence (%)",
        "Image File": "Image Filename",
    })
    st.dataframe(display_df, use_container_width=True)

    # --- View Image for selected event ---
    if not filtered_df.empty:
        st.markdown("### 🖼️ View Detection Image")
        sel_id = st.selectbox("Select Detection ID to view image", filtered_df["ID"].tolist(), key="hist_sel_event")
        sel_row = filtered_df[filtered_df["ID"] == sel_id]
        if not sel_row.empty:
            sel = sel_row.iloc[0]
            shot_path = sel["Screenshot"]
            if shot_path and os.path.exists(shot_path):
                st.image(shot_path, caption=f"{sel['Damage Type']} — {sel['Confidence %']}% confidence at {sel['Time']}", use_column_width=True)
            else:
                st.info("Screenshot not available for this event.")

    # --- Aggregate inspection records (all types) still accessible below ---
    if records:
        with st.expander("📁 All Inspection Records (Images, Video, Live)"):
            history_data = []
            for record in records:
                history_data.append({
                    "ID": record[0],
                    "Date": record[8],
                    "Type": record[3],
                    "File": os.path.basename(record[2]),
                    "Potholes": record[10],
                    "Cracks": record[11],
                    "Critical": record[12],
                    "Condition Score": record[16],
                })
            df = pd.DataFrame(history_data)
            st.dataframe(df, use_container_width=True)

            selected = st.selectbox("Select record ID to inspect details", df["ID"].tolist(), key="hist_agg_select")
            record = db.get_detection_by_id(selected)
            if record:
                st.markdown("**Record Details**")
                location_display = f"{record[4] or 'N/A'}, {record[5] or 'N/A'}, {record[6] or 'N/A'}, {record[7] or 'N/A'}"
                st.write({
                    "File": record[2], "Type": record[3],
                    "Location": location_display, "Road Name": record[9],
                    "GPS": f"{record[17] or 'N/A'}, {record[18] or 'N/A'}",
                    "Added": record[8], "Potholes": record[10],
                    "Cracks": record[11], "Critical": record[12],
                    "Condition Score": record[16],
                })
                try:
                    st.map(pd.DataFrame([{"latitude": float(record[17]), "longitude": float(record[18])}]))
                except Exception:
                    pass


def analytics_page():
    st.header("Analytics Dashboard")
    metrics = db.get_dashboard_metrics(st.session_state.user["id"])
    st.write("Aggregate insights and trend analysis for road damage monitoring.")

    stat_cols = st.columns(4)
    stat_cols[0].metric("Road Condition Score", f"{metrics['road_condition_score']}%")
    stat_cols[1].metric("Images Processed", metrics["image_inspections"])
    stat_cols[2].metric("Videos Processed", metrics["video_inspections"])
    stat_cols[3].metric("Critical Events", metrics["critical_damages"])

    records = db.get_detection_history(st.session_state.user["id"])
    if records:
        df = pd.DataFrame([
            {
                "inspection_date": row[8],
                "potholes": row[10],
                "cracks": row[11],
                "critical": row[12],
                "score": row[16],
                "latitude": row[17],
                "longitude": row[18],
            }
            for row in records
        ])
        df["inspection_date"] = pd.to_datetime(df["inspection_date"])
        fig1 = px.line(df, x="inspection_date", y=["potholes", "cracks"], title="Damage Counts Over Time")
        fig2 = px.pie(df, names="critical", values="potholes", title="Critical Event Breakdown")
        st.plotly_chart(fig1, use_container_width=True)
        st.plotly_chart(fig2, use_container_width=True)

        if not df.empty:
            fig3 = px.histogram(df, x="score", nbins=5, title="Road Condition Score Distribution")
            st.plotly_chart(fig3, use_container_width=True)

        map_df = df[["latitude", "longitude"]].dropna()
        if not map_df.empty:
            map_df = map_df.apply(pd.to_numeric, errors="coerce").dropna()
            if not map_df.empty:
                st.markdown("### Inspection Locations")
                st.map(map_df)
    else:
        st.info("No analytics available until detection results are recorded.")


def report_generation_page():
    st.header("Report Generation")
    records = db.get_detection_history(st.session_state.user["id"])
    if not records:
        st.info("No detection records available to generate reports.")
        return

    record_options = {f"{row[0]} - {os.path.basename(row[2])} ({row[8]})": row[0] for row in records}
    selected_option = st.selectbox("Select inspection record", list(record_options.keys()))
    record_id = record_options[selected_option]
    record = db.get_detection_by_id(record_id)
    if record:
        detections = json.loads(record["detections_json"] or "[]")
        report_meta = {
            "user_name": st.session_state.user["full_name"],
            "inspection_date": record["created_at"],
            "location": {
                "country": record["location_country"],
                "state": record["location_state"],
                "city": record["location_city"],
                "area": record["location_area"],
                "road_name": record["location_road_name"],
                "latitude": record["latitude"],
                "longitude": record["longitude"],
            },
            "file_name": os.path.basename(record["filename"]),
            "full_path": record["filename"],
            "total_potholes": record["total_potholes"],
            "total_cracks": record["total_cracks"],
            "critical_damages": record["critical_damages"],
            "condition_score": record["condition_score"],
            "detections": detections,
        }
        pdf_path = Path("reports") / f"report_{record_id}.pdf"
        excel_path = Path("reports") / f"report_{record_id}.xlsx"
        if st.button("Generate PDF Report"):
            reporter.generate_pdf_report(report_meta, pdf_path)
            st.success("PDF report generated.")
            st.download_button("Download PDF", data=open(pdf_path, "rb"), file_name=pdf_path.name, mime="application/pdf")
        if st.button("Generate Excel Report"):
            reporter.generate_excel_report(report_meta, excel_path)
            st.success("Excel report generated.")
            st.download_button("Download Excel", data=open(excel_path, "rb"), file_name=excel_path.name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def profile_page():
    st.header("User Profile")
    user = st.session_state.user
    st.write(f"**Name:** {user['full_name']}")
    st.write(f"**Email:** {user['email']}")
    st.write(f"**Mobile:** {user['mobile']}")
    st.write(f"**Department:** {user['department']}")
    st.write("\n")
    st.write("Update your profile in Settings.")


def settings_page():
    st.header("Settings")
    st.write("Configure application settings and model details.")
    model_path = st.text_input("YOLOv8 model path", value=str(config.get("model_path", MODEL_PATH)), key="setting_model_path")
    if st.button("Save Settings"):
        config["model_path"] = model_path
        save_config(config)
        detector.model_path = Path(model_path)
        detector.load_model()
        if detector.is_ready:
            st.success("Settings saved and YOLO model loaded successfully.")
        else:
            st.warning("Settings saved, but model could not be loaded. Check the model path.")

    st.markdown("### Upload YOLOv8 Weights")
    st.write("If you do not have a local model file yet, upload it here and the app will save it to the `models/` directory.")
    uploaded_model = st.file_uploader("Upload YOLOv8 model (.pt)", type=["pt"], key="upload_model")
    if uploaded_model:
        target_path = Path("models") / uploaded_model.name
        with open(target_path, "wb") as f:
            f.write(uploaded_model.getbuffer())
        config["model_path"] = str(target_path)
        save_config(config)
        detector.model_path = target_path
        detector.load_model()
        if detector.is_ready:
            st.success(f"Model uploaded and loaded: {uploaded_model.name}")
        else:
            st.error(f"Model uploaded but could not be loaded. Check that this file is a valid YOLOv8 `.pt` weights file.")

    st.markdown("### Model Classes")
    st.write(", ".join(ROAD_DAMAGE_CLASSES))

    st.markdown("### Road Damage Model Setup")
    st.write(
        "If you don't yet have a road damage model, upload `models/best.pt` here or train a YOLOv8 model using a road damage dataset."
    )
    st.write("Recommended class labels: Pothole, Longitudinal Crack, Transverse Crack, Alligator Crack, Surface Damage, Road Deterioration.")
    st.markdown(
        "#### Training Guidance\n"
        "- Download the RDD dataset or a road damage dataset from GitHub/Kaggle.\n"
        "- Prepare a `data.yaml` file with class names and train/val paths.\n"
        "- Use YOLOv8 training: `yolo task=detect mode=train model=yolov8n.pt data=data.yaml epochs=100 imgsz=640`\n"
        "- After training, place the new weights in `models/` and update the model path above."
    )


def logout_page():
    st.session_state.authenticated = False
    st.session_state.user = None
    st.session_state.nav = "Home"
    st.success("You have been logged out.")


# Main application entrypoint
if not st.session_state.authenticated:
    login_form()
else:
    sidebar_navigation()
    page = st.session_state.nav
    if page == "Home":
        show_home()
    elif page == "Upload Image":
        image_detection_page()
    elif page == "Upload Video":
        video_detection_page()
    elif page == "Live Camera Detection":
        live_detection_page()
    elif page == "GPS & Location Tracking":
        gps_page()
    elif page == "Detection History":
        history_page()
    elif page == "Analytics Dashboard":
        analytics_page()
    elif page == "Report Generation":
        report_generation_page()
    elif page == "User Profile":
        profile_page()
    elif page == "Settings":
        settings_page()
    elif page == "Logout":
        logout_page()