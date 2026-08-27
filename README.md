# AT Network Dashboard v2

AT Network Dashboard is a self-hosted monitoring application for ISP performance, WAN quality, Wi-Fi health, UniFi gateways/access points, UPS/NUT power monitoring, incidents, alerts, and evidence reporting.

## v2 goals

Version 2 is a clean rebuild of the working v1 application with a modular backend, one shared UI/theme system, web-first configuration, encrypted integration secrets, first-run setup, and a GitHub-safe source tree with no customer-specific addresses or credentials committed.

### Planned integrations

- UniFi Network
- NUT / NUTPI
- Discord notifications
- Generic Internet quality monitoring

### Core application areas

- Dashboard
- Incidents
- Wi-Fi
- Reports
- Settings
  - General
  - ISP & Monitoring
  - Integrations
  - Wi-Fi Alerts
  - Notifications
  - Network Changes
  - Security
  - System
  - About

## Development status

`2.0.0-dev1` — clean v2 foundation.

The existing v1.0.2 installation remains the behavioural reference while functionality is ported into v2.

## Security model

Do not commit `.env`, databases, reports, backups, API keys, webhooks, passwords, session secrets, or customer-specific configuration. Use `.env.example` as the deployment template.
