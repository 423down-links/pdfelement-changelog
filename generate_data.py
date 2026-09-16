#!/usr/bin/env python3
"""Generate PDFelement changelog data.
Primary: Wondershare API (requires valid client_sign, may fail).
Fallback: Increment version probe on download URL pattern.
If all fail, preserves existing data and exits successfully.
"""
import json
import os
import sys
import urllib.request
import urllib.error
import re
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

# Download URL pattern for increment probing
# Format: https://download.wondershare.com/cbs_down/pdfelement-pro_{major.minor.patch}_full{build}.exe
DOWNLOAD_PATTERN = "https://download.wondershare.com/cbs_down/pdfelement-pro_{version}_full5239.exe"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_latest_from_api():
    """Try to fetch latest version info from API. Returns dict or None."""
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


def probe_latest_version():
    """Increment version probe on download URL to find latest available version.
    Returns (version, download_url, size, date) or None.
    """
    print("  Probing download URLs for latest version...")
    
    def check_url(url):
        """Check if URL exists, return (exists, size, last_modified)."""
        try:
            req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=10) as resp:
                size = resp.headers.get('Content-Length', '0')
                date = resp.headers.get('Last-Modified', '')
                return resp.status == 200, int(size) if size.isdigit() else 0, date
        except:
            return False, 0, ''
    
    # Start from known versions and increment
    base_versions = ['13.0.0', '13.0.1', '13.0.2', '13.0.3', '13.0.4', '13.0.5', '13.1.0']
    
    latest_version = None
    latest_url = None
    latest_size = 0
    latest_date = ''
    
    for version in base_versions:
        url = DOWNLOAD_PATTERN.format(version=version)
        exists, size, date = check_url(url)
        if exists:
            latest_version = version
            latest_url = url
            latest_size = size
            latest_date = date
            print(f"    Found: {version} ({size/1024/1024:.1f}MB)")
        else:
            print(f"    Not found: {version}")
    
    # If found, try to increment further
    if latest_version:
        parts = latest_version.split('.')
        # Try incrementing patch version
        for i in range(1, 10):
            parts[-1] = str(int(parts[-1]) + 1)
            test_version = '.'.join(parts)
            url = DOWNLOAD_PATTERN.format(version=test_version)
            exists, size, date = check_url(url)
            if exists:
                latest_version = test_version
                latest_url = url
                latest_size = size
                latest_date = date
                print(f"    Found increment: {test_version}")
            else:
                break
    
    if latest_version:
        # Parse date
        parsed_date = ''
        if latest_date:
            # GMT format: Wed, 16 Sep 2026 05:55:33 GMT
            m = re.match(r'[A-Za-z]{3},\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', latest_date)
            if m:
                months = {'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
                          'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12'}
                parsed_date = f"{m.group(3)}-{months.get(m.group(2).lower(), '01')}-{m.group(1).zfill(2)}"
        
        print(f"  Latest version from probe: {latest_version}")
        return {
            'version': latest_version,
            'download_url': latest_url,
            'size': latest_size,
            'size_mb': round(latest_size / 1024 / 1024, 1),
            'date': parsed_date or datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        }
    return None


def parse_api_response(api_data):
    """Parse API response into version entry."""
    version = api_data.get('upgradeVersion') or api_data.get('new_version', '')
    if not version:
        return None

    title = api_data.get('whats_new_title', f'PDFelement {version}')
    content = api_data.get('whats_new_content', '')
    whats_new_list = api_data.get('whats_new_list', [])

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

    with open(DATA_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    versions = data.get('versions', [])
    print(f"  Existing versions: {len(versions)}")

    # Try fetch latest from API first
    print("  Fetching latest from API...")
    api_data = fetch_latest_from_api()

    new_entry = None
    if api_data:
        new_entry = parse_api_response(api_data)
        if new_entry:
            print(f"  API returned version: {new_entry['version']}")

    # Fallback: increment probe on download URL
    if not new_entry:
        print("  API unavailable, using download URL probe...")
        probe_result = probe_latest_version()
        if probe_result:
            new_entry = {
                'version': probe_result['version'],
                'date': probe_result['date'],
                'title': f'Wondershare PDFelement V{probe_result["version"]} is released!',
                'sections': [{'title': 'Updates', 'items': ['Version update detected via download URL probe.']}],
                'download_url': probe_result['download_url'],
                'md5': '',
                'size': probe_result['size'],
                'size_mb': probe_result['size_mb'],
            }
            print(f"  Probe found version: {new_entry['version']}")

    if new_entry:
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
                    if new_entry.get('size'):
                        versions[i]['size'] = new_entry['size']
                        versions[i]['size_mb'] = new_entry['size_mb']
                    if new_entry.get('sections') and not v.get('sections'):
                        versions[i]['sections'] = new_entry['sections']
                    break
    else:
        print("  Could not fetch latest version, preserving existing data")

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
        sys.exit(0)
