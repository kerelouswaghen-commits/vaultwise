"""All custom CSS for the VaultWise app."""

import streamlit as st


def inject_css():
    st.markdown("""<style>
    /* ── Design tokens (matching mockup design system) ─────────── */
    :root {
        --vw-green: #22c55e; --vw-green-dark: #16a34a; --vw-green-bg: #f0fdf4;
        --vw-red: #ef4444; --vw-red-bg: #fef2f2;
        --vw-amber: #f59e0b; --vw-amber-bg: #fffbeb;
        --vw-blue: #2563eb;
        --vw-purple: #7c3aed;
        --vw-teal: #0d9488; --vw-teal-bg: #f0fdfa;
        --vw-gray: #6b7280;
        --vw-bg: #f8f9fb;
        --vw-bg-alt: #f0f2f6;
        --vw-card-bg: #ffffff;
        --vw-card-bg-alt: #f8f9fb;
        --vw-border: #d1d5db;
        --vw-border-light: #f3f4f6;
        --vw-text: #1a1a2e;
        --vw-text-muted: #6b7280;
        --vw-text-faint: #9ca3af;
        --vw-input-bg: #ffffff;
        --vw-input-border: #e5e7eb;
        --vw-progress-bg: #e5e7eb;
        --vw-radius: 16px;
        --vw-radius-sm: 10px;
        --vw-radius-xs: 6px;
        --vw-shadow: 0 1px 3px rgba(0,0,0,0.04);
        --vw-shadow-md: 0 1px 3px rgba(0,0,0,0.06), 0 4px 12px rgba(0,0,0,0.08);
        --vw-shadow-lg: 0 8px 24px rgba(0,0,0,0.12);
    }

    /* ── DARK MODE ────────────────────────────────────────────── */
    [data-theme="dark"] {
        --vw-bg: #0f0f14; --vw-bg-alt: #16161e;
        --vw-card-bg: #1a1a24; --vw-card-bg-alt: #22222e;
        --vw-border: #2a2a38; --vw-border-light: #22222e;
        --vw-text: #e0e0e8; --vw-text-muted: #8888a0; --vw-text-faint: #66667a;
        --vw-input-bg: #22222e; --vw-input-border: #33334a;
        --vw-progress-bg: #2a2a3a;
        --vw-green-bg: #0f2a1a; --vw-red-bg: #2a0f0f; --vw-amber-bg: #2a1f0f;
        --vw-shadow: 0 1px 3px rgba(0,0,0,0.3);
        --vw-shadow-md: 0 2px 6px rgba(0,0,0,0.4);
        --vw-shadow-lg: 0 8px 24px rgba(0,0,0,0.5);
    }
    [data-theme="dark"] .stApp,
    [data-theme="dark"] [data-testid="stAppViewContainer"],
    [data-theme="dark"] .main .block-container { background-color: var(--vw-bg) !important; color: var(--vw-text) !important; }
    [data-theme="dark"] section[data-testid="stSidebar"] { background-color: var(--vw-bg-alt) !important; }
    [data-theme="dark"] p, [data-theme="dark"] span, [data-theme="dark"] div,
    [data-theme="dark"] label, [data-theme="dark"] h1, [data-theme="dark"] h2,
    [data-theme="dark"] h3, [data-theme="dark"] h4 { color: var(--vw-text) !important; }
    [data-theme="dark"] .vw-ai-suggest { background: linear-gradient(135deg, #1e1b2e, #2a2640); border-color: #3a3550; }
    [data-theme="dark"] .vw-ai-suggest .suggest-body { color: #c4b5fd; }

    /* App background */
    .stApp, [data-testid="stAppViewContainer"] { background-color: var(--vw-bg) !important; }

    /* Metric cards — premium look */
    [data-testid="stMetric"] {
        background: var(--vw-card-bg); border: 1px solid var(--vw-border);
        border-radius: var(--vw-radius); padding: 16px 20px;
        box-shadow: var(--vw-shadow);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    [data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow: var(--vw-shadow-md); }
    [data-testid="stMetricValue"] { font-size: clamp(1.2rem, 3.5vw, 1.5rem); font-weight: 700; color: var(--vw-text); }
    [data-testid="stMetricLabel"] { font-size: 0.7rem; color: var(--vw-text-muted); text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
    [data-testid="stMetricDelta"] { font-size: 0.8rem; }

    /* Hide slider thumb value labels to prevent overlap with custom labels.
       Targets the BaseWeb StyledThumbValue positioned above the thumb knob. */
    [data-testid="stSlider"] [data-testid="stThumbValue"] { display: none !important; }
    [data-baseweb="slider"] [role="slider"] > div:first-child {
        visibility: hidden !important;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] > div { padding-top: 1rem; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] { gap: 4px; background: var(--vw-bg); padding: 4px; border-radius: 10px; }
    .stTabs [data-baseweb="tab"] { border-radius: 8px; padding: 8px 16px; font-weight: 500; color: var(--vw-text-muted) !important; }
    .stTabs [aria-selected="true"] { background: var(--vw-card-bg) !important; box-shadow: var(--vw-shadow); color: var(--vw-text) !important; }

    /* Segmented nav — compact on mobile */
    [data-testid="stSegmentedControl"] button {
        padding: 6px 8px !important;
        font-size: 13px !important;
        min-height: 32px !important;
    }
    [data-testid="stSegmentedControl"] {
        gap: 2px !important;
    }

    /* Expanders — V5 collapsible card style */
    [data-testid="stExpander"] { border: 1px solid var(--vw-border) !important; border-radius: 14px !important; overflow: hidden; background: var(--vw-card-bg) !important; box-shadow: var(--vw-shadow); }
    [data-testid="stExpander"] summary { font-weight: 600 !important; font-size: 13px !important; color: var(--vw-text) !important; padding: 14px 16px !important; }
    [data-testid="stExpander"] > div[data-testid="stExpanderDetails"] { border-top: 1px solid var(--vw-border-light) !important; }

    /* Streamlit widget overrides — inputs */
    [data-testid="stTextInput"] input, [data-baseweb="input"] input {
        border-radius: 12px !important; border: 1.5px solid var(--vw-input-border) !important;
        background: var(--vw-input-bg) !important; color: var(--vw-text) !important; font-size: 14px !important;
    }
    [data-testid="stNumberInput"] input {
        border-radius: 10px !important; border: 1.5px solid var(--vw-input-border) !important;
        background: var(--vw-input-bg) !important; color: var(--vw-text) !important;
    }
    [data-baseweb="select"] > div { border-radius: 12px !important; border-color: var(--vw-input-border) !important; background: var(--vw-input-bg) !important; }
    [data-testid="stDateInput"] > div > div { border-radius: 12px !important; border-color: var(--vw-input-border) !important; background: var(--vw-input-bg) !important; }
    [data-testid="stFileUploader"] > div { border-radius: 14px !important; border: 2px dashed var(--vw-border) !important; background: var(--vw-card-bg) !important; }

    /* Buttons — V5 pill style */
    .stButton > button { border-radius: 12px !important; font-weight: 500 !important; font-size: 13px !important; border: 1.5px solid var(--vw-border) !important; background: var(--vw-card-bg) !important; color: var(--vw-text) !important; }
    .stButton > button:hover { border-color: var(--vw-text-muted) !important; box-shadow: var(--vw-shadow) !important; }
    .stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"] { background: var(--vw-blue) !important; color: #fff !important; border-color: var(--vw-blue) !important; }
    .stDownloadButton > button { border-radius: 12px !important; font-size: 13px !important; }

    /* Alerts */
    .stAlert { border-radius: 10px; }

    /* Hide branding */
    #MainMenu, footer, header { visibility: hidden; }

    /* Chat — consistent sizing */
    [data-testid="stChatMessage"] { border-radius: 12px; }
    [data-testid="stChatMessage"] p,
    [data-testid="stChatMessage"] li,
    [data-testid="stChatMessage"] span {
        font-size: 0.88rem;
        line-height: 1.5;
    }

    /* Bottom padding for sticky chat_input */
    .main .block-container { padding-bottom: 70px !important; }

    /* Category cards — premium design matching mockup */
    .cat-card {
        border-radius: 12px; padding: 14px 16px; margin-bottom: 10px;
        border-left: 6px solid; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .cat-card:hover { transform: translateX(2px); box-shadow: var(--vw-shadow); }
    .cat-card-critical { border-left-color: var(--vw-red); background: var(--vw-red-bg); }
    .cat-card-warning { border-left-color: var(--vw-amber); background: var(--vw-amber-bg); }
    .cat-card-good { border-left-color: var(--vw-green); background: var(--vw-green-bg); }
    .cat-card-pace { border-left-color: #6366f1; background: #eef2ff; }
    .cat-card-neutral { border-left-color: var(--vw-gray); background: var(--vw-card-bg-alt); }

    /* Severity badges (pill-shaped) */
    .vw-badge {
        display: inline-block; padding: 2px 8px; border-radius: 10px;
        font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.3px;
    }
    .vw-badge-red { background: #fee2e2; color: var(--vw-red); }
    .vw-badge-amber { background: #fef3c7; color: #b45309; }
    .vw-badge-green { background: #dcfce7; color: var(--vw-green-dark); }
    .vw-badge-teal { background: #ccfbf1; color: var(--vw-teal); }
    .vw-badge-purple { background: #ede9fe; color: var(--vw-purple); }

    /* Progress bars — thicker for visibility */
    .budget-bar { height: 8px; border-radius: 4px; background: var(--vw-progress-bg); overflow: hidden; margin: 6px 0; }
    .budget-fill { height: 100%; border-radius: 4px; transition: width 0.4s ease; }

    /* Hero status banner */
    .vw-hero {
        border-radius: var(--vw-radius); padding: 24px; color: white;
        margin-bottom: 16px; position: relative; overflow: hidden;
    }
    .vw-hero-green { background: linear-gradient(135deg, var(--vw-green), var(--vw-green-dark)); box-shadow: 0 4px 16px rgba(34,197,94,0.3); }
    .vw-hero-amber { background: linear-gradient(135deg, var(--vw-amber), #d97706); box-shadow: 0 4px 16px rgba(245,158,11,0.3); }
    .vw-hero-red { background: linear-gradient(135deg, var(--vw-red), #dc2626); box-shadow: 0 4px 16px rgba(239,68,68,0.3); }
    .vw-hero-top { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
    .vw-hero-amount { font-size: clamp(1.6rem, 5vw, 2.2rem); font-weight: 800; letter-spacing: -0.5px; }
    .vw-hero-sub { font-size: clamp(0.8rem, 2.5vw, 0.95rem); opacity: 0.9; margin-top: 4px; }
    .vw-hero-pct {
        background: rgba(255,255,255,0.2); border-radius: 20px; padding: 6px 14px;
        font-weight: 700; font-size: 1.1rem; white-space: nowrap;
    }
    .vw-hero-bar { height: 6px; background: rgba(255,255,255,0.3); border-radius: 3px; margin-top: 16px; overflow: hidden; }
    .vw-hero-bar-fill { height: 100%; background: white; border-radius: 3px; }

    /* Dividers */
    hr { border: none; border-top: 1px solid var(--vw-border-light); margin: 1.2rem 0; }

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
        [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        .main .block-container { max-width: 100% !important; }
    }
    [data-testid="stHorizontalBlock"] { gap: 4px; }

    /* Segmented control (nav) — force ALL 5 tabs in one row on any screen */
    [data-testid="stSegmentedControl"],
    [data-testid="stSegmentedControl"] > div,
    [data-testid="stSegmentedControl"] [role="tablist"] {
        flex-wrap: nowrap !important;
        overflow-x: auto !important;
        display: flex !important;
        gap: 0 !important;
        width: 100% !important;
    }
    [data-testid="stSegmentedControl"] button {
        white-space: nowrap !important;
        padding: 4px 6px !important;
        font-size: clamp(10px, 2.2vw, 13px) !important;
        min-height: 34px !important;
        flex: 1 1 0 !important;
        min-width: 0 !important;
    }

    /* Top nav pill bar — force single row on all screen sizes */
    .nav-bar [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important;
        gap: 4px !important;
        overflow-x: auto;
    }
    .nav-bar [data-testid="stHorizontalBlock"] > div {
        flex: 1 1 0 !important;
        min-width: 0 !important;
        width: auto !important;
    }
    .nav-bar button {
        font-size: clamp(0.65rem, 2.5vw, 0.82rem) !important;
        padding: 8px 4px !important;
        border-radius: 10px !important;
        white-space: nowrap;
        min-height: 42px;
    }
    .nav-bar button[kind="primary"] {
        box-shadow: 0 2px 8px rgba(0,102,255,0.25);
    }

    /* Gauge responsive helpers */
    .gauge-header, .gauge-footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 4px; }
    .gauge-detail { font-size: clamp(0.7rem, 2.5vw, 0.82rem); }

    /* Data tables — cleaner styling */
    [data-testid="stDataFrame"] table { border-radius: var(--vw-radius-sm); overflow: hidden; }
    [data-testid="stDataFrame"] th { background: var(--vw-bg) !important; font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.3px; }
    [data-testid="stDataFrame"] td { font-size: 0.85rem; }

    /* Currency formatting helper */
    .currency { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }

    /* Smooth page transitions */
    .main .block-container { animation: fadeIn 0.2s ease-in; }
    @keyframes fadeIn { from { opacity: 0.7; } to { opacity: 1; } }

    /* ── V5 Design System ─────────────────────────────────────── */

    /* Card base */
    .vw-card {
        background: var(--vw-card-bg); border-radius: 16px; padding: 16px;
        box-shadow: var(--vw-shadow); margin-bottom: 12px;
    }
    .vw-card-title {
        font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px;
        color: var(--vw-text-muted); font-weight: 600; margin-bottom: 6px;
    }

    /* V5 Hero — left-aligned with sparkline */
    .vw-hero-v5 {
        border-radius: 20px; overflow: hidden; padding: 20px;
        color: #fff; margin-bottom: 14px; position: relative;
    }
    .vw-hero-v5-green { background: linear-gradient(135deg, #0f4c2e 0%, #16a34a 50%, #22c55e 100%); }
    .vw-hero-v5-amber { background: linear-gradient(135deg, #78350f 0%, #d97706 50%, #f59e0b 100%); }
    .vw-hero-v5-red { background: linear-gradient(135deg, #7f1d1d 0%, #dc2626 50%, #ef4444 100%); }
    .vw-hero-v5 .hero-top {
        display: flex; justify-content: space-between; align-items: flex-start;
    }
    .vw-hero-v5 .hero-label {
        font-size: 11px; opacity: 0.7; text-transform: uppercase;
        letter-spacing: 1.2px; font-weight: 500;
    }
    .vw-hero-v5 .hero-amount {
        font-size: clamp(1.8rem, 6vw, 2.6rem); font-weight: 800;
        letter-spacing: -2px; line-height: 1;
    }
    .vw-hero-v5 .hero-sub {
        font-size: 13px; opacity: 0.85; margin-top: 6px;
    }

    /* Sparkline bars */
    .vw-sparkline {
        display: flex; align-items: flex-end; gap: 2px; height: 28px;
    }
    .vw-sparkline .bar {
        width: 6px; border-radius: 2px; background: rgba(255,255,255,0.5);
        transition: height 0.3s;
    }
    .vw-sparkline .bar-current {
        width: 8px; background: #fff;
    }

    /* Waterfall budget bar */
    .vw-waterfall {
        display: flex; gap: 2px; height: 12px; border-radius: 6px;
        overflow: hidden; margin: 14px 0 4px;
    }
    .vw-waterfall .seg { height: 100%; }
    .vw-waterfall-labels {
        display: flex; justify-content: space-between; font-size: 10px;
        opacity: 0.6; margin-top: 3px;
    }
    .vw-waterfall-labels .current {
        opacity: 1; font-weight: 600;
    }

    /* AI Insight card */
    .vw-ai-insight {
        background: var(--vw-card-bg); border-radius: 14px; padding: 14px 16px;
        box-shadow: var(--vw-shadow); margin-bottom: 14px;
        border-left: 4px solid var(--vw-purple);
    }
    .vw-ai-insight .insight-header {
        display: flex; align-items: center; gap: 6px; margin-bottom: 6px;
    }
    .vw-ai-insight .insight-header span:last-child {
        font-size: 12px; font-weight: 600; color: var(--vw-purple);
    }
    .vw-ai-insight .insight-body {
        font-size: 13px; color: var(--vw-text); line-height: 1.5;
    }

    /* Streak dots */
    .vw-streak-dots {
        display: flex; gap: 4px; justify-content: center;
    }
    .vw-dot {
        width: 7px; height: 7px; border-radius: 50%;
    }
    .vw-dot-hit { background: var(--vw-green); }
    .vw-dot-miss { background: var(--vw-red); }
    .vw-dot-current {
        background: var(--vw-green); border: 1.5px solid #0f4c2e;
    }
    .vw-dot-future { background: var(--vw-progress-bg); }

    /* Flex spending list */
    .vw-flex-list {
        background: var(--vw-card-bg); border-radius: 14px; padding: 16px;
        box-shadow: var(--vw-shadow); margin-bottom: 14px;
    }
    .vw-flex-list .list-header {
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 14px;
    }
    .vw-flex-list .list-header .title {
        font-size: 12px; font-weight: 600; color: var(--vw-text-muted);
        text-transform: uppercase; letter-spacing: 0.8px;
    }
    .vw-flex-list .list-header .total {
        font-size: 14px; font-weight: 700; color: var(--vw-text);
    }
    .vw-flex-row {
        margin-bottom: 8px;
    }
    .vw-flex-row .row-top {
        display: flex; justify-content: space-between; align-items: center;
        margin-bottom: 3px;
    }
    .vw-flex-row .cat-name {
        font-size: 13px; font-weight: 500; color: var(--vw-text);
    }
    .vw-flex-row .row-right {
        display: flex; align-items: center; gap: 6px;
    }
    .vw-flex-row .trend-badge {
        font-size: 12px; font-weight: 500;
    }
    .vw-flex-row .amount {
        font-size: 13px; font-weight: 600;
    }
    .vw-progress-sm {
        height: 6px; background: var(--vw-progress-bg); border-radius: 6px; overflow: hidden;
    }
    .vw-progress-sm .fill {
        height: 100%; border-radius: 6px; transition: width 0.3s;
    }

    /* Collapsible section row */
    .vw-collapse-row {
        background: var(--vw-card-bg); border-radius: 14px; padding: 14px 16px;
        box-shadow: var(--vw-shadow); margin-bottom: 8px;
        cursor: pointer;
    }
    .vw-collapse-row .row-inner {
        display: flex; justify-content: space-between; align-items: center;
    }
    .vw-collapse-row .row-left {
        display: flex; align-items: center; gap: 8px;
    }
    .vw-collapse-row .row-left .icon { font-size: 14px; }
    .vw-collapse-row .row-left .label {
        font-size: 13px; font-weight: 600; color: var(--vw-text);
    }
    .vw-collapse-row .chevron {
        font-size: 14px; color: var(--vw-text-faint);
    }

    /* Quick chat pill buttons */
    .vw-quick-btn {
        display: inline-block; padding: 5px 10px; border-radius: 16px;
        border: 1px solid var(--vw-border); font-size: 11px;
        color: var(--vw-text-muted); background: var(--vw-card-bg); margin: 3px;
        text-decoration: none;
    }

    /* Section label (uppercase muted) */
    .vw-section-label {
        font-size: 11px; font-weight: 600; color: var(--vw-text-faint);
        text-transform: uppercase; letter-spacing: 1px;
        margin-bottom: 8px; padding: 0 4px;
    }

    /* Income allocation bar (Plan) */
    .vw-alloc-bar {
        display: flex; height: 36px; border-radius: 10px; overflow: hidden;
        margin-bottom: 8px;
    }
    .vw-alloc-seg {
        display: flex; align-items: center; justify-content: center;
        font-size: 11px; font-weight: 600; color: #fff;
    }

    /* Dark gradient summary (Transactions) */
    .vw-dark-summary {
        background: linear-gradient(135deg, #1a1a2e, #2d2d44);
        border-radius: 16px; padding: 16px; margin-bottom: 14px; color: #fff;
    }
    .vw-dark-summary .summary-top {
        display: flex; justify-content: space-between; align-items: flex-end;
    }
    .vw-dark-summary .summary-label {
        font-size: 10px; opacity: 0.5; text-transform: uppercase; letter-spacing: 1px;
    }
    .vw-dark-summary .summary-amount {
        font-size: clamp(1.4rem, 4vw, 1.75rem); font-weight: 800; letter-spacing: -1px;
    }
    .vw-dark-summary .summary-bar {
        height: 4px; background: rgba(255,255,255,0.12); border-radius: 4px; margin-top: 10px;
        overflow: hidden;
    }
    .vw-dark-summary .summary-bar .fill {
        height: 100%; background: linear-gradient(90deg, #22c55e, #4ade80); border-radius: 4px;
    }
    .vw-dark-summary .summary-footer {
        display: flex; justify-content: space-between; margin-top: 6px;
        font-size: 10px; opacity: 0.4;
    }

    /* Icon tile (Categories) */
    .vw-icon-tile {
        width: 36px; height: 36px; border-radius: 10px;
        display: flex; align-items: center; justify-content: center;
        font-size: 16px; flex-shrink: 0;
    }

    /* Date group header (Transactions) */
    .vw-date-header {
        display: flex; justify-content: space-between; align-items: center;
        padding: 2px 4px; margin-bottom: 6px;
        font-size: 11px; font-weight: 600; color: var(--vw-text-faint);
    }

    /* Transaction card group */
    .vw-txn-card {
        background: var(--vw-card-bg); border-radius: 16px; overflow: hidden;
        box-shadow: var(--vw-shadow); margin-bottom: 10px;
    }
    .vw-txn-row {
        display: flex; align-items: center; padding: 14px 16px;
        border-bottom: 1px solid var(--vw-border-light);
    }
    .vw-txn-row:last-child { border-bottom: none; }
    .vw-txn-row .txn-icon {
        width: 42px; height: 42px; border-radius: 12px;
        display: flex; align-items: center; justify-content: center;
        font-size: 20px; margin-right: 12px; flex-shrink: 0;
    }
    .vw-txn-row .txn-details { flex: 1; min-width: 0; }
    .vw-txn-row .txn-name {
        font-size: 14px; font-weight: 500; color: var(--vw-text);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .vw-txn-row .txn-meta {
        font-size: 12px; color: var(--vw-text-muted); margin-top: 1px;
    }
    .vw-txn-row .txn-amount {
        font-size: 15px; font-weight: 700; color: var(--vw-text);
        text-align: right; flex-shrink: 0; margin-left: 8px;
    }

    /* AI suggest card (Settings) */
    .vw-ai-suggest {
        background: linear-gradient(135deg, #f5f3ff, #ede9fe);
        border-radius: 16px; padding: 14px 16px; margin-bottom: 12px;
        border: 1px solid #ddd6fe;
    }
    .vw-ai-suggest .suggest-header {
        display: flex; align-items: center; gap: 6px; margin-bottom: 6px;
    }
    .vw-ai-suggest .suggest-header span:last-child {
        font-size: 12px; font-weight: 600; color: var(--vw-purple);
    }
    .vw-ai-suggest .suggest-body {
        font-size: 13px; color: #4c1d95; line-height: 1.5; /* dark mode override in [data-theme=dark] block */
    }

    /* Integration card row (Settings) */
    .vw-integration-row {
        display: flex; align-items: center; padding: 14px 16px;
        border-bottom: 1px solid var(--vw-border-light);
    }
    .vw-integration-row:last-child { border-bottom: none; }
    .vw-integration-row .int-icon {
        width: 40px; height: 40px; border-radius: 12px;
        display: flex; align-items: center; justify-content: center;
        font-size: 18px; margin-right: 12px; flex-shrink: 0;
    }
    .vw-integration-row .int-details { flex: 1; }
    .vw-integration-row .int-title {
        font-size: 14px; font-weight: 500; color: var(--vw-text);
    }
    .vw-integration-row .int-status {
        display: flex; align-items: center; gap: 4px; margin-top: 2px;
    }
    .vw-status-dot {
        width: 6px; height: 6px; border-radius: 50%; display: inline-block;
    }
    .vw-status-dot-green { background: var(--vw-green); }
    .vw-status-dot-red { background: var(--vw-red); }
    .vw-status-dot-gray { background: var(--vw-border); }
    .vw-integration-row .int-chevron {
        font-size: 14px; color: var(--vw-border); flex-shrink: 0;
    }

    /* Year projection cards (Plan) */
    .vw-proj-card {
        text-align: center; padding: 10px; border-radius: 10px; flex: 1;
    }
    .vw-proj-card .proj-label {
        font-size: 10px; color: var(--vw-text-muted);
    }
    .vw-proj-card .proj-value {
        font-size: 18px; font-weight: 700; margin-top: 2px;
    }
    .vw-proj-card .proj-sub {
        font-size: 9px; margin-top: 1px;
    }

    /* V5 Plan hero (dark green) */
    .vw-plan-hero {
        background: linear-gradient(135deg, #0f4c2e, #16a34a);
        border-radius: 16px; padding: 18px; color: #fff;
        margin-bottom: 12px; text-align: center;
    }
    .vw-plan-hero .plan-label {
        font-size: 11px; opacity: 0.7; text-transform: uppercase; letter-spacing: 1px;
    }
    .vw-plan-hero .plan-amount {
        font-size: clamp(1.8rem, 5vw, 2.4rem); font-weight: 800;
        letter-spacing: -1.5px; margin: 4px 0;
    }
    .vw-plan-hero .plan-sub { font-size: 13px; opacity: 0.85; }
    .vw-plan-hero .plan-divider {
        height: 1px; background: rgba(255,255,255,0.15); margin: 12px 0;
    }
    .vw-plan-hero .plan-year {
        font-size: 12px; opacity: 0.7;
    }

    /* Category tile row (Categories V5) */
    .vw-cat-tile-row {
        display: flex; align-items: center; padding: 14px 16px;
        border-bottom: 1px solid var(--vw-border-light);
    }
    .vw-cat-tile-row:last-child { border-bottom: none; }
    .vw-cat-tile-row .tile-icon {
        width: 36px; height: 36px; border-radius: 10px;
        display: flex; align-items: center; justify-content: center;
        font-size: 16px; margin-right: 10px; flex-shrink: 0;
    }
    .vw-cat-tile-row .tile-details { flex: 1; }
    .vw-cat-tile-row .tile-name {
        font-size: 14px; font-weight: 500;
    }
    .vw-cat-tile-row .tile-sub {
        font-size: 11px; margin-top: 1px;
    }
    .vw-cat-tile-row .tile-amount {
        font-size: 15px; font-weight: 700; flex-shrink: 0;
    }

    /* V5 Mobile responsive additions */
    @media (max-width: 768px) {
        .vw-hero-v5 { padding: 16px; border-radius: 16px; }
        .vw-hero-v5 .hero-amount { font-size: clamp(1.5rem, 7vw, 2.2rem); }
        .vw-alloc-seg { font-size: 9px; }
        .vw-dark-summary { padding: 14px; }
        .vw-dark-summary .summary-amount { font-size: clamp(1.2rem, 5vw, 1.5rem); }
        .vw-txn-row .txn-icon { width: 36px; height: 36px; font-size: 16px; margin-right: 10px; }
        .vw-txn-row .txn-name { font-size: 13px; }
        .vw-txn-row .txn-amount { font-size: 14px; }
        .vw-integration-row .int-icon { width: 34px; height: 34px; font-size: 15px; margin-right: 10px; }
        .vw-cat-tile-row .tile-icon { width: 32px; height: 32px; font-size: 14px; }
        .vw-plan-hero .plan-amount { font-size: clamp(1.5rem, 6vw, 2rem); }
        .vw-proj-card .proj-value { font-size: 15px; }
        .vw-flex-row .cat-name { font-size: 12px; }
        .vw-flex-row .amount { font-size: 12px; }
        .vw-ai-insight .insight-body { font-size: 12px; }
    }
</style>""", unsafe_allow_html=True)


def inject_dark_mode_js(enabled=False):
    """Apply dark mode by injecting override CSS directly.

    Since Streamlit blocks <script> in st.markdown and iframe approaches
    are unreliable, we inject dark mode as a CSS override that forces
    dark colors on all elements — no JS or data-theme attribute needed.
    """
    if enabled:
        st.markdown("""<style>
            /* ── FORCED DARK MODE (injected when toggle is on) ── */
            .stApp, [data-testid="stAppViewContainer"],
            .main .block-container { background-color: #0f0f14 !important; color: #e0e0e8 !important; }
            section[data-testid="stSidebar"] { background-color: #16161e !important; }
            section[data-testid="stSidebar"] * { color: #e0e0e8 !important; }
            p, span, div, label, h1, h2, h3, h4, li, td, th,
            [data-testid="stMarkdownContainer"] * { color: #e0e0e8 !important; }
            [data-testid="stExpander"] { background-color: #1a1a24 !important; border-color: #2a2a38 !important; }
            [data-testid="stExpander"] summary span { color: #e0e0e8 !important; }
            .stSelectbox > div > div,
            [data-testid="stSelectbox"] > div > div { background-color: #22222e !important; color: #e0e0e8 !important; border-color: #33334a !important; }
            .stButton > button { background-color: #22222e !important; color: #e0e0e8 !important; border-color: #33334a !important; }
            .stChatMessage { background-color: #1a1a24 !important; }
            [data-testid="stChatInput"] textarea { background-color: #22222e !important; color: #e0e0e8 !important; border-color: #33334a !important; }
            hr { border-color: #2a2a38 !important; }
            .stPopover > div { background-color: #1a1a24 !important; border-color: #2a2a38 !important; }
            [data-testid="stPopover"] [data-testid="stMarkdownContainer"] * { color: #e0e0e8 !important; }
        </style>""", unsafe_allow_html=True)
