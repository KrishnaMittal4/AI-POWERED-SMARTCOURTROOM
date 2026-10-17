# LEXAI Consolidated Master Build

This build consolidates the latest production/local features into one codebase.

Key production behavior:
- Public landing page with authentication gate for private actions.
- Upload & Research user-owned PDFs; no 848-judgment research corpus required in production.
- Private FAISS + BM25 retrieval and Private Evidence Verification.
- Uploaded judgments/orders are conservatively detected and routed through Judgment Citation Verification while remaining private uploads.
- Background Case Intelligence jobs with structured-field normalization and strict completeness validation. Empty summary/Timeline/Evidence/Legal Issues cannot be saved as a successful analysis.
- Render/Supabase production mode and local VS Code mode remain separate through environment flags.

Production keeps `GLOBAL_JUDGMENT_CORPUS_ENABLED=false`; local research may enable it explicitly.
