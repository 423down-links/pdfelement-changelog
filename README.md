# PDFelement Changelog

Complete version history and update notes for Wondershare PDFelement.

## Features

- **Latest version** from official API (`pc-api.wondershare.cc/v2/product/check-upgrade`)
- **Historical versions** from official whats-new page, dating back to v7.0.0
- Sidebar version navigation grouped by year
- Download links, MD5, and file size for the latest version
- All content in English
- GitHub Actions auto-updates daily

## Access

https://423down.github.io/pdfelement-changelog/

## API Details

- Endpoint: `https://pc-api.wondershare.cc/v2/product/check-upgrade`
- Parameters: `pid` (product ID), `client_sign={}` (empty braces work), `version`, `platform=win_x86`
- English version PID: 5239

## Files

- `index.html` - Main page with embedded data
- `data.json` - Version history data (latest + historical)
- `generate_data.py` - Generates data.json (latest from API + history from official page)
- `embed_data.py` - Embeds data.json into index.html
- `.github/workflows/update.yml` - Daily auto-update workflow

## Version Coverage

- **13.x**: 13.0.3 (latest)
- **12.x**: 12.0.0
- **11.x**: 11.4.25, 11.4.23, 11.4.22, 11.4.20, 11.4.17, 11.3.0, 11.1.0, 11.0.0
- **10.x**: 10.0.0
- **9.x**: 9.5.0, 9.0.0
- **8.x**: 8.0.0
- **7.x**: 7.0.0
