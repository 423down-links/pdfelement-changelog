#!/usr/bin/env python3
"""Generate PDFelement changelog data.
Fetches latest version from Wondershare API and merges with history.
If API fails, preserves existing data and exits successfully.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

DATA_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')

# PDFelement product config
PRODUCT_ID = "pdfelement"
BRAND = "wondershare"
API_URL = "https://pc-api.wondershare.cc/v5/product/check-upgrade"

# Fallback API endpoints
FALLBACK_APIS = [
    "https://pc-api.300624.com/v5/product/check-upgrade",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_latest_from_api():
    """Try to fetch latest version info from API. Returns dict or None."""
    # Try with a generic client_sign (may not work but worth trying)
    params = f"pid={PRODUCT_ID}&version=13.0.0.0&brand={BRAND}&client_sign=generic"
    urls = [f"{API_URL}?{params}"] + [f"{u}?{params}" for u in FALLBACK_APIS]

    for url in urls:
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'X-Client-Type': '1',
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('upgradeVersion') or data.get('new_version'):
                    return data
        except Exception as e:
            print(f"  API {url[:50]}... failed: {e}")
            continue
    return None


def parse_api_response(api_data):
    """Parse API response into version entry."""
    version = api_data.get('upgradeVersion') or api_data.get('new_version', '')
    if not version:
        return None

    title = api_data.get('whats_new_title', f'PDFelement {version}')
    content = api_data.get('whats_new_content', '')
    whats_new_list = api_data.get('whats_new_list', [])

    # Build sections from content or list
    sections = []
    if whats_new_list:
        for item in whats_new_list:
            if isinstance(item, str):
                sections.append({'title': 'Updates', 'items': [item]})
            elif isinstance(item, dict):
                sections.append({
                    'title': item.get('title', 'Updates'),
                    'items': item.get('items', [item.get('content', '')])
                })
    elif content:
        # Simple HTML parsing
        import re
        items = re.findall(r'<li[^>]*>(.*?)</li>', content, re.DOTALL)
        items = [re.sub(r'<[^>]+>', '', i).strip() for i in items if i.strip()]
        if items:
            sections.append({'title': 'Updates', 'items': items})

    entry = {
        'version': version,
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'title': title,
        'sections': sections,
        'download_url': api_data.get('full_url', ''),
        'md5': api_data.get('patch_md5', ''),
        'size': int(api_data.get('packageSize', 0) or 0),
        'size_mb': round(int(api_data.get('packageSize', 0) or 0) / 1024 / 1024, 1),
    }
    return entry


def main():
    print("Generating PDFelement changelog data...")

    # Load existing data
    with open(DATA_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    versions = data.get('versions', [])
    print(f"  Existing versions: {len(versions)}")

    # Try fetch latest from API
    print("  Fetching latest from API...")
    api_data = fetch_latest_from_api()

    if api_data:
        new_entry = parse_api_response(api_data)
        if new_entry:
            # Check if version already exists
            existing_versions = [v['version'] for v in versions]
            if new_entry['version'] not in existing_versions:
                versions.insert(0, new_entry)
                data['latest_version'] = new_entry['version']
                print(f"  New version added: {new_entry['version']}")
            else:
                print(f"  Version {new_entry['version']} already exists, updating info")
                for i, v in enumerate(versions):
                    if v['version'] == new_entry['version']:
                        if new_entry.get('download_url'):
                            versions[i]['download_url'] = new_entry['download_url']
                        if new_entry.get('sections'):
                            versions[i]['sections'] = new_entry['sections']
                        break
        else:
            print("  Could not parse API response")
    else:
        print("  API unavailable, preserving existing data")

    data['versions'] = versions
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    if versions and not data.get('latest_version'):
        data['latest_version'] = versions[0]['version']

    with open(DATA_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  Saved {len(versions)} versions to data.json")
    print(f"  Latest version: {data.get('latest_version', '?')}")
    print("Done.")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")
        print("Preserving existing data due to error.")
        # Still exit 0 to not fail the workflow
        sys.exit(0)
