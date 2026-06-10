"""
🔥 Fire Fighter Document Version Check — Streamlit Dashboard
═══════════════════════════════════════════════════════════════
Upload Fire Safety PDFs, store versioned clauses, and semantically
compare changes across editions with an AI-powered diff engine.
"""

import sys
import os
import pandas as pd
import streamlit as st

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.db import init_db
from database.operations import (
    upsert_document,
    add_version,
    get_all_documents,
    get_versions,
    get_clauses,
)
from ingestion.extractor import extract_text_from_bytes
from ingestion.cleaner import clean_text
from ingestion.clause_parser import parse_clauses
from comparison.engine import SemanticComparator
from comparison.report import ChangeType, CHANGE_TYPE_COLORS, CHANGE_TYPE_BG_COLORS


# ─── Page Config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="🔥 Fire Safety Document Version Check",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="st-"] {
        font-family: 'Inter', sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }
    .main-header h1 {
        color: #ff6b35;
        font-size: 2rem;
        font-weight: 700;
        margin: 0 0 0.5rem 0;
        letter-spacing: -0.5px;
    }
    .main-header p {
        color: #a0aec0;
        font-size: 1rem;
        margin: 0;
        font-weight: 300;
    }

    .metric-card {
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.15);
    }
    .metric-card .metric-value {
        font-size: 2.2rem;
        font-weight: 700;
        line-height: 1.2;
    }
    .metric-card .metric-label {
        font-size: 0.8rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-top: 0.3rem;
        opacity: 0.85;
    }

    .clause-card {
        border-radius: 10px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.75rem;
        border-left: 4px solid;
        transition: transform 0.15s ease;
    }
    .clause-card:hover {
        transform: translateX(3px);
    }
    .clause-number {
        font-weight: 700;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .clause-content {
        font-size: 0.92rem;
        line-height: 1.6;
        margin-top: 0.4rem;
    }
    .similarity-badge {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    .sidebar-section {
        background: rgba(255,255,255,0.03);
        border-radius: 10px;
        padding: 1rem;
        margin-bottom: 1rem;
    }

    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f0f1a 0%, #1a1a2e 100%);
    }

    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
</style>
""", unsafe_allow_html=True)


# ─── Initialize ───────────────────────────────────────────────────────
init_db()


@st.cache_resource
def load_comparator():
    """Load the Sentence-Transformer model once and cache it."""
    return SemanticComparator()


# ─── Header ───────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🔥 Fire Safety Document Version Check</h1>
    <p>Upload fire safety PDFs, track clause-level versions, and discover semantic changes with AI-powered analysis</p>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# SIDEBAR — Document Upload & Ingestion
# ═══════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### 📄 Upload Document")

    uploaded_file = st.file_uploader(
        "Choose a Fire Safety PDF",
        type=["pdf"],
        help="Upload a PDF to extract and store its clauses.",
    )

    doc_name = st.text_input(
        "Document Name",
        placeholder="e.g., NBC Fire Safety Code",
        help="Logical name grouping all versions together.",
    )

    version_label = st.text_input(
        "Version Label",
        placeholder="e.g., 2024 Edition",
        help="Unique label for this version of the document.",
    )

    doc_description = st.text_area(
        "Description (optional)",
        placeholder="Brief description of this document...",
        height=80,
    )

    ingest_btn = st.button("🚀 Ingest Document", use_container_width=True, type="primary")

    if ingest_btn:
        if not uploaded_file:
            st.error("Please upload a PDF file.")
        elif not doc_name.strip():
            st.error("Please enter a document name.")
        elif not version_label.strip():
            st.error("Please enter a version label.")
        else:
            with st.spinner("Extracting text from PDF..."):
                raw_text = extract_text_from_bytes(
                    uploaded_file.read(), uploaded_file.name
                )

            with st.spinner("Cleaning and parsing clauses..."):
                cleaned = clean_text(raw_text)
                clauses_data = parse_clauses(cleaned)

            if not clauses_data:
                st.warning("No clauses could be parsed from this document.")
            else:
                with st.spinner("Saving to database..."):
                    doc = upsert_document(doc_name.strip(), doc_description.strip() or None)
                    version = add_version(
                        doc.id, version_label.strip(),
                        uploaded_file.name, clauses_data,
                    )

                st.success(
                    f"✅ Ingested **{len(clauses_data)}** clauses as "
                    f"**{version_label}** of **{doc_name}**."
                )

    st.markdown("---")
    st.markdown("### 📊 Database Stats")
    all_docs = get_all_documents()
    st.metric("Documents", len(all_docs))
    total_versions = sum(len(get_versions(d.id)) for d in all_docs)
    st.metric("Total Versions", total_versions)


# ═══════════════════════════════════════════════════════════════════════
# MAIN AREA — Comparison Interface
# ═══════════════════════════════════════════════════════════════════════

st.markdown("## 🔍 Compare Document Versions")

all_docs = get_all_documents()

if not all_docs:
    st.info(
        "👈 **Get started** by uploading a Fire Safety PDF in the sidebar. "
        "Upload at least **two versions** of the same document to compare them."
    )
    st.stop()

# ─── Document & Version Selection ─────────────────────────────────────
col_doc, col_v1, col_v2 = st.columns([2, 1, 1])

with col_doc:
    doc_options = {d.name: d.id for d in all_docs}
    selected_doc_name = st.selectbox("📁 Select Document", list(doc_options.keys()))
    selected_doc_id = doc_options[selected_doc_name]

versions = get_versions(selected_doc_id)

if len(versions) < 2:
    st.warning(
        f"📌 **{selected_doc_name}** has only **{len(versions)}** version(s). "
        "Upload at least 2 versions to compare."
    )
    st.stop()

version_options = {
    f"{v.version_label} ({v.uploaded_at.strftime('%Y-%m-%d %H:%M') if v.uploaded_at else 'N/A'})": v.id
    for v in versions
}
version_labels = list(version_options.keys())

with col_v1:
    v1_label = st.selectbox("📗 Version 1 (Baseline)", version_labels, index=min(1, len(version_labels) - 1))
    v1_id = version_options[v1_label]

with col_v2:
    v2_label = st.selectbox("📕 Version 2 (Updated)", version_labels, index=0)
    v2_id = version_options[v2_label]

if v1_id == v2_id:
    st.warning("⚠️ Please select two **different** versions to compare.")
    st.stop()

# ─── Run Comparison ───────────────────────────────────────────────────
compare_btn = st.button("⚡ Run Semantic Comparison", use_container_width=True, type="primary")

if compare_btn or st.session_state.get("last_comparison"):
    if compare_btn:
        with st.spinner("🧠 Loading AI model and computing semantic similarity..."):
            comparator = load_comparator()

            clauses_v1 = get_clauses(v1_id)
            clauses_v2 = get_clauses(v2_id)

            # Convert ORM objects to dicts for the comparator
            c1_dicts = [
                {"clause_number": c.clause_number, "title": c.title, "content": c.content}
                for c in clauses_v1
            ]
            c2_dicts = [
                {"clause_number": c.clause_number, "title": c.title, "content": c.content}
                for c in clauses_v2
            ]

            report = comparator.compare_clauses(
                c1_dicts, c2_dicts,
                document_name=selected_doc_name,
                version_v1_label=v1_label.split(" (")[0],
                version_v2_label=v2_label.split(" (")[0],
            )

            st.session_state["last_comparison"] = report

    report = st.session_state.get("last_comparison")
    if report is None:
        st.stop()

    # ─── Summary Metrics ──────────────────────────────────────────────
    st.markdown("### 📈 Comparison Summary")

    m1, m2, m3, m4, m5, m6 = st.columns(6)

    with m1:
        st.markdown(f"""
        <div class="metric-card" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);">
            <div class="metric-value" style="color: #e2e8f0;">{report.summary.total_clauses}</div>
            <div class="metric-label" style="color: #a0aec0;">Total Clauses</div>
        </div>
        """, unsafe_allow_html=True)

    with m2:
        st.markdown(f"""
        <div class="metric-card" style="background: rgba(46,204,113,0.1); border: 1px solid rgba(46,204,113,0.3);">
            <div class="metric-value" style="color: #2ecc71;">{report.summary.unchanged}</div>
            <div class="metric-label" style="color: #2ecc71;">Unchanged</div>
        </div>
        """, unsafe_allow_html=True)

    with m3:
        st.markdown(f"""
        <div class="metric-card" style="background: rgba(243,156,18,0.1); border: 1px solid rgba(243,156,18,0.3);">
            <div class="metric-value" style="color: #f39c12;">{report.summary.minor_edits}</div>
            <div class="metric-label" style="color: #f39c12;">Minor Edits</div>
        </div>
        """, unsafe_allow_html=True)

    with m4:
        st.markdown(f"""
        <div class="metric-card" style="background: rgba(231,76,60,0.1); border: 1px solid rgba(231,76,60,0.3);">
            <div class="metric-value" style="color: #e74c3c;">{report.summary.significant_changes}</div>
            <div class="metric-label" style="color: #e74c3c;">Significant</div>
        </div>
        """, unsafe_allow_html=True)

    with m5:
        st.markdown(f"""
        <div class="metric-card" style="background: rgba(52,152,219,0.1); border: 1px solid rgba(52,152,219,0.3);">
            <div class="metric-value" style="color: #3498db;">{report.summary.added}</div>
            <div class="metric-label" style="color: #3498db;">Added</div>
        </div>
        """, unsafe_allow_html=True)

    with m6:
        st.markdown(f"""
        <div class="metric-card" style="background: rgba(155,89,182,0.1); border: 1px solid rgba(155,89,182,0.3);">
            <div class="metric-value" style="color: #9b59b6;">{report.summary.removed}</div>
            <div class="metric-label" style="color: #9b59b6;">Removed</div>
        </div>
        """, unsafe_allow_html=True)

    # Change rate bar
    st.markdown(f"""
    <div style="margin: 1.5rem 0; padding: 0.8rem 1.2rem; background: rgba(255,107,53,0.08);
                border-radius: 10px; border: 1px solid rgba(255,107,53,0.2);">
        <span style="font-weight: 600; color: #ff6b35;">📊 Overall Change Rate:</span>
        <span style="font-size: 1.3rem; font-weight: 700; color: #ff6b35; margin-left: 0.5rem;">
            {report.summary.change_rate:.1f}%
        </span>
    </div>
    """, unsafe_allow_html=True)

    # ─── Filter ───────────────────────────────────────────────────────
    st.markdown("### 🔎 Clause-Level Comparison")

    filter_options = ["All"] + [ct.value for ct in ChangeType]
    selected_filter = st.selectbox(
        "Filter by Change Type",
        filter_options,
        help="Show only clauses matching a specific change type.",
    )

    comparisons = report.comparisons
    if selected_filter != "All":
        comparisons = [
            c for c in comparisons
            if c.change_type.value == selected_filter
        ]

    if not comparisons:
        st.info(f"No clauses match the filter: **{selected_filter}**")
    else:
        st.caption(f"Showing {len(comparisons)} of {len(report.comparisons)} clauses")

    # ─── Side-by-side Comparison ──────────────────────────────────────
    for comp in comparisons:
        change_color = CHANGE_TYPE_COLORS[comp.change_type]
        bg_color = CHANGE_TYPE_BG_COLORS[comp.change_type]

        # Similarity badge
        if comp.similarity_score is not None:
            sim_text = f"{comp.similarity_score:.2%}"
        else:
            sim_text = comp.change_type.value

        # Header row
        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 0.8rem; margin-top: 1rem; margin-bottom: 0.3rem;">
            <span class="clause-number" style="color: {change_color};">
                § {comp.clause_number}
                {f' — {comp.title}' if comp.title else ''}
            </span>
            <span class="similarity-badge" style="background: {bg_color}; color: {change_color}; border: 1px solid {change_color}40;">
                {comp.change_type.value} | {sim_text}
            </span>
        </div>
        """, unsafe_allow_html=True)

        col_left, col_right = st.columns(2)

        with col_left:
            content_v1 = comp.content_v1 or "*(Clause not present in this version)*"
            st.markdown(f"""
            <div class="clause-card" style="background: {bg_color}; border-left-color: {change_color};">
                <div style="font-size: 0.72rem; font-weight: 600; color: {change_color}; text-transform: uppercase;
                            letter-spacing: 1px; margin-bottom: 0.4rem;">
                    📗 {report.version_v1_label}
                </div>
                <div class="clause-content">{content_v1[:1000]}{'...' if len(content_v1) > 1000 else ''}</div>
            </div>
            """, unsafe_allow_html=True)

        with col_right:
            content_v2 = comp.content_v2 or "*(Clause not present in this version)*"
            st.markdown(f"""
            <div class="clause-card" style="background: {bg_color}; border-left-color: {change_color};">
                <div style="font-size: 0.72rem; font-weight: 600; color: {change_color}; text-transform: uppercase;
                            letter-spacing: 1px; margin-bottom: 0.4rem;">
                    📕 {report.version_v2_label}
                </div>
                <div class="clause-content">{content_v2[:1000]}{'...' if len(content_v2) > 1000 else ''}</div>
            </div>
            """, unsafe_allow_html=True)

    # ─── Export ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 💾 Export Report")

    df = pd.DataFrame(report.to_dataframe_rows())

    col_csv, col_info = st.columns([1, 2])
    with col_csv:
        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download CSV Report",
            data=csv_data,
            file_name=f"comparison_{report.version_v1_label}_vs_{report.version_v2_label}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col_info:
        st.dataframe(df, use_container_width=True, hide_index=True)
