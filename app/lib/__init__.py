"""Shared layer of the read-only Streamlit dashboard (docs/80_frontend.md).

    data        cached, typed loaders over the pipeline's published files; a missing file returns None
    docs_text   markdown sections pulled from docs/*.md (links rewritten for the app)
    components  the SIM banner, the P&L headline with its band, captions, flags, downloads, page header, navigation
    charts      Plotly helpers with one palette, window shading, event markers and a SIM watermark

The dashboard never runs a pipeline stage, never writes a file and never touches the network. Pages import this
package after putting the repository root on sys.path (see the three-line bootstrap at the top of every page).
"""
