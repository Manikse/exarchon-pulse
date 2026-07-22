<div align="center">
  <a href="https://github.com/Manikse/exarchon-pulse">
    <img src="docs/logo.png" alt="EXARCHON PULSE Logo" width="180">
  </a>

  <h1>EXARCHON-PULSE ENGINE</h1>

  <p>
    <b>The Autonomous Engineering, Analytics & Bootstrapping Sub-system for EXARCHON.</b><br>
    Quantifying developer activity, dynamic roadmap orchestration, and automated institutional reporting.
  </p>
</div>

---

<p align="center">
  <img src="https://img.shields.io/badge/version-v0.1.0--alpha-blue">
  <img src="https://img.shields.io/badge/status-bootstrapping-orange">
  <img src="https://img.shields.io/badge/license-MIT-green">
  <img src="https://img.shields.io/badge/ecosystem-Exarchon-purple">
</p>

---

## Vision & Role

EXARCHON-PULSE Engine є суверенним автономним вузлом в екосистемі EXARCHON.

Його головна мета — самокомпіляція (bootstrapping): модуль взяв на себе ментальне навантаження з операційного менеджменту, моніторингу активності, коригування планів та зовнішньої звітності як під час розробки самого себе, так і для інших модулів екосистеми.

> Ecosystem Context: Pulse Engine не замінює Ядро Exarchon (exarchon-core). Він є автономним супутником, розробленим з ізольованими інтерфейсами (Core Connectors). У майбутньому, коли центральний робочий простір на базі Ядра Exarchon буде розгорнуто, воно перехопить пряме управління цим вузлом.

---

## Core Sub-systems

Модуль функціонально розділений на два взаємопов'язані контури:<br>

[ Git Commits / Workspace Notes / Ideas ]<br>
                   │<br>
                   ▼<br>
┌─────────────────────────────────────────────────────┐<br>
│               Activity Tracker Daemon               │<br>
└──────────┬───────────────────────────────┬──────────┘<br>
           │                               │<br>
           ▼                               ▼<br>
┌───────────────────────────┐   ┌───────────────────────────┐<br>
│ Executive Reporter        │   │ Dynamic Planner           │<br>
│ - Activity 24/7 & Drafts  │   │ - Roadmap & Decision Q    │<br>
└──────────┬────────────────┘   └──────────┬────────────────┘<br>
           │                               │<br>
           └───────────────┬───────────────┘<br>
                           ▼<br>
              [ Telegram / CLI Approval ]<br>

### 1. Exarchon-Executive Reporter
Автономна система спостереження та звітності 24/7:
* Activity Tracker Daemon: Фоновий процес, який моніторить Git commit logs, оновлення у робочих директоріях та локальні Markdown-нотатки.
* Grant & Institutional Reporter: Автоматичне агрегування даних у періодичні Executive Summaries та Changelog для грантових подач (Thiel Fellowship, 1517 Fund, USF, Brave1 тощо).
* Build-in-Public Generator: Автономна підготовка чернеток постів для X (Twitter) / Telegram про хід розробки з механікою 1-Click Approve перед публікацією.

### 2. Exarchon-Dynamic Planner
Персональний адаптивний помічник і стратегічний навігатор:
* Dynamic Roadmap Engine: Аналізує фактичний прогрес коду та нотатки, автоматично перебудовуючи вектор розробки без ручних правок.
* Adaptive Scheduler: Гнучкий графік, що адаптується під поточну продуктивність та пріоритети.
* Decision Queue: Видає лише 1–3 найважливіші стратегічні питання/блокери на день (наприклад, вибір архітектурного паттерну чи БД). Ви ухвалюєте рішення в 1 клік — система рухається далі.

---

## Privacy & Security (Private Core)

Усі неопубліковані ідеї, архітектурні чорнетки, локальні нотатки та файли стану є суворо приватними. Обробка та аналіз даних відбуваються локально або через приватні ізольовані ендпоінти.

---

## Project Structure

exarchon-pulse/<br>
├── config/<br>
│   ├── config.yaml          # Системна конфігурація та джерела<br>
│   └── roadmap.yaml         # Динамічна структура роадмапу<br>
├── data/                    # Локальний приватний шар стану (SQLite)<br>
├── src/<br>
│   ├── core/                # Bus & Exarchon Core Connectors<br>
│   ├── tracker/             # Git & File Watcher Daemons<br>
│   ├── reporter/            # Grant Reporter & Build-in-Public Generators<br>
│   ├── planner/             # Dynamic Roadmap & Decision Queue<br>
│   └── interface/           # Telegram Bot / CLI Interfaces<br>
├── main.py                  # Точка входу (Daemon + Telegram Bot)<br>
└── requirements.txt<br>

---

## Quick Start

### 1. Clone & Setup
git clone https://github.com/Manikse/exarchon-pulse.git
cd exarchon-pulse
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

### 2. Environment Configuration
Створіть файл .env на основі .env.template:
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_CHAT_ID="your_chat_id"
REPO_PATH="."

### 3. Run the Engine
python main.py

---

## Ecosystem Roadmap

- [x] Phase 1: Foundation & Bootstrapping - Git Activity Tracker, Decision Queue Telegram Interface, YAML/DB state engine.
- [ ] Phase 2: Analytics & Grant Pipelines - Automated Markdown parsing and Executive Summary generation for funders.
- [ ] Phase 3: Dynamic Scheduler Engine - Adaptive daily task redistribution based on velocity metrics.
- [ ] Phase 4: Exarchon Core Integration - Attaching Core Connectors and handing over execution control to the main Exarchon Kernel workspace.

---

## Author & Ecosystem

Created by Manikse — Building autonomous execution infrastructure for the next era of AI.


<div align="center"> 
  <a href="https://ko-fi.com/manikse"> 
    <img src="https://storage.ko-fi.com/cdn/kofi3.png?v=3" width="200"/> 
  </a> 
</div>