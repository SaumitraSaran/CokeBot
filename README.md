<p align="center">
  <img src="static/assets/Cokebot%20AI%20Logo.png" alt="Cokebot AI logo" />
</p>

> A finance-focused conversational analytics assistant for exploring customer transaction data with natural-language questions.

Cokebot AI combines a Flask web application, MySQL transaction data, deterministic intent recognition, and Google Gemini-powered query generation. It is designed for finance and business users who need fast answers, transparent results, lightweight visualizations, and exportable insights without writing SQL.

[**Try the live demo**](https://983e3bd9.cokebot.pages.dev/)

## Contents

- [Highlights](#highlights)
- [Architecture](#architecture)
- [Request lifecycle](#request-lifecycle)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Database requirements](#database-requirements)
- [Local development](#local-development)
- [Production deployment](#production-deployment)
- [HTTP API](#http-api)
- [SQL safety model](#sql-safety-model)
- [Performance and reliability](#performance-and-reliability)
- [Troubleshooting](#troubleshooting)
- [Limitations and next steps](#limitations-and-next-steps)
- [License](#license)

## Highlights

### Conversational finance analytics

- Ask questions about transactions, customers, payments, trends, rankings, and reporting amounts.
- Supports follow-up context from the most recent conversation messages.
- Handles greetings, unsupported topics, unsupported metrics, and ambiguous questions explicitly.
- Uses a finance-specific prompt and schema contract to keep answers within the transaction dataset.

### Deterministic-first query generation

1. The application checks for greetings and obviously out-of-scope questions.
2. It attempts to match the question to a locally recognized intent.
3. Approved SQL templates are loaded from the `frequent_queries` registry and rendered with validated parameters.
4. If no local intent matches, Gemini generates a structured query request.
5. The generated SQL is validated before it can reach MySQL.
6. Results are summarized by Gemini and returned with metadata, trust indicators, insights, and an explanation of the calculation.

### Executive-friendly interface

- Command Center cards for current dataset metrics.
- Result tables and compact charts.
- CSV export.
- Downloadable Cokebot AI CFO briefs.
- “What-if” display-only scenarios that do not modify source data.
- Root-cause investigation by payment mode.
- Saved threshold monitors.
- Correct/incorrect feedback capture for query intents.
- Glossary support for common financial terms.

### Static frontend demo

The files in `static/` can be hosted on Cloudflare Pages or another static host without
running Flask, MySQL, or Gemini. On non-local hosts the frontend automatically uses a
small, clearly labelled demo fixture dataset for the Command Center and common questions.
The demo keeps the interactive experience enabled, including SQL inspection, calculation
explanations, charts, CSV export, What-if scenarios, CFO brief downloads, root-cause
investigation, and saved monitor feedback.

For local development, `localhost` and `127.0.0.1` continue to use the live Flask API.
Use `?demo=1` to force the static fixtures or `?demo=0` to force API mode on another host.

When a user asks an unsupported custom question while the frontend is in demo mode,
the UI explains that this is a demo of the official Cokebot and links to the full
repository: https://github.com/SaumitraSaran/CokeBot

## Architecture

```text
Browser
  │
  │ HTML / CSS / JavaScript
  ▼
Flask application (app.py)
  ├── Guardrails and scope checks
  ├── Local intent recognition
  ├── Approved intent-template lookup
  ├── Gemini query generation and result summarization
  ├── SQL safety validation
  ├── Short-lived in-process response caches
  └── Command Center, feedback, monitor, and audit routes
       │                         │
       ▼                         ▼
  MySQL connection pool      Google Gemini API
       │
       ▼
  customer_transactions
  frequent_queries
  ai_query_audit
  ai_saved_monitors
```

### Core components

| Component | Responsibility |
| --- | --- |
| `app.py` | Flask application, routes, request validation, orchestration, response shaping, and caching |
| `brain.py` | Gemini client integration for SQL generation, result summarization, and administrative query assistance |
| `finance_prompt.py` | Finance schema, SQL-generation rules, response contract, and scope restrictions |
| `guardrails.py` | Greeting handling, out-of-scope responses, and forbidden-query definitions |
| `local_intent.py` | Deterministic recognition of supported question patterns |
| `query_cache.py` | Approved intent-template lookup, parameter rendering, and feedback statistics |
| `sql_validator.py` | SELECT-only validation, statement restrictions, table restrictions, and year limits |
| `mysql_dispatcher.py` | MySQL connection pooling, bounded result fetching, and value serialization |
| `finance_features.py` | Glossary, local plans, calculation explanations, and normalized finance terms |
| `insights.py` | Structured insight generation and scope detection |
| `operations.py` | Audit events and saved monitor persistence |
| `static/` | Browser UI assets |
| `wsgi.py` | Production WSGI entry point for Gunicorn |

## Request lifecycle

```text
POST /api/ask
      │
      ├─ Validate request
      ├─ Greeting / scope / year checks
      ├─ 120-second in-process cache lookup
      ├─ Local intent recognition
      │     └─ Approved SQL template, when matched
      ├─ Gemini SQL generation, when no local match exists
      ├─ Parse structured response
      ├─ Validate SQL
      ├─ Execute bounded MySQL query
      ├─ Build insight and calculation explanation
      ├─ Gemini result summarization
      ├─ Write audit event
      └─ Return JSON to the browser
```

## Repository layout

```text
FInanceChatbot/
├── app.py
├── brain.py
├── db_optimizations.py
├── finance_features.py
├── finance_prompt.py
├── guardrails.py
├── insights.py
├── local_intent.py
├── mysql_dispatcher.py
├── operations.py
├── query_cache.py
├── sql_validator.py
├── wsgi.py
├── requirements.txt
├── .env                         # local secrets; do not commit
├── static/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── assets/
└── backups/                     # local data and conversion artifacts
```

## Prerequisites

- Python 3.10 or newer
- MySQL 8.x or a compatible MySQL server
- A Google Gemini API key with access to the configured model
- A database containing the required transaction table and supporting operational tables
- A modern browser with JavaScript enabled

## Configuration

Create a local `.env` file in this directory. Never commit real credentials.

```dotenv
GEMINI_API_KEY=replace-with-your-gemini-api-key

DB_HOST=127.0.0.1
DB_USER=app_user
DB_PASSWORD=replace-with-a-strong-password
DB_NAME=your_database_name
```

The application also has development fallbacks for database values. For any shared, staging, or production environment, set every `DB_*` variable explicitly rather than relying on defaults.

### Secret-handling checklist

- Add `.env` to `.gitignore`.
- Rotate any API key or password that has been exposed in a local file, terminal output, log, screenshot, or repository history.
- Use a secret manager or deployment-platform secret store outside local development.
- Do not place credentials in README files, frontend assets, SQL templates, or client-side requests.

## Database requirements

### Primary data table

The finance prompts and built-in analytics expect a table named `customer_transactions`. The active schema is defined in `finance_prompt.py`; keep that schema description synchronized with the actual MySQL table.

The application uses fields including:

- `trans_date`
- `amount_cur`
- `reporting_currency_amount`
- `customer_name`
- `customer_party`
- `payment_mode`
- Account, company, invoice, voucher, currency, and posting-profile dimensions

### Supporting tables

The following tables are used by operational and feedback features:

| Table | Used by |
| --- | --- |
| `frequent_queries` | Approved SQL intent templates and feedback statistics |
| `ai_query_audit` | Query and event audit records |
| `ai_saved_monitors` | Saved threshold monitors |

The application does not create these tables automatically. Provision them through your normal database migration process before enabling the corresponding features.

## Local development

From the parent directory:

```bash
cd FInanceChatbot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

The development server listens on:

```text
http://127.0.0.1:5002
```

The root route serves the browser application:

```text
GET /
```

### Windows activation

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

### Smoke test

```bash
curl -i http://127.0.0.1:5002/
```

With the server and database configured, test a question:

```bash
curl -s http://127.0.0.1:5002/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Show the top 5 customers by transaction value"}'
```

## Production deployment

`wsgi.py` exposes the Flask application as `wsgi:app`. A representative Gunicorn command is:

```bash
gunicorn --workers 2 --threads 4 --bind 0.0.0.0:5002 wsgi:app
```

Before production use:

1. Configure secrets through the platform secret manager.
2. Use a dedicated least-privilege MySQL user.
3. Restrict CORS to known frontend origins instead of allowing broad cross-origin access.
4. Put the service behind TLS and an authenticated reverse proxy or identity layer.
5. Configure structured application logging and log redaction.
6. Add health checks, process supervision, and database connectivity monitoring.
7. Replace the in-process cache with a shared cache if running multiple workers or instances.
8. Apply database migrations for all supporting tables.
9. Review the SQL validator and finance schema whenever the data model changes.

## HTTP API

All JSON request bodies should use `Content-Type: application/json`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/` | Serve the web application |
| `POST` | `/api/ask` | Generate and execute a finance query, then return the answer and data |
| `POST` | `/api/answer` | Summarize a supplied database result for a user question |
| `POST` | `/api/report` | Record correct/incorrect feedback for an intent |
| `POST` | `/api/feedback` | Alias of `/api/report` |
| `GET` | `/api/stats` | Return feedback statistics for an intent |
| `GET` | `/api/glossary` | Return supported finance glossary terms |
| `GET` | `/api/monitors` | List saved monitors for an actor |
| `POST` | `/api/monitors` | Save a reporting amount or transaction-count threshold monitor |
| `GET` | `/api/command-center` | Return verified home-screen metric cards |
| `POST` | `/api/investigate` | Return deterministic payment-mode month-over-month drivers |

### `POST /api/ask`

Request:

```json
{
  "question": "What was the total reporting amount last month?",
  "context": [
    {
      "role": "user",
      "content": "Show the last six months"
    },
    {
      "role": "assistant",
      "content": "Here is the six-month trend."
    }
  ],
  "actor": "finance-user"
}
```

Successful responses can include:

```json
{
  "answer": "…",
  "sql": "SELECT …",
  "data": {
    "columns": ["…"],
    "rows": [["…"]],
    "truncated": false
  },
  "intent": "…",
  "query_type": "trend",
  "insight": {},
  "explanation": {},
  "trust": {
    "score": 82,
    "basis": "validated AI query",
    "freshness": "Latest available transaction date"
  },
  "meta": {
    "source": "AI analysis",
    "latency_ms": 0,
    "sql_latency_ms": 0,
    "data_through_year": 2026
  }
}
```

## SQL safety model

Before execution, generated SQL is checked to ensure that it:

- Is a single `SELECT` statement.
- Does not contain DML, DDL, DCL, transaction-control, or execution keywords.
- Does not contain multiple statements.
- References the permitted `customer_transactions` table.
- Does not access system schemas such as `INFORMATION_SCHEMA`, `MYSQL`, `SYS`, or `PERFORMANCE_SCHEMA`.
- Does not request years after the supported data boundary.
- Returns bounded result sets through the dispatcher.

This is a defense-in-depth control, not a substitute for database permissions, authentication, authorization, network isolation, or security testing.

## Performance and reliability

- MySQL connections are pooled with a pool size of five.
- Query results are capped at 500 displayed rows.
- The application uses short-lived in-process caches for repeated questions and summaries.
- Local intent matches avoid an LLM call for supported, frequently used questions.
- Decimal and date values are serialized before being returned as JSON.
- Database, audit, and monitor failures are surfaced through application responses or logs according to the route.
- The UI reports whether results came from a local intent template, AI analysis, or cache.

## Troubleshooting

### The app starts but answers fail

Check:

```bash
python -c "import mysql.connector; print('mysql connector available')"
```

Then verify `DB_HOST`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME`, and confirm that the MySQL user can read `customer_transactions`.

### Gemini requests fail

- Confirm `GEMINI_API_KEY` is present in the process environment.
- Confirm the configured Gemini model is available to the API key.
- Check server logs for the upstream error.
- Do not print or paste the API key while diagnosing the issue.

### A question is rejected

The request may be:

- Outside the finance dataset scope.
- Asking for a year beyond the supported data boundary.
- Using a metric not represented by the active schema.
- Ambiguous enough to require clarification.
- Generating SQL that fails validation.

### Command Center or monitors return errors

Confirm that `customer_transactions` and `ai_saved_monitors` exist and that the database user has the required read/write privileges.

## Limitations and next steps

The current codebase is a strong application prototype and internal analytics service. For a hardened public or enterprise deployment, prioritize:

- Authentication and role-based authorization.
- Tenant isolation and actor identity from a trusted identity provider.
- Strict CORS configuration.
- CSRF protection where cookie-based authentication is introduced.
- Rate limiting and request-size limits at the edge.
- Centralized logs, metrics, traces, and alerting.
- Automated migrations and schema validation.
- Shared cache and durable job handling for horizontally scaled deployments.
- Automated unit, integration, API, and security tests.
- Formal data classification, retention, and audit policies.

## License

No license file is currently included. Add a license before publishing this project as an open-source repository. Until then, all rights remain with the copyright holder.
