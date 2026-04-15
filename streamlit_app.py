import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, time, timedelta
import numpy as np
import streamlit_shadcn_ui as ui

# --- Page Config ---
st.set_page_config(
    page_title="ATC PositionLog Dashboard",
    page_icon="✈️",
    layout="wide",
)

# --- Styling ---
st.markdown("""
    <style>
    .main { background-color: #0c0e14; }
    
    /* Global Metric Styling */
    div[data-testid="stMetric"] {
        background-color: #1a1c23;
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #2d303d;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    
    div[data-testid="stMetricLabel"] > div {
        color: #94a3b8 !important;
        font-weight: 500 !important;
        font-size: 0.9rem !important;
    }
    
    div[data-testid="stMetricValue"] > div {
        color: #f8fafc !important;
        font-weight: 700 !important;
    }

    .stTabs [data-baseweb="tab-list"] { gap: 24px; margin-bottom: 20px; }
    div[data-testid="stExpander"] { background-color: #1a1c23; border: 1px solid #2d303d; border-radius: 8px; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# --- Helpers ---
def format_hm(decimal_hours):
    if pd.isna(decimal_hours) or decimal_hours == 0:
        return "0h 0m"
    h = int(decimal_hours)
    m = int(round((decimal_hours - h) * 60))
    if m == 60:
        h += 1
        m = 0
    return f"{h}h {m}m"

def get_corrected_duty(start_time):
    if start_time is None: return "N/A"
    h = start_time.hour
    if 6 <= h < 12: return "MORNING"
    elif 12 <= h < 18: return "AFTERNOON"
    elif 18 <= h <= 23: return "EVENING"
    else: return "NIGHT"

# --- Data Loading ---
@st.cache_data(ttl=600)
def load_staff_mapping():
    try:
        df = pd.read_excel("ats-staff-list.xlsx")
        return df
    except Exception as e:
        st.error(f"Error loading staff list: {e}")
        return pd.DataFrame(columns=['Staff Name', 'Unit', 'Staff Code', 'RC No'])

@st.cache_data(ttl=600)
def load_data():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(worksheet="YEAR 2024")
    
    # Filter Units early as requested
    df = df[df['UNIT'].isin(['MATCC', 'MALE TWR'])]
    
    # Basic cleanup
    df = df.dropna(subset=['DATE', 'TIME IN', 'TIME OUT'])
    df['DATE'] = pd.to_datetime(df['DATE'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['DATE'])
    
    def parse_time(t_str):
        if pd.isna(t_str): return None
        if isinstance(t_str, time): return t_str
        try:
            if isinstance(t_str, (float, int)):
                return (datetime.min + timedelta(days=float(t_str))).time()
            return pd.to_datetime(str(t_str), errors='coerce').time()
        except: return None

    df['TIME IN'] = df['TIME IN'].apply(parse_time)
    df['TIME OUT'] = df['TIME OUT'].apply(parse_time)
    df = df.dropna(subset=['TIME IN', 'TIME OUT'])
    
    durations = []
    corrected_duties = []
    for idx, row in df.iterrows():
        t_in, t_out, d = row['TIME IN'], row['TIME OUT'], row['DATE']
        dt_in = datetime.combine(d, t_in)
        dt_out = datetime.combine(d, t_out)
        if dt_out <= dt_in: dt_out += timedelta(days=1)
        diff = (dt_out - dt_in).total_seconds() / 3600.0
        durations.append(diff)
        corrected_duties.append(get_corrected_duty(t_in))
            
    df['Calculated_Duration'] = durations
    df['Corrected_DUTY'] = corrected_duties
    return df

# --- Main App ---
def main():
    st.title("✈️ ATC PositionLog Dashboard")
    
    try:
        df = load_data()
        staff_mapping = load_staff_mapping()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return

    # --- Sidebar Filters ---
    st.sidebar.header("Filters")
    min_date, max_date = df['DATE'].min(), df['DATE'].max()
    date_range = st.sidebar.date_input("Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
    
    units = sorted([str(u) for u in df['UNIT'].unique() if pd.notna(u)])
    selected_units = st.sidebar.multiselect("Unit", units, default=units)
    
    # Dependent Staff Search
    if selected_units:
        filtered_mapping = staff_mapping[staff_mapping['Unit'].str.upper().isin([u.upper() for u in selected_units])]
        valid_staff_names = sorted(filtered_mapping['Staff Name'].dropna().unique().tolist())
    else:
        valid_staff_names = sorted(staff_mapping['Staff Name'].dropna().unique().tolist())
    
    log_names = set(df['NAME'].unique().tolist())
    if not selected_units or len(selected_units) == len(units):
        staff_options = sorted(list(set(valid_staff_names) | log_names))
    else:
        staff_options = valid_staff_names
        
    selected_staff = st.sidebar.selectbox("Search Staff Name", ["All"] + [str(n) for n in staff_options if pd.notna(n)])

    # Add Position filter back for general dashboard
    positions = sorted([str(p) for p in df['POSITION'].unique() if pd.notna(p)])
    selected_positions = st.sidebar.multiselect("Filter by Positions", positions, default=positions)

    # Apply Filters
    if len(date_range) == 2:
        start_date, end_date = date_range
        filtered_df = df[(df['DATE'].dt.date >= start_date) & (df['DATE'].dt.date <= end_date)]
    else: filtered_df = df
        
    if selected_units: filtered_df = filtered_df[filtered_df['UNIT'].isin(selected_units)]
    if selected_positions: filtered_df = filtered_df[filtered_df['POSITION'].isin(selected_positions)]
    
    # --- Controller Isolation ---
    staff_df = filtered_df if selected_staff == "All" else filtered_df[filtered_df['NAME'] == selected_staff]

    # --- Metrics Section ---
    st.divider()
    
    # 1. Unit Comparison (Side by Side)
    with ui.card(key="unit_comparison"):
        st.subheader("Unit Comparison: Avg Hours / Day")
        c1, c2 = st.columns(2)
        unique_days = filtered_df['DATE'].nunique() if not filtered_df.empty else 1
        
        matcc_data = filtered_df[filtered_df['UNIT'] == 'MATCC']
        matcc_avg = matcc_data['Calculated_Duration'].sum() / unique_days
        
        twr_data = filtered_df[filtered_df['UNIT'] == 'MALE TWR']
        twr_avg = twr_data['Calculated_Duration'].sum() / unique_days
        
        with c1: ui.metric_card(title="MATCC Avg", content=format_hm(matcc_avg), description="Total Hours / Unique Days", key="avg_matcc")
        with c2: ui.metric_card(title="MALE TWR Avg", content=format_hm(twr_avg), description="Total Hours / Unique Days", key="avg_twr")

    # 2. Main Analytics
    tabs = st.tabs(["👤 Controller Profile", "🗓️ Activity History"])
    prof_tab, hist_tab = tabs

    with prof_tab:
        if selected_staff == "All":
            st.info("Select an individual controller from the sidebar to view their profile and detailed position performance.")
        else:
            # Controller Profile
            profile_info = staff_mapping[staff_mapping['Staff Name'] == selected_staff].iloc[0] if not staff_mapping[staff_mapping['Staff Name'] == selected_staff].empty else None
            
            with ui.card(key="profile_card"):
                c1, c2 = st.columns([1, 3])
                with c1:
                    st.markdown(f"# {selected_staff}")
                    if profile_info is not None:
                        st.markdown(f"**RC No:** `{profile_info['RC No']}`")
                        st.markdown(f"**Staff Code:** `{profile_info['Staff Code']}`")
                        st.markdown(f"**Unit:** {profile_info['Unit']}")
                
                with c2:
                    m1, m2, m3 = st.columns(3)
                    total_p = staff_df['Calculated_Duration'].sum()
                    avg_p = staff_df['Calculated_Duration'].mean()
                    max_p = staff_df['Calculated_Duration'].max()
                    
                    with m1: ui.metric_card(title="Total Hours", content=format_hm(total_p), key="prof_total")
                    with m2: ui.metric_card(title="Avg Shift", content=format_hm(avg_p), key="prof_avg")
                    with m3: ui.metric_card(title="Longest Shift", content=format_hm(max_p), key="prof_max")
            
            # Position Performance KPIs (Conditional & Individual only)
            st.subheader("Position Performance")
            groups = {
                "AREA": ['Area Executive', 'Area OJTI/Supervisor', 'Area Planner'],
                "APPROACH": ['Approach Executive', 'Approach Director', 'Approach OJTI/Supervisor', 'Approach Director OJTI / Supervisor'],
                "TOWER & GROUND": ['Tower EX 1', 'Tower EX 2', 'Tower Supervisor / Asst', 'Ground']
            }
            for group_name, pos_list in groups.items():
                st.markdown(f"#### {group_name}")
                group_data = staff_df[staff_df['POSITION'].isin(pos_list)]
                # Filter columns to only those that have data for this staff to save space
                active_pos = [p for p in pos_list if not group_data[group_data['POSITION'] == p].empty]
                if active_pos:
                    cols = st.columns(len(active_pos))
                    for idx, pos in enumerate(active_pos):
                        pos_hrs = group_data[group_data['POSITION'] == pos]['Calculated_Duration'].sum()
                        with cols[idx]:
                            ui.metric_card(title=pos, content=format_hm(pos_hrs), key=f"pos_{pos}_{idx}")
                else:
                    st.caption(f"No logged hours for {group_name} positions.")
            
            # Trends & Charts
            st.divider()
            col_left, col_right = st.columns(2)
            with col_left:
                st.subheader("Position Breakdown")
                pos_mix = staff_df.groupby('POSITION')['Calculated_Duration'].sum().reset_index()
                fig_mix = px.pie(pos_mix, values='Calculated_Duration', names='POSITION', template="plotly_dark", hole=0.4)
                st.plotly_chart(fig_mix, use_container_width=True)
            
            with col_right:
                st.subheader("Logged Hours Trend")
                trend_data = staff_df.set_index('DATE').resample('ME')['Calculated_Duration'].sum().reset_index()
                fig_trend = px.line(trend_data, x='DATE', y='Calculated_Duration', line_shape="spline",
                               template="plotly_dark", color_discrete_sequence=['#00f2ff'])
                st.plotly_chart(fig_trend, use_container_width=True)

    with hist_tab:
        st.subheader("Activity History")
        # Grouped Logs by Date
        dates = sorted(staff_df['DATE'].unique(), reverse=True)
        for d in dates:
            d_dt = pd.to_datetime(d)
            d_str = d_dt.strftime("%d-%b-%Y")
            day_data = staff_df[staff_df['DATE'] == d].copy()
            day_data['Duration_HM'] = day_data['Calculated_Duration'].apply(format_hm)
            
            with st.expander(f"📅 {d_str} - {len(day_data)} entries"):
                display_cols = ['TIME IN', 'TIME OUT', 'POSITION', 'Duration_HM', 'Corrected_DUTY']
                st.table(day_data[display_cols])

if __name__ == "__main__":
    main()
