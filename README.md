# SafeTrade AI

AI-assisted business risk and reputation intelligence platform for evaluating commercial counterparties using public and regulated data sources. The system resolves a company identity, collects source evidence, and presents findings with traceable references rather than unsupported claims.

Türkçe özet: SafeTrade AI, ticari ortaklıkların güvenilirliğini kamuya açık ve düzenlenmiş kaynaklardan toplanan verilerle değerlendiren bir risk istihbarat platformudur. Sistem şirket kimlik çözümlemesi yapar, kanıtları bir araya toplar ve sonuçları destekleyen kaynak referanslarıyla açık ve izlenebilir biçimde sunar.

## What this project does

SafeTrade AI is designed to help answer a practical business question: "Can we trust this company or counterparty?" It combines company identity resolution, public-source collection, and AI-assisted synthesis to provide a structured risk overview grounded in evidence.

The platform is intended for operational due-diligence workflows where outputs must be explainable, human-reviewable, and tied to source material.

## Core capabilities

- Company identity resolution and matching
- Public-source collection for business and reputation signals
- AI-assisted synthesis of risk signals into a structured summary
- Source-linked evidence workflow for human verification
- Streaming status updates during analysis

## Architecture

The solution is organized around a FastAPI backend, a lightweight frontend, and a data pipeline that gathers signals from multiple sources before synthesizing findings.

## Repository structure

- backend/ — FastAPI application and business logic
- frontend/ — UI assets and browser interfaces
- tests/ — automated validation suite
- scripts/ — dev and utility scripts
- docs/ — architecture and legal documents

## Technology stack

- Backend: Python, FastAPI, SQLAlchemy, PostgreSQL
- Frontend: HTML, JavaScript, CSS
- AI layer: Google Gemini API
- Data collection: async scraping and public-source enrichment
- Infrastructure: Docker, GitHub Actions

## Source-aware approach

This project does not claim that AI outputs are infallible. Instead, the design goal is to make the result auditable: every significant conclusion should be traceable to a source or a set of supporting documents, and the final report should be reviewed by a human before used as a decision basis.

## Legal and compliance note

Public-data collection must be handled carefully. The project is designed for informational due-diligence workflows and should only use sources that are legally accessible and compliant with applicable terms, privacy obligations, and local data-protection rules. A dedicated legal note is included in `docs/legal.md`.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest tests -q
```

## CI

This repository includes a GitHub Actions workflow to run the Python test suite automatically on push and pull requests.

## Notes

The project is intentionally framed as a source-linked intelligence workflow, not as a system that guarantees zero hallucination in all circumstances. Responsible AI usage here means auditable evidence, clear limitations, and human oversight.
