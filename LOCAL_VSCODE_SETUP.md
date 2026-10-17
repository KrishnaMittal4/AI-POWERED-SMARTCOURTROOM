# LEXAI local VS Code mode

Local and deployment settings are intentionally separate.

## First run
1. Open this folder in VS Code.
2. Run `python -m venv .venv` and select `.venv` with **Python: Select Interpreter**.
3. Run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
4. Copy `.env.development.example` to `.env` and add your own Groq/Gemini keys.
5. Terminal 1: `.\run-local.ps1`
6. Terminal 2: `.\run-frontend.ps1`

The local launcher forces local storage, full-memory mode, Global RAG enabled and developer tools enabled even if deployment examples exist in the repository.

## Global 848-judgment research corpus
The deployment-clean ZIP intentionally does not bundle research judgments/indexes. To use Global Judgment RAG locally, restore your own research corpus/index folders into the locations expected by `rag_pipeline.py`, or rebuild the index. Private Case RAG works without them.

## Production
Do not copy `.env` to Render. Configure Render Environment variables from `.env.production.example`. Production uses Supabase, disables the research corpus/RAG Lab, and enables Render Free low-memory mode.
