# 🏠 Residental Report Bot

Telegram bot for receiving and managing **citizen complaints** (water, electricity, roads, noise, etc.).  
Built with **Aiogram 3** and SQLite. Lightweight, easy to run, and ready to deploy.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## ✨ Features

- ✅ Users can submit complaints with:
  - Category, address, free-text description
  - Photos / videos / documents
  - GPS location (mobile) or coordinates/link (desktop fallback)
- ✅ Complaints are posted to a Telegram **group/supergroup**
  - Inline buttons for moderators: **Принять**, **Отказаться**, **Готово**
  - Status is edited live in the group message
- ✅ Author receives DM notifications when status changes
- ✅ Simple SQLite storage (`complaints.db`) with incremental request IDs (#1, #2, ...)
- ✅ Easy to self-host and extend

---

## Quick start (Windows PowerShell)

1. Clone the repo:
```powershell
git clone https://github.com/IkhTee/residental_report_BoT.git
cd residental_report_BoT
2. Create & activate virtual environment:
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # PowerShell
# or .\.venv\Scripts\activate    # cmd.exe
Install dependencies:

pip install -r requirements.txt
