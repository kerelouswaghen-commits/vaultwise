# Vaultwise - Family Budget Tracker

A data-driven family budget tracker powered by Claude AI, Prophet forecasting, and Telegram integration.

## Quick Start

### Run everything (app + Telegram bot) in one line:

```bash
cd "<your-project-directory>" && source .venv/bin/activate && launchctl load ~/Library/LaunchAgents/com.vaultwise.bot.plist 2>/dev/null; lsof -ti:8501 | xargs kill -9 2>/dev/null; sleep 1 && streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

### Stop everything:

```bash
lsof -ti:8501 | xargs kill -9 2>/dev/null; launchctl unload ~/Library/LaunchAgents/com.vaultwise.bot.plist 2>/dev/null
```

## Features

### Dashboard
- Monthly spending breakdown with color-coded category cards (red/yellow/green)
- Prophet time-series forecasts per category
- Top merchant impact analysis
- Claude-driven preventive action recommendations
- Cash flow projection chart

### Upload Statements
- Drag & drop Chase PDF statements (checking + credit card spending reports)
- Coverage heatmap showing data completeness per account per month
- Missing month alerts with specific upload guidance
- Auto-triggers analytics refresh after import

### Transactions
- Browse and filter all transactions
- Category analysis with treemap visualization
- **Recategorize with Claude** - AI-driven dynamic category structure
- Edit categories before applying, consistent across the entire app

### Financial Advisor
- Ask Claude questions about your finances
- Powered by your actual transaction data and analytics
- LaTeX-safe rendering

### Forecasts & Goals
- User-defined monthly savings target
- Prophet-based spending forecasts
- Scenario analysis: "What if I cut X category?"
- Savings progress tracking over time

### Reports & Telegram
- Weekly spending report with KEEP/STOP/START recommendations
- Send report summary to Telegram
- Two-way Telegram Q&A with Claude (ask follow-up questions)

### Settings
- Anthropic API key
- Telegram bot token and chat ID
- Monthly savings target
- All credentials auto-persist to `.env` file

## Architecture

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI and page routing |
| `analytics.py` | Time-series analysis, Prophet, trend scoring |
| `analytics_cache.py` | Pre-computed analytics stored in DB |
| `database.py` | SQLite database operations |
| `claude_advisor.py` | Claude API integration |
| `category_engine.py` | Dynamic category management |
| `pdf_parser.py` | Chase checking statement parser |
| `chase_report_parser.py` | Chase spending report parser (instant, no AI) |
| `csv_parser.py` | Capital One / Apple Card CSV parser |
| `telegram_listener.py` | Telegram bot for Q&A and reports |
| `spending_intelligence.py` | Spending velocity and alerts |
| `config.py` | Account definitions and category defaults |
| `prompts/` | Claude prompt templates |

## Accounts Supported

- Chase Freedom/Sapphire (credit card ending 4730)
- Chase credit card (ending 3072)
- Capital One (CSV import)
- Apple Card (CSV import)
- Chase Joint Checking (ending 3829)

## Requirements

- Python 3.13+
- Anthropic API key
- Telegram bot token (optional, for mobile reports)

## Environment Variables (`.env`)

```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

These are auto-saved when you enter them in Settings. They survive database resets.
