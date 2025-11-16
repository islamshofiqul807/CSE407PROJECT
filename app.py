# app.py — fixed navigation, working buttons, and improved stability

from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import altair as alt
import plotly.express as px
import os
import numpy as np
from plotly.subplots import make_subplots
import plotly.graph_objects as go

# Local modules
from devices import load_devices, save_devices
from get_power_data import fetch_and_log_once
from tuya_api import control_device, get_token
from tuya_api_mongo import latest_docs, range_docs
from billing import daily_monthly_for, _latest_power_voltage
from helpers import go_home as _go_home
from billing import aggregate_timeseries_24h, aggregate_totals_all_devices


# ------------------------------------------------------------------------------------
# Page setup
st.set_page_config(page_title="Smart Plug Dashboard", layout="wide")
DATA_DIR = Path("data")

# Global CSS Theme
st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #E0E7FF, #F0F4FF);
        color: #222222;
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #4C1D95, #6D28D9);
        color: #FFFFFF;
    }
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p {
        color: #F3E8FF !important;
    }
    div[data-testid="stMetricValue"] {
        color: #3B82F6;
    }
    div[data-testid="stMetricLabel"] {
        color: #111827 !important;
    }
    div.stButton > button {
        background: linear-gradient(90deg, #3B82F6, #2563EB);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6em 1em;
        font-weight: 600;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    }
    div.stButton > button:hover {
        background: linear-gradient(90deg, #2563EB, #1D4ED8);
        transform: scale(1.05);
    }
    h1, h2, h3, h4, h5 { color: #1E1B4B; }
    .stAlert {
        background-color: rgba(59,130,246,0.1);
        border-left: 5px solid #3B82F6;
        color: #111827;
    }
    .stPlotlyChart {
        background: white !important;
        border-radius: 10px;
        padding: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    [data-testid="stMetric"] {
        background: white;
        border-radius: 12px;
        padding: 15px;
        box-shadow: 0 1px 8px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------------------------
# Session defaults
if "route" not in st.session_state:
    st.session_state.route = "home"
if "current_device_id" not in st.session_state:
    st.session_state.current_device_id = None
if "current_device_name" not in st.session_state:
    st.session_state.current_device_name = None


# Small helpers
def set_route(new_route: str):
    st.session_state.route = new_route

def go_home(): set_route("home")
def go_mydevices(): set_route("mydevices")
def go_add(): set_route("add")
def go_manage(): set_route("manage")

def go_device_detail(device_id: str, device_name: str):
    st.session_state.current_device_id = device_id
    st.session_state.current_device_name = device_name
    set_route("device")

def get_device_by_id(device_id: str):
    for d in (load_devices() or []):
        if d.get("id") == device_id:
            return d
    return None


# ------------------------------------------------------------------------------------
# Pages

def page_home():
    st.title("📊 Smart Enegry Monitoring System Dashboard")
    st.caption("At-a-glance overview of your smart energy setup.")

    devices = load_devices() or []
    try:
        total_power_now, present_voltage, today_kwh, today_bill_bdt, month_kwh, month_bill_bdt = \
            aggregate_totals_all_devices(devices)
    except Exception as e:
        st.error(f"Aggregation error: {e}")
        total_power_now = present_voltage = today_kwh = today_bill_bdt = month_kwh = month_bill_bdt = 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Devices", len(devices))
    c2.metric("Total Power (now)", f"{total_power_now:.1f} W")
    c3.metric("Present Voltage (max)", f"{present_voltage:.1f} V")
    c4.metric("Today’s Bill (BDT)", f"{today_bill_bdt:.2f}")
    c5.metric("Monthly Bill (BDT)", f"{month_bill_bdt:.2f}")

    st.markdown("---")
    st.subheader("Device Management")
    a1, a2, a3, a4 = st.columns(4)
    if a1.button("📂 My Devices"): go_mydevices(); st.rerun()
    if a2.button("➕ Add Device"): go_add(); st.rerun()
    if a3.button("⚙️ Manage Devices"): go_manage(); st.rerun()
    if a4.button("📘 User Manual"):
        set_route("manual")
        st.rerun()

    st.markdown("---")
    st.subheader("Last 24h — Power & Voltage (All Devices)")

    ts = pd.DataFrame()
    try:
        ts = aggregate_timeseries_24h(devices, resample_rule="5T")
    except Exception as e:
        st.error(f"Timeseries aggregation failed: {e}")

    if ts.empty:
        st.info("No data available for the last 24 hours.")
        st.stop()

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # --- Color palette for your UI theme ---
    power_color = "#6C63FF"      # soft indigo (matches sidebar accent)
    voltage_color = "#00A8E8"    # cyan-blue accent
    background_color = "#EEF2FF" # light bluish background to match dashboard

    # Add traces with matching colors
    fig.add_trace(
        go.Scatter(
            x=ts["timestamp"],
            y=ts["power_sum_W"],
            mode="lines",
            name="Power (W)",
            line=dict(color=power_color, width=2.5),
            fill="tozeroy",
            fillcolor="rgba(108, 99, 255, 0.1)"  # soft purple fill
        ),
        secondary_y=False
    )

    fig.add_trace(
        go.Scatter(
            x=ts["timestamp"],
            y=ts["voltage_avg_V"],
            mode="lines",
            name="Voltage (V)",
            line=dict(color=voltage_color, width=2, dash="dot")
        ),
        secondary_y=True
    )

    # Y axes
    fig.update_yaxes(
        title_text="Power (W)",
        secondary_y=False,
        rangemode="tozero",
        showgrid=True,
        gridcolor="rgba(0,0,0,0.05)"
    )
    fig.update_yaxes(
        title_text="Voltage (V)",
        secondary_y=True,
        showgrid=False
    )

    # X axis
    fig.update_xaxes(
        title_text="Time",
        showgrid=True,
        gridcolor="rgba(0,0,0,0.05)",
        rangeslider=dict(visible=True),
        rangeselector=dict(
            buttons=list([
                dict(count=6, step="hour", stepmode="backward", label="6h"),
                dict(count=12, step="hour", stepmode="backward", label="12h"),
                dict(count=1, step="day", stepmode="backward", label="1d"),
                dict(step="all", label="All")
            ])
        )
    )

    # Layout update — matches light dashboard theme
    fig.update_layout(
        title=dict(
            text="⚡ Total Power (sum) & Voltage (avg) — Last 24 Hours",
            x=0.5,
            xanchor="center",
            font=dict(size=20, color="#333", family="Arial Black")
        ),
        hovermode="x unified",
        template="plotly_white",
        plot_bgcolor=background_color,
        paper_bgcolor=background_color,
        font=dict(color="#333"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(255,255,255,0)",
            bordercolor="rgba(0,0,0,0)"
        ),
        margin=dict(l=60, r=40, t=80, b=50)
    )

    # Clean hover format
    fig.update_traces(hovertemplate="%{y:.2f}<extra></extra>")

    # Render in Streamlit
    st.plotly_chart(fig, use_container_width=True)


def page_mydevices():
    st.title("⚡ My Devices")
    st.caption("Browse and open a device to view live data.")

    devices = load_devices() or []
    if not devices:
        st.info("No devices added yet. Click **Add Device** to get started.")
        if st.button("➕ Add Device"):
            go_add(); st.rerun()
        return

    cols = st.columns(3)
    for i, d in enumerate(devices):
        with cols[i % 3]:
            st.markdown(f"#### 🔌 {d['name']}")
            st.markdown(f"**Device ID:** `{d['id']}`")
            if st.button(f"View Details ({d['name']})", key=f"view_{i}"):
                go_device_detail(d["id"], d["name"])
                st.rerun()
            st.markdown("---")


def page_add():
    st.header("➕ Add Device")
    name = st.text_input("Device Name")
    dev_id = st.text_input("Device ID")
    c1, c2 = st.columns([1,1])
    if c1.button("Save"):
        if name and dev_id:
            devs = load_devices() or []
            if any(d.get("id") == dev_id for d in devs):
                st.warning("Device ID already exists.")
            else:
                devs.append({"name": name, "id": dev_id})
                save_devices(devs)
                st.success("Device added.")
                go_home(); st.rerun()
        else:
            st.warning("Enter both name and ID.")
    if c2.button("Cancel"):
        go_home(); st.rerun()


def page_manage():
    st.header("⚙️ Manage Devices")
    devs = load_devices() or []
    if not devs:
        st.info("No devices to manage.")
        return

    for i, d in enumerate(devs):
        c1, c2, c3 = st.columns([3, 3, 2])
        new_name = c1.text_input("Name", value=d["name"], key=f"nm_{i}")
        new_id = c2.text_input("ID", value=d["id"], key=f"id_{i}")
        save_clicked = c3.button("Save", key=f"sv_{i}")
        del_clicked = c3.button("Delete", key=f"dl_{i}")
        open_clicked = c3.button("Open", key=f"open_{i}")

        if save_clicked:
            devs[i] = {"name": new_name, "id": new_id}
            save_devices(devs)
            st.success("Saved."); st.rerun()

        if del_clicked:
            devs.pop(i)
            save_devices(devs)
            st.warning("Deleted."); st.rerun()

        if open_clicked:
            go_device_detail(d["id"], d["name"])
            st.rerun()


def page_device():
    dev_id = st.session_state.get("current_device_id")
    dev_name = st.session_state.get("current_device_name")

    if not dev_id:
        st.error("No device selected.")
        if st.button("Back to Home"):
            go_home(); st.rerun()
        return

    if not dev_name:
        d = get_device_by_id(dev_id)
        dev_name = d["name"] if d else dev_id

    st_autorefresh(interval=30000, key=f"data_refresh_{dev_id}")  # 30 sec refresh
    st.title(f"🔌 {dev_name} — Live")

    result = fetch_and_log_once(dev_id, dev_name)
    if "error" in result:
        st.error(f"Tuya API error: {result['error']}")
        if st.button("⬅️ Back to Home"): go_home(); st.rerun()
        st.caption("You can also retry after checking connectivity.")
        return

    row = result.get("row", {})
    v = float(row.get("voltage", 0.0))
    c = float(row.get("current", 0.0))
    p = float(row.get("power", 0.0))
    # Simple status logic: if power > 1 W, assume ON
    is_on = p > 1.0
    status_text = "🟢 Device is ON" if is_on else "🔴 Device is OFF"

    m1, m2, m3 = st.columns(3)
    m1.metric("🔋 Voltage (V)", f"{v:.1f}")
    m2.metric("⚡ Power (W)", f"{p:.1f}")
    m3.metric("🔌 Current (A)", f"{c:.3f}")

    colA, colB, colC, colD = st.columns([1,1,1,2])

    with colA:
        if st.button("Turn ON"):
            try:
                token = get_token()
                st.info(control_device(dev_id, token, "switch_1", True))
            except Exception as e:
                st.error(e)

    with colB:
        if st.button("Turn OFF"):
            try:
                token = get_token()
                st.info(control_device(dev_id, token, "switch_1", False))
            except Exception as e:
                st.error(e)

    with colC:
        if st.button("Show Status"):
            st.info(status_text)

    with colD:
        if st.button("⬅️ Back to My Devises"):
            go_home()
            st.rerun()

    st.markdown("### 💰 Bill Estimate")
    d_units, d_cost, m_units, m_cost = daily_monthly_for(dev_id)
    b1, b2 = st.columns(2)
    b1.metric("📅 Today kWh", f"{d_units:.3f}")
    b1.metric("💸 Today BDT", f"{d_cost:.2f}")
    b2.metric("🗓 Month kWh", f"{m_units:.3f}")
    b2.metric("💰 Month BDT", f"{m_cost:.2f}")

    st.markdown("### 🕰️ Historical Data")
    c1, c2, c3 = st.columns(3)
    start_date = c1.date_input("Start", value=datetime.now().date() - timedelta(days=1))
    end_date = c2.date_input("End", value=datetime.now().date())
    agg = c3.selectbox("Aggregation", ["raw", "1-min", "5-min", "15-min"], index=1)

    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    df = range_docs(dev_id, start_dt, end_dt)

    if df is not None and not df.empty:
        df = df.sort_values("timestamp").set_index("timestamp")
        if agg != "raw":
            rule = {"1-min": "1T", "5-min": "5T", "15-min": "15T"}[agg]
            df = df.resample(rule).mean(numeric_only=True).dropna()

        plot_df = df.reset_index()
        fig = px.line(plot_df, x="timestamp", y="power", title=f"Power over time ({agg})", markers=(agg == "raw"))
        fig.update_layout(hovermode="x unified", xaxis_title="Time", yaxis_title="Power (W)", template="plotly_white")
        fig.update_yaxes(rangemode="tozero")
        fig.update_xaxes(
            rangeslider=dict(visible=True),
            rangeselector=dict(buttons=[
                dict(count=6, step="hour", stepmode="backward", label="6h"),
                dict(count=12, step="hour", stepmode="backward", label="12h"),
                dict(count=1, step="day", stepmode="backward", label="1d"),
                dict(step="all", label="All")
            ])
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(plot_df.tail(200))
    else:
        st.info("No data in selected range.")


# ------------------------------------------------------------------------------------
# FULL User Manual (Option C — exact manual text)
# def page_manual():
#     st.title("📘 User Manual — Smart Energy Monitoring System")
#     st.caption("Learn how to use your Smart Energy Dashboard efficiently.")

#     st.markdown("---")

#     st.header("🏠 Home Dashboard Overview")
#     st.markdown("""
#     - The **Home Dashboard** gives you a quick overview of your energy system.  
#     - It displays the **number of connected devices**, **total power**, **maximum voltage**, and **billing estimates**.  
#     - You can also view **interactive time-series graphs** of your devices’ power and voltage usage.  
#     - Use the range selector below the chart to view data for **6h, 12h, 1d**, or all available data.
#     """)

#     with st.expander("🔍 How to Read the Dashboard"):
#         st.markdown("""
#         - **Power (W):** Total instantaneous power consumption from all connected devices.  
#         - **Voltage (V):** Average voltage recorded across devices.  
#         - **Today's Bill:** Calculated based on today's energy consumption and your configured rate.  
#         - **Monthly Bill:** Estimated billing projection for the current month.  
#         - **Graph:** Use the chart zoom and range tools to analyze consumption trends over time.
#         """)

#     st.markdown("---")
#     st.header("⚙️ Manage Devices")
#     st.markdown("""
#     - Go to **Manage Devices** from the sidebar or the dashboard buttons.  
#     - From here, you can:
#     - 🟢 **Add a new device** by providing a name and ID.  
#     - ✏️ **Edit an existing device** (rename or update details).  
#     - ❌ **Delete a device** if it’s no longer active.  
#     - All device data is stored locally or in your configured backend (depending on setup).
#     """)

#     with st.expander("💡 Tips for Device Management"):
#         st.markdown("""
#         - Use short, descriptive names (e.g., “Living Room Fan” or “AC Unit”).  
#         - Avoid duplicate Device IDs — they must be **unique**.  
#         - If your devices don’t appear in the dashboard, check your **data logging frequency** or **connection status**.
#         """)

#     st.markdown("---")
#     st.header("📈 Power Consumption & Analytics")
#     st.markdown("""
#     - View historical **power and voltage data** over custom time ranges (1, 3, 7, or 30 days).  
#     - Graphs are interactive — hover to view values or click the legend to hide/show metrics.  
#     - Data is resampled automatically for smooth visualization (default: every 15 minutes).  
#     """)

#     with st.expander("⚡ Understanding the Graphs"):
#         st.markdown("""
#         - **Orange Area (Power):** Represents total power consumption (W).  
#         - **Blue Line (Voltage):** Represents average voltage (V).  
#         - Use zoom and pan tools at the bottom of the chart to inspect specific time intervals.  
#         - You can export data by adding a download button if enabled in your setup.
#         """)

#     st.markdown("---")
#     st.header("💰 Billing Information")
#     st.markdown("""
#     - The dashboard automatically estimates your **daily** and **monthly electricity cost**.  
#     - Billing is calculated using your system’s configured tariff rate per kilowatt-hour (kWh).  
#     - Actual cost may differ slightly based on your energy provider’s pricing model.  
#     """)

#     with st.expander("🧮 Billing Formula"):
#         st.markdown(r"""
#         \[
#         \text{Bill (BDT)} = \text{Energy (kWh)} \times \text{Tariff Rate (BDT/kWh)}
#         \]
#         """)

#     st.markdown("---")
#     st.header("🧭 Navigation Guide")
#     st.markdown("""
#     - Use the **sidebar menu** to move between pages:
#     - 🏠 **Home:** Dashboard overview  
#     - 🔌 **My Devices:** View live data for your registered devices  
#     - ➕ **Add Device:** Register new smart devices  
#     - ⚙️ **Manage Devices:** Edit or remove devices  
#     - 📘 **User Manual:** View this help guide  
#     """)

#     st.markdown("---")
#     st.header("🛠️ Troubleshooting")
#     with st.expander("❗ Common Issues & Fixes"):
#         st.markdown("""
#         - **No Data Displayed:** Check if the device is powered on and connected.  
#         - **Graph Not Updating:** Refresh the page or check logging interval.  
#         - **Billing Looks Wrong:** Verify tariff configuration in system settings.  
#         - **Device Not Found:** Re-add the device or check connection settings.
#         """)

#     st.markdown("---")
#     st.header("📞 Support & Credits")
#     st.markdown("""
#     For technical support or customization help, contact your system administrator or the project maintainer.  
#     **Developed by:** Smart Energy Monitoring Team  
#     **Version:** 1.0.0  
#     """)

#     st.success("✅ You’re now ready to explore your Smart Energy Monitoring Dashboard with confidence!")
def page_manual():
        st.title("📘 User Manual")

        st.write("Click the link below to open the User Manual:")
        st.caption("Learn how to use your Smart Energy Dashboard efficiently.")
        drive_link = "https://drive.google.com/file/d/1Kui0mipniXLR-G6k88k5xPthj5UK0Pku/view?usp=drive_link"
      
        st.markdown(
            f"""
            ### 👉 [Open User Manual (Google Drive)]({drive_link})  
            """,
            unsafe_allow_html=True
        )

        st.info("The manual will open in a new tab.")

        st.success("✅ You’re now ready to explore your Smart Energy Monitoring Dashboard with confidence!")


# ------------------------------------------------------------------------------------
# Sidebar navigation (single source of truth) + Router
route_to_index = {"home":0, "mydevices":1, "add":2, "manage":3, "manual":4}
index = route_to_index.get(st.session_state.route, 0)

nav_choice = st.sidebar.radio("Navigate", ["Home", "My Devices", "Add Device", "Manage Devices", "User Manual"], index=index)
st.sidebar.markdown("---")
st.sidebar.caption("Auto-logging every 5s while a device page is open.")

sidebar_map = {"Home":"home", "My Devices":"mydevices", "Add Device":"add", "Manage Devices":"manage", "User Manual":"manual"}

# Only change route from sidebar when not on a device detail page
if st.session_state.route != "device":
    set_route(sidebar_map.get(nav_choice, "home"))

# Router
if st.session_state.route == "home":
    page_home()
elif st.session_state.route == "mydevices":
    page_mydevices()
elif st.session_state.route == "add":
    page_add()
elif st.session_state.route == "manage":
    page_manage()
elif st.session_state.route == "device":
    page_device()
elif st.session_state.route == "manual":
    page_manual()
else:
    page_home()
