"""Virtual Metals Trading Desk: read-only dashboard over the pipeline's published outputs.

    .venv/bin/streamlit run app/streamlit_app.py

The entrypoint only sets the page config, builds the navigation from `components.PAGES` and draws the sidebar footer
(SIM label, Excel reconciliation status, commit). Each page under app/views/ also runs on its own, so no page depends
on anything set here. See docs/80_frontend.md.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.lib import components  # noqa: E402

st.set_page_config(page_title="Virtual Metals Trading Desk", page_icon=":material/stacked_line_chart:",
                   layout="wide", initial_sidebar_state="auto")

page = st.navigation(components.navigation_pages(), position="sidebar", expanded=True)
components.sidebar_footer()
page.run()
