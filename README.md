# Entity Allocation - PE Multi-Entity Expense Allocation Tool

A CLI-based expense allocation tool for multi-entity private equity firms. Ingests raw expenses and allocates them across fund entities, management companies, and portfolio companies based on configurable allocation methodologies.

## Quick Start

```bash
# Setup
cd ceviche
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Initialize database and load sample data
python run.py init
python run.py seed
```

## Architecture

Entity Allocation manages expenses across PE firm legal entities:

- **GP (Management Company)** — Apex Capital Management LLC
- **Fund Entities** — Fund I ($200M), Fund II ($400M), Fund III ($600M)
- **Portfolio Companies** — Operating companies owned by the funds
- **SPVs** — Deal-specific co-invest vehicles

## Allocation Methodologies

| Method | Description | Use Case |
|--------|-------------|----------|
| `pro_rata_aum` | Proportional to AUM | Rent, technology, insurance |
| `pro_rata_committed` | Proportional to committed capital | Legal, accounting, compliance |
| `pro_rata_invested` | Proportional to invested capital | Deal-related shared costs |
| `direct` | 100% to one entity | Fund formation, travel |
| `headcount` | Proportional to FTE count | Personnel, payroll |
| `custom_split` | Manually defined percentages | Custom arrangements |
| `deal_specific` | 100% to deal/portfolio company | Due diligence, deal expenses |

## CLI Commands

### Entity Management
```bash
python run.py entities list
python run.py entities add --name "Fund IV" --type Fund --committed-capital 800000000
python run.py entities update 3 --aum 400000000
python run.py entities show 2
```

### Policy Management
```bash
python run.py policies list
python run.py policies add --name "New Policy" --method pro_rata_aum --categories "rent,technology"
python run.py policies add --name "Custom" --method custom_split --splits '{"2": 0.6, "3": 0.4}'
python run.py policies show 1
```

### Expense Management
```bash
python run.py expenses list --status pending --month 2025-01
python run.py expenses add --date 2025-01-15 --vendor "Kirkland & Ellis" --amount 150000 --category legal
python run.py expenses import --file expenses.csv
python run.py expenses categorize    # AI-assisted auto-categorization
```

### Allocation Engine
```bash
python run.py allocate --expense-id 1              # Single expense
python run.py allocate --month 2025-01              # All pending for month
python run.py allocate --preview --month 2025-01    # Dry run
python run.py allocate --recalculate --month 2025-01  # Re-run after metric updates
```

### Reporting
```bash
python run.py report summary --month 2025-01
python run.py report by-entity --entity "Apex Capital Partners III LP" --quarter Q1-2025
python run.py report by-category --category legal --year 2025
python run.py report variance --month 2025-02
python run.py report lpa-compliance --fund "Apex Capital Partners III LP"
python run.py report export --format csv --month 2025-01
python run.py report journal-entries --month 2025-01
```

### Override & Audit
```bash
python run.py override 5 --new-splits '{"2": 0.6, "3": 0.4}' --reason "Per IC approval"
python run.py audit-trail --expense-id 16
python run.py audit-trail --month 2025-01
```

### Natural Language Query
```bash
python run.py query "How much did we allocate to Fund II for legal expenses in Q1?"
```

## CSV Import Format

```csv
date,vendor,description,amount,currency,category,entity_paid,gl_account,notes
2025-01-15,Kirkland & Ellis,Formation docs,150000,USD,legal,,6100,Fund III
```

Supports: duplicate detection, multiple date formats, validation, error reporting.

## Journal Entry Export

Generates NetSuite/QuickBooks-compatible journal entries:
- CREDIT to paying entity (intercompany receivable)
- DEBIT to each receiving entity (expense account + intercompany payable)

## LPA Compliance

Configurable rules in `config.yaml`:
- Management fee cap (% of committed capital)
- Organizational expense cap
- Broken deal expense limits
- Annual total expense cap

## AI Features (requires ANTHROPIC_API_KEY)

- **Auto-categorization**: Vendor/description → expense category
- **Anomaly detection**: Flag unusually large expenses
- **Natural language queries**: Ask questions about allocations
- Falls back to heuristic matching when API key is not set

## Testing

```bash
python -m pytest tests/ -v
```

27 tests covering: all allocation methodologies, edge cases (rounding, liquidated entities, zero metrics), CSV import validation, duplicate detection, and LPA compliance checks.

## Configuration

All firm-specific settings live in `config.yaml`: entity structure, GL account mappings, LPA rules, and default policy mappings.

## Database

SQLite stored at `~/.ceviche/ceviche.db`. Tables: entities, allocation_policies, expenses, allocations, allocation_overrides.
