"""All custom CSS for the VaultWise app."""

import streamlit as st


def inject_css():
    st.markdown("""<style>
    /* Metric cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #f8f9fb 0%, #f0f2f6 100%);
        border: 1px solid #e2e6ed; border-radius: 14px; padding: 16px 20px;
        transition: transform 0.15s ease;
    }
    [data-testid="stMetric"]:hover { transform: translateY(-1px); }
    [data-testid="stMetricValue"] { font-size: 1.5rem; font-weight: 700; color: #1a1a2e; }
    [data-testid="stMetricLabel"] { font-size: 0.75rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600; }

    /* Sidebar */
    section[data-testid="stSidebar"] > div { padding-top: 1rem; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 4px; background: #f8f9fb; padding: 4px; border-radius: 10px; }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px; padding: 8px 16px; font-weight: 500;
    }
    .stTabs [aria-selected="true"] { background: white !important; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }

    /* Clean expanders */
    [data-testid="stExpander"] { border: 1px solid #e2e6ed; border-radius: 12px; overflow: hidden; }
    [data-testid="stExpander"] summary { font-weight: 500; }

    /* Alerts */
    .stAlert { border-radius: 10px; }

    /* Hide branding */
    #MainMenu, footer, header { visibility: hidden; }

    /* Chat */
    [data-testid="stChatMessage"] { border-radius: 12px; }

    /* Category cards — thicker severity stripes */
    .cat-card { border-radius: 12px; padding: 16px; margin-bottom: 8px; border-left: 6px solid; }
    .cat-card-critical { border-left-color: #ef4444; background: #fef2f2; }
    .cat-card-warning { border-left-color: #f59e0b; background: #fffbeb; }
    .cat-card-good { border-left-color: #22c55e; background: #f0fdf4; }
    .cat-card-neutral { border-left-color: #6b7280; background: #f9fafb; }

    /* Progress bars */
    .budget-bar { height: 8px; border-radius: 4px; background: #e5e7eb; overflow: hidden; margin: 6px 0; }
    .budget-fill { height: 100%; border-radius: 4px; transition: width 0.3s ease; }

    /* Dividers */
    hr { border: none; border-top: 1px solid #e8ecf1; margin: 1.2rem 0; }

    /* Mobile responsive */
    @media (max-width: 768px) {
        [data-testid="stMetricValue"] { font-size: clamp(1rem, 4vw, 1.5rem); }
        [data-testid="stMetricLabel"] { font-size: clamp(0.6rem, 2vw, 0.75rem); }
        .cat-card { padding: 10px 12px; margin-bottom: 6px; }
        [data-testid="stExpander"] summary { font-size: 0.9rem; }
        [data-testid="stExpander"] > div { padding: 0.5rem 0.75rem; }
        .block-container { padding: 1rem 0.75rem !important; }
        [data-testid="stPlotlyChart"] > div { max-height: 300px; }
        button, [data-testid="stCheckbox"] label { min-height: 44px; }
        section[data-testid="stSidebar"] > div { padding-top: 0.5rem; }
        section[data-testid="stSidebar"] [data-testid="stMetric"] { padding: 8px 12px; }
        .stTabs [data-baseweb="tab"] { padding: 6px 10px; font-size: 0.85rem; }
    }
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 4px; }

    /* Gauge responsive helpers */
    .gauge-header, .gauge-footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 4px; }
    .gauge-detail { font-size: clamp(0.7rem, 2.5vw, 0.82rem); }
</style>""", unsafe_allow_html=True)
