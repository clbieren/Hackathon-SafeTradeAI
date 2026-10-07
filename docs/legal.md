# Legal and Compliance Note

## Overview

SafeTrade AI is designed for business intelligence and due-diligence workflows using publicly accessible data sources. This document outlines the legal and ethical framework for data collection and processing.

## Public Data Sources

The platform aggregates data from:

- **Şikayetvar.com** - Public complaint and review platform
  - Status: Public access, review terms of service for programmatic access
  - Robots.txt must be respected
  
- **EKAP (Eczacı Kimlik Authentication Platform)** - Turkish pharmacist registry
  - Status: Public government registry
  - Accessible per Turkish official data policies
  
- **MERSİS (Turkish Business Registry)** - Company registration database
  - Status: Public government official data
  - Accessible per Turkish official data policies
  
- **News & Media Sources** - Public news aggregation
  - Status: Public content, standard journalism attribution applies
  
- **Google Maps & Places** - Business location and review data
  - Status: Public API access, terms of service apply

## Scraping and Access Policy

All data collection respects:

1. **robots.txt** - We honor exclusion rules set by source owners
2. **Rate Limiting** - Requests are throttled to avoid server strain
3. **Terms of Service** - No ToS violations; commercial use is reviewed per source
4. **User-Agent Declaration** - Clearly identifies the requester
5. **Data Minimization** - Only essential business information is collected

## Privacy and Personal Data (KVKK)

- Personal names, email addresses, and phone numbers are **not collected or stored** unless explicitly required for business identification
- Company information (registration, ratings, compliance) is treated as business data, not personal data
- No profiling or mass personal data processing occurs
- Processing aligns with KVKK Article 5-8 principles (lawfulness, minimization, accuracy)

## Output and Accountability

Every report output includes:

- **Source identification** - Which sources contributed to findings
- **Collection timestamp** - When data was gathered
- **Confidence level** - How certain the findings are
- **Human review status** - Whether results have been manually verified
- **Audit trail** - Traceable back to original sources

This ensures outputs are explainable and auditable, not black-box predictions.

## Limitations and Disclaimers

- **Not a legal substitute** - SafeTrade scores inform business decisions; they are not legal opinions
- **AI limitations** - LLM-synthesized analysis may contain errors; human review is essential
- **Source dependency** - Quality depends on accuracy of public sources
- **No guarantee of completeness** - Some information may be missing or outdated

## Compliance Responsibility

Organizations using this platform are responsible for:

- Ensuring their own data processing complies with local regulations
- Conducting legal review before making risk decisions based on SafeTrade output
- Respecting the intellectual property and terms of service of data sources
- Maintaining audit records of how SafeTrade findings inform business decisions

## Ongoing Review

This compliance framework is reviewed and updated as:
- Source policies change
- Legal requirements evolve
- New data sources are added
