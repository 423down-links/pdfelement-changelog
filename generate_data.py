#!/usr/bin/env python3
"""Generate PDFelement changelog data.
Multi-layer detection:
  1. Wondershare API (requires valid client_sign, may fail with 401)
  2. Increment version probe on download URL pattern
  3. MD5 streaming calculation for new versions
  4. Changelog content fetch from official sources
If all fail, preserves existing data and exits successfully.
"""
import json
import os
import sys
import urllib.request
import urllib.error
import re
import hashlib
import time
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

# Download URL patterns for increment probing
# Build number may change, try multiple build suffixes
DOWNLOAD_PATTERNS = [
    "https://download.wondershare.com/cbs_down/pdfelement-pro_{version}_full5239.exe",
    "https://download.wondershare.com/cbs_down/pdfelement-pro_{version}_full.exe",
    "https://download.wondershare.com/cbs_down/pdfelement-pro_{version}.exe",
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# MD5 calculation: only for files under this size (bytes)
MD5_MAX_SIZE = 500 * 1024 * 1024  # 500MB
MD5_TIMEOUT = 300  # 5 minutes max for MD5 download


def fetch_latest_from_api():
    """Try to fetch latest version info from API. Returns dict or None."""
    params = f"pid={PRODUCT_ID}&version=13.0.0.0&brand={BRAND}&client_sign=generic"
    urls = [f"{API_URL}?{params}"] + [f"{u}?{params}" for u in FALLBACK_APIS]

    for url in urls:
        for attempt in range(2):  # retry once
            try:
                req = urllib.request.Request(url, headers={
                    'User-Agent': UA,
                    'X-Client-Type': '1',
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data.get('upgradeVersion') or data.get('new_version'):
                        return data
            except Exception as e:
                print(f"  API attempt {attempt+1} {url[:50]}... failed: {e}")
                if attempt == 0:
                    time.sleep(2)
                continue
    return None


def check_url_head(url):
    """Check URL with HEAD request, return (exists, size, last_modified)."""
    try:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            size = resp.headers.get('Content-Length', '0')
            date = resp.headers.get('Last-Modified', '')
            return resp.status == 200, int(size) if size.isdigit() else 0, date
    except:
        return False, 0, ''


def check_url_with_fallback(version):
    """Try multiple URL patterns for a version, return (exists, url, size, date)."""
    for pattern in DOWNLOAD_PATTERNS:
        url = pattern.format(version=version)
        exists, size, date = check_url_head(url)
        if exists:
            return True, url, size, date
    return False, '', 0, ''


def calculate_md5_streaming(url, max_size=MD5_MAX_SIZE, timeout=MD5_TIMEOUT):
    """Stream download and calculate MD5 without saving file.
    Returns md5 hex string or empty string on failure.
    """
    print(f"  Calculating MD5 (streaming, max {max_size/1024/1024:.0f}MB)...")
    md5 = hashlib.md5()
    total = 0
    start_time = time.time()
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            # Check content-length
            content_length = resp.headers.get('Content-Length', '0')
            if content_length.isdigit() and int(content_length) > max_size:
                print(f"  File too large ({int(content_length)/1024/1024:.0f}MB), skipping MD5")
                return ''
            
            while True:
                # Check timeout
                if time.time() - start_time > timeout:
                    print(f"  MD5 calculation timeout ({timeout}s), skipping")
                    return ''
                
                chunk = resp.read(65536)
                if not chunk:
                    break
                md5.update(chunk)
                total += len(chunk)
                
                if total > max_size:
                    print(f"  Download exceeded max size, skipping MD5")
                    return ''
        
        result = md5.hexdigest()
        print(f"  MD5: {result} (downloaded {total/1024/1024:.1f}MB)")
        return result
    except Exception as e:
        print(f"  MD5 calculation failed: {e}")
        return ''


def parse_date_gmt(date_str):
    """Parse GMT date format to YYYY-MM-DD."""
    if not date_str:
        return ''
    m = re.match(r'[A-Za-z]{3},\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', date_str)
    if m:
        months = {'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
                  'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12'}
        return f"{m.group(3)}-{months.get(m.group(2).lower(), '01')}-{m.group(1).zfill(2)}"
    return ''


def probe_latest_version():
    """Multi-layer increment version probe on download URL patterns.
    Returns dict with version, download_url, size, date, md5 or None.
    """
    print("  Probing download URLs for latest version...")
    
    # Generate candidate versions: 13.0.0 through 13.0.20, then 13.1.0 through 13.1.10, then 14.0.0
    candidates = []
    for minor in range(0, 5):  # 13.0.x to 13.4.x
        for patch in range(0, 25):
            candidates.append(f"13.{minor}.{patch}")
    for major in range(14, 16):  # 14.0.x, 15.0.x
        for patch in range(0, 10):
            candidates.append(f"{major}.0.{patch}")
    
    latest_version = None
    latest_url = None
    latest_size = 0
    latest_date = ''
    
    # Probe in batches, stop after 5 consecutive 404s
    consecutive_404 = 0
    for version in candidates:
        exists, url, size, date = check_url_with_fallback(version)
        if exists:
            latest_version = version
            latest_url = url
            latest_size = size
            latest_date = date
            consecutive_404 = 0
            print(f"    Found: {version} ({size/1024/1024:.1f}MB)")
        else:
            consecutive_404 += 1
            if consecutive_404 >= 8:
                print(f"    Stopping after {consecutive_404} consecutive not-found")
                break
    
    if latest_version:
        parsed_date = parse_date_gmt(latest_date)
        
        # Calculate MD5 for the latest version
        md5 = ''
        if latest_size > 0 and latest_size < MD5_MAX_SIZE:
            md5 = calculate_md5_streaming(latest_url)
        
        print(f"  Latest version from probe: {latest_version}")
        return {
            'version': latest_version,
            'download_url': latest_url,
            'size': latest_size,
            'size_mb': round(latest_size / 1024 / 1024, 1),
            'date': parsed_date or datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'md5': md5,
        }
    return None


def fetch_changelog_from_web(version):
    """Try to fetch changelog content from official website or known sources.
    Returns list of update items or empty list.
    """
    # Try Wondershare whats-new page
    urls = [
        f"https://pdf.wondershare.com/whats-new.html",
        f"https://pdf.wondershare.com/support/whats-new-pdfelement.html",
    ]
    
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                # Look for version section
                version_pattern = version.replace('.', r'\.')
                # Find content after version heading
                pattern = rf'{version_pattern}[^<]*</?h[23][^>]*>(.*?)(?:<h[23]|$)'
                m = re.search(pattern, html, re.S | re.I)
                if m:
                    content = m.group(1)
                    items = re.findall(r'<li[^>]*>(.*?)</li>', content, re.S)
                    items = [re.sub(r'<[^>]+>', '', i).strip() for i in items if i.strip()]
                    if items:
                        print(f"  Found {len(items)} changelog items from {url}")
                        return items
        except Exception as e:
            print(f"  Changelog fetch from {url} failed: {e}")
            continue
    
    return []


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
    print(f"  Time: {datetime.now(timezone.utc).isoformat()}")

    with open(DATA_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    versions = data.get('versions', [])
    print(f"  Existing versions: {len(versions)}")

    # Layer 1: Try fetch latest from API
    print("  [Layer 1] Fetching latest from API...")
    api_data = fetch_latest_from_api()

    new_entry = None
    if api_data:
        new_entry = parse_api_response(api_data)
        if new_entry:
            print(f"  API returned version: {new_entry['version']}")
            # If API has full_url, calculate MD5 if missing
            if new_entry.get('download_url') and not new_entry.get('md5'):
                new_entry['md5'] = calculate_md5_streaming(new_entry['download_url'])

    # Layer 2: Fallback to increment probe on download URL
    if not new_entry:
        print("  [Layer 2] API unavailable, using download URL probe...")
        probe_result = probe_latest_version()
        if probe_result:
            # Try to fetch changelog from web
            changelog_items = fetch_changelog_from_web(probe_result['version'])
            if not changelog_items:
                changelog_items = ['Version update detected via download URL probe.']
            
            new_entry = {
                'version': probe_result['version'],
                'date': probe_result['date'],
                'title': f'Wondershare PDFelement V{probe_result["version"]} is released!',
                'sections': [{'title': 'Updates', 'items': changelog_items}],
                'download_url': probe_result['download_url'],
                'md5': probe_result.get('md5', ''),
                'size': probe_result['size'],
                'size_mb': probe_result['size_mb'],
            }
            print(f"  Probe found version: {new_entry['version']} (MD5: {new_entry['md5'][:16]}...)")

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
                    # Update download URL if available
                    if new_entry.get('download_url'):
                        versions[i]['download_url'] = new_entry['download_url']
                    # Update size if available
                    if new_entry.get('size'):
                        versions[i]['size'] = new_entry['size']
                        versions[i]['size_mb'] = new_entry['size_mb']
                    # Update MD5 if we have it and existing is empty
                    if new_entry.get('md5') and not v.get('md5'):
                        versions[i]['md5'] = new_entry['md5']
                        print(f"  Updated MD5 for {new_entry['version']}")
                    # Update sections if existing is empty
                    if new_entry.get('sections') and not v.get('sections'):
                        versions[i]['sections'] = new_entry['sections']
                    # Update date if existing is empty
                    if new_entry.get('date') and not v.get('date'):
                        versions[i]['date'] = new_entry['date']
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
    # Print MD5 status for latest 3 versions
    for v in versions[:3]:
        md5_status = v.get('md5', '')[:16] + '...' if v.get('md5') else 'MISSING'
        print(f"    {v['version']}: MD5={md5_status}, size={v.get('size_mb', '?')}MB")
    print("Done.")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print("Preserving existing data due to error.")
        sys.exit(0)
