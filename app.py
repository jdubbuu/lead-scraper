import os
from datetime import datetime
from io import BytesIO

import pandas as pd
import streamlit as st

# Bridge Streamlit Cloud secrets into environment variables so scraper.py's
# os.getenv() calls and the Anthropic SDK can find the API keys when deployed.
# Locally this is a no-op: there's no .streamlit/secrets.toml, and .env wins.
try:
    for _key in ("GOOGLE_PLACES_API_KEY", "ANTHROPIC_API_KEY"):
        if _key in st.secrets:
            os.environ.setdefault(_key, str(st.secrets[_key]))
except Exception:
    pass

from database import (
    STATUS_OPTIONS,
    get_all_leads_for_display,
    init_db,
    save_leads,
    update_lead,
)
from scraper import (
    ANTHROPIC_API_KEY,
    API_KEY as GOOGLE_API_KEY,
    DEFAULT_MAX_RESULTS,
    build_workbook,
    get_headers,
    run_pipeline,
    slugify,
)


st.set_page_config(
    page_title="Lead Scraper",
    page_icon="🎯",
    layout="wide",
)

# Make sure the SQLite file and table exist before anything else runs.
init_db()

st.title("Lead Scraper")

# Bail early if the core API key is missing.
if not GOOGLE_API_KEY:
    st.error(
        "GOOGLE_PLACES_API_KEY is missing. Add it to the `.env` file in this "
        "folder and restart the app."
    )
    st.stop()


# The columns we show in the My Leads view, in order.
MY_LEADS_COLUMNS = [
    "Status",
    "Notes",
    "Score",
    "Business Name",
    "Address",
    "Phone",
    "Website",
    "Rating",
    "Number of Reviews",
    "Categories",
    "Reasoning",
    "Flags",
    "Emails (Generic)",
    "Emails (Personal)",
    "Search Query",
    "Created",
    "Updated",
]

# Columns the user can actually edit in My Leads.
EDITABLE_DISPLAY_COLUMNS = {"Status", "Notes"}
# Maps display column names to the database column names update_lead expects.
DISPLAY_TO_DB = {"Status": "status", "Notes": "notes"}


tab_search, tab_leads = st.tabs(["🔎 Search", "📋 My Leads"])


# ===========================================================================
# Search tab
# ===========================================================================
with tab_search:
    st.caption(
        "Find local businesses, qualify them with AI, and save the best ones "
        "to your lead database."
    )

    with st.form("search_form"):
        query = st.text_input(
            "What kind of businesses are you searching for?",
            placeholder="e.g., dental offices in Milwaukee, Wisconsin",
        )

        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            max_results = st.number_input(
                "Max results",
                min_value=1, max_value=60, value=DEFAULT_MAX_RESULTS,
                help="Google returns up to 20 per page; we paginate up to 60.",
            )
        with col2:
            qualify_disabled = not ANTHROPIC_API_KEY
            include_qualification = st.checkbox(
                "AI qualification",
                value=not qualify_disabled,
                disabled=qualify_disabled,
                help=(
                    "Score each lead 1-10 with reasoning, sorted high to low. "
                    "Requires ANTHROPIC_API_KEY in .env."
                    if qualify_disabled
                    else "Score each lead 1-10 with reasoning, sorted high to low."
                ),
            )
        with col3:
            include_enrichment = st.checkbox(
                "Email enrichment",
                value=True,
                help="Scrape each business's website for contact emails.",
            )

        submitted = st.form_submit_button("Run", type="primary")

    # -- Run the pipeline ----------------------------------------------------

    if submitted:
        if not query.strip():
            st.error("Please enter a search query.")
        else:
            with st.status("Running...", expanded=True) as status:
                def log(msg):
                    st.write(msg)

                try:
                    rows = run_pipeline(
                        query=query.strip(),
                        max_results=int(max_results),
                        include_qualification=include_qualification,
                        include_enrichment=include_enrichment,
                        log=log,
                    )
                except Exception as e:
                    status.update(label=f"Error: {e}", state="error")
                    st.exception(e)
                    rows = []
                else:
                    if rows:
                        status.update(
                            label=f"Done — {len(rows)} leads found.",
                            state="complete",
                        )
                    else:
                        status.update(
                            label="No businesses found. Try a different query.",
                            state="error",
                        )

            if rows:
                st.session_state["rows"] = rows
                st.session_state["query"] = query.strip()
                st.session_state["include_qualification"] = include_qualification
                st.session_state["include_enrichment"] = include_enrichment
                # Reset the "saved" indicator so the user can save this new batch
                # and so stale badges don't show up on a fresh search.
                st.session_state.pop("saved_result", None)

    # -- Display results -----------------------------------------------------

    if "rows" in st.session_state:
        rows = st.session_state["rows"]
        saved_query = st.session_state["query"]
        iq = st.session_state["include_qualification"]
        ie = st.session_state["include_enrichment"]

        st.subheader(f"Results — {len(rows)} leads for: {saved_query}")

        # Order columns to match the spreadsheet (Score first, etc.).
        headers = get_headers(include_qualification=iq, include_enrichment=ie)
        df = pd.DataFrame(rows)
        df = df[[h for h in headers if h in df.columns]]

        # If the user just saved, mark which rows were new vs updated.
        saved_result = st.session_state.get("saved_result")
        if saved_result:
            new_ids = saved_result["new_place_ids"]
            df.insert(
                0,
                "Just saved",
                ["🆕 New" if r.get("place_id") in new_ids else "✓ Updated"
                 for r in rows],
            )

        st.dataframe(df, use_container_width=True, hide_index=True)

        # -- Action buttons --------------------------------------------------

        action_col1, action_col2, _ = st.columns([1, 1, 4])

        with action_col1:
            wb = build_workbook(rows, include_qualification=iq, include_enrichment=ie)
            buf = BytesIO()
            wb.save(buf)
            buf.seek(0)
            filename = (
                f"{slugify(saved_query)}_"
                f"{datetime.now().strftime('%Y-%m-%d')}.xlsx"
            )
            st.download_button(
                label="⬇️ Download as Excel",
                data=buf,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with action_col2:
            if st.button("💾 Save to database", type="primary"):
                new_count, updated_count, new_place_ids = save_leads(
                    rows, saved_query
                )
                new_set = set(new_place_ids)
                new_names = [
                    r.get("Business Name", "(unnamed)")
                    for r in rows if r.get("place_id") in new_set
                ]
                st.session_state["saved_result"] = {
                    "new_count": new_count,
                    "updated_count": updated_count,
                    "new_place_ids": new_set,
                    "new_names": new_names,
                }
                st.rerun()

        if "saved_result" in st.session_state:
            r = st.session_state["saved_result"]
            total = r["new_count"] + r["updated_count"]
            base = (
                f"Saved {total} leads — **{r['new_count']} new**, "
                f"{r['updated_count']} updated."
            )
            if r["new_names"]:
                shown = r["new_names"][:5]
                names_str = ", ".join(f"**{n}**" for n in shown)
                more = len(r["new_names"]) - len(shown)
                if more > 0:
                    names_str += f", and {more} more"
                base += f"  \n🆕 New: {names_str}"
            st.success(base)


# ===========================================================================
# My Leads tab
# ===========================================================================
def _save_my_leads_edits():
    """Callback: persist any edits the user made in the data_editor."""
    editor_state = st.session_state.get("my_leads_editor", {})
    edited_rows = editor_state.get("edited_rows", {}) or {}
    if not edited_rows:
        return
    visible = st.session_state.get("_visible_leads", [])
    for row_idx, changes in edited_rows.items():
        row_idx = int(row_idx)
        if row_idx >= len(visible):
            continue
        lead_id = visible[row_idx].get("ID")
        if lead_id is None:
            continue
        db_fields = {
            DISPLAY_TO_DB[col]: val
            for col, val in changes.items()
            if col in DISPLAY_TO_DB
        }
        if db_fields:
            update_lead(lead_id, **db_fields)


with tab_leads:
    leads = get_all_leads_for_display()

    if not leads:
        st.info(
            "No leads saved yet. Run a search in the **Search** tab and click "
            "**Save to database** to start building your list."
        )
    else:
        st.subheader(f"📋 {len(leads)} leads in your database")

        # -- Filter --------------------------------------------------------
        filter_status = st.multiselect(
            "Filter by status",
            options=STATUS_OPTIONS,
            placeholder="Show all statuses",
        )

        if filter_status:
            visible_leads = [l for l in leads if l.get("Status") in filter_status]
        else:
            visible_leads = leads

        # Stash for the callback to look up lead IDs by row index.
        st.session_state["_visible_leads"] = visible_leads

        if not visible_leads:
            st.info("No leads match the selected filter(s).")
        else:
            df = pd.DataFrame(visible_leads)
            df = df[[c for c in MY_LEADS_COLUMNS if c in df.columns]]

            disabled_cols = [
                c for c in df.columns if c not in EDITABLE_DISPLAY_COLUMNS
            ]

            st.caption(
                "Click a **Status** cell to move a lead through your pipeline, "
                "or a **Notes** cell to leave yourself a reminder. "
                "Changes save automatically."
            )

            st.data_editor(
                df,
                column_config={
                    "Status": st.column_config.SelectboxColumn(
                        "Status",
                        options=STATUS_OPTIONS,
                        required=True,
                    ),
                    "Notes": st.column_config.TextColumn(
                        "Notes",
                        max_chars=500,
                    ),
                },
                disabled=disabled_cols,
                hide_index=True,
                use_container_width=True,
                key="my_leads_editor",
                on_change=_save_my_leads_edits,
            )
