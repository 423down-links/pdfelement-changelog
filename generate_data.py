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
PRODUCT_ID = "5239"            # numeric pid required by the check-upgrade API
BRAND = "wondershare"
PLATFORM = "win_x86"
CLIENT_SIGN = "%7B%7D"         # url-encoded empty JSON "{}"
API_URL = "https://pc-api.wondershare.cc/v2/product/check-upgrade"

# Fallback API endpoints (identical response schema)
FALLBACK_APIS = [
    "https://pc-api.300624.com/v2/product/check-upgrade",
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


def version_key(v):
    """Sort key for dotted version strings."""
    try:
        return tuple(int(x) for x in str(v).split('.'))
    except Exception:
        return (0,)


def fetch_latest_from_api(current_version):
    """Fetch latest version info from the check-upgrade API.

    `current_version` is the version the client reports as installed. The API
    returns the newest release that is strictly newer than it, together with the
    matching release notes. Passing a version one step behind the latest yields
    the accurate delta notes for the newest release.
    Returns the parsed `data` object or None.
    """
    params = ("pid={pid}&client_sign={sign}&version={ver}&platform={plat}"
              .format(pid=PRODUCT_ID, sign=CLIENT_SIGN,
                      ver=current_version, plat=PLATFORM))
    urls = [f"{API_URL}?{params}"] + [f"{u}?{params}" for u in FALLBACK_APIS]

    for url in urls:
        for attempt in range(2):  # retry once
            try:
                req = urllib.request.Request(url, headers={
                    'User-Agent': UA,
                    'X-Client-Type': '1',
                })
                with urllib.request.urlopen(req, timeout=20) as resp:
                    payload = json.loads(resp.read().decode('utf-8'))
                data = payload.get('data') if isinstance(payload, dict) else None
                if data and data.get('version'):
                    return data
            except Exception as e:
                print(f"  API attempt {attempt+1} {url[:60]}... failed: {e}")
                if attempt == 0:
                    time.sleep(2)
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
    """Try to fetch changelog content from official website.
    Returns list of update items or empty list.
    页面结构: 版本号在<h2>中，内容含<h4>分类和<ul><li>条目
    小版本(13.0.4)无单独日志时，回退到大版本(13.0.0)日志
    """
    urls = [
        "https://pdf.wondershare.com/whats-new.html",
        "https://pdf.wondershare.cn/whats-new.html",
    ]

    # 生成要尝试的版本列表：精确版本 → 大版本(13.0.0)
    parts = version.split('.')
    versions_to_try = [version]
    if len(parts) >= 3 and parts[2] != '0':
        major_version = f"{parts[0]}.{parts[1]}.0"
        if major_version not in versions_to_try:
            versions_to_try.append(major_version)

    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode('utf-8', errors='ignore')

                for ver in versions_to_try:
                    ver_pattern = ver.replace('.', r'\.')
                    # 匹配版本号在h2/h3标签内: 13.0.0</h2> 或 <h2>...13.0.0...</h2>
                    # 捕获到下一个h2/h3之前的内容
                    pattern = rf'{ver_pattern}\s*</h[23]>(.*?)(?=<h[23]|$)'
                    m = re.search(pattern, html, re.DOTALL | re.I)
                    if not m:
                        # 尝试另一种结构: <h2...>版本号</h2>
                        pattern2 = rf'<h[23][^>]*>\s*{ver_pattern}\s*</h[23]>(.*?)(?=<h[23]|$)'
                        m = re.search(pattern2, html, re.DOTALL | re.I)
                    if m:
                        content = m.group(1)
                        items = re.findall(r'<li[^>]*>(.*?)</li>', content, re.DOTALL)
                        items = [re.sub(r'<[^>]+>', '', i).strip() for i in items if i.strip()]
                        if items:
                            label = f" (from {ver})" if ver != version else ""
                            print(f"  Found {len(items)} changelog items from {url}{label}")
                            return items
        except Exception as e:
            print(f"  Changelog fetch from {url} failed: {e}")
            continue

    return []


def strip_tags(s):
    """Remove HTML tags / scripts and collapse whitespace."""
    s = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', s, flags=re.DOTALL | re.I)
    s = re.sub(r'<[^>]+>', '', s)
    s = (s.replace('&nbsp;', ' ').replace('&amp;', '&')
          .replace('&#39;', "'").replace('&quot;', '"'))
    return re.sub(r'\s+', ' ', s).strip()


def parse_whats_new_sections(content):
    """Convert whats_new_content (plain text or HTML) into section objects."""
    if not content or not content.strip():
        return []

    text = content.strip()

    # Rich release notes: <div class='wn-title'>Title</div> + <div class='wn-desc'>…</div>
    if 'wn-title' in text:
        sections = []
        blocks = re.findall(
            r"<div class='wn-title'>(.*?)</div>(.*?)(?=<div class='wn-title'>|$)",
            text, re.DOTALL)
        for name, body in blocks:
            name = strip_tags(name)
            items = [strip_tags(d) for d in
                     re.findall(r"<div class='wn-desc'>(.*?)</div>", body, re.DOTALL)]
            items = [i for i in items if i]
            if name and items:
                sections.append({'title': name, 'items': items})
        if sections:
            return sections

    # Simple <li> list
    items = [strip_tags(i) for i in re.findall(r'<li[^>]*>(.*?)</li>', text, re.DOTALL)]
    items = [i for i in items if i]
    if items:
        return [{'title': 'Updates', 'items': items}]

    # Plain-text note
    plain = strip_tags(text)
    if plain:
        return [{'title': 'Updates', 'items': [plain]}]

    return []


def parse_api_response(api_data):
    """Parse a check-upgrade `data` object into a version entry."""
    version = (api_data.get('version') or '').strip()
    if not version:
        return None

    full = api_data.get('full') or {}
    size = int(full.get('size') or 0)
    url = (full.get('url') or '').replace('http://', 'https://', 1)
    md5 = (full.get('md5') or '').lower()

    return {
        'version': version,
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'title': (api_data.get('whats_new_title')
                  or f'Wondershare PDFelement V{version} is released!'),
        'sections': parse_whats_new_sections(api_data.get('whats_new_content', '')),
        'download_url': url,
        'md5': md5,
        'size': size,
        'size_mb': round(size / 1024 / 1024, 1),
    }


def main():
    print("Generating PDFelement changelog data...")
    print(f"  Time: {datetime.now(timezone.utc).isoformat()}")

    with open(DATA_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    versions = data.get('versions', [])
    print(f"  Existing versions: {len(versions)}")

    known_sorted = sorted({v['version'] for v in versions if v.get('version')},
                          key=version_key, reverse=True)

    # Layer 1: query the check-upgrade API. Try the current latest first (detects a
    # strictly newer release), then the previous version (refreshes the notes of the
    # current latest), then the oldest known version as a last resort.
    print("  [Layer 1] Fetching latest from API...")
    api_bases = []
    if known_sorted:
        api_bases.append(known_sorted[0])
        if len(known_sorted) > 1:
            api_bases.append(known_sorted[1])
        api_bases.append(known_sorted[-1])
    api_bases.append("9.0.0")

    api_data = None
    for base in dict.fromkeys(api_bases):  # unique, order preserved
        api_data = fetch_latest_from_api(base)
        if api_data:
            print(f"  API (from {base}) -> {api_data.get('version')}")
            break
    if not api_data:
        print("  API unavailable.")

    new_entry = None
    if api_data:
        new_entry = parse_api_response(api_data)
        if new_entry:
            print(f"  API latest version: {new_entry['version']}")
            # Calculate MD5 if the API did not return one
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
            print(f"  Probe found version: {new_entry['version']}")

    if new_entry:
        existing_versions = [v['version'] for v in versions]
        if new_entry['version'] not in existing_versions:
            # Derive the release date from the installer's Last-Modified header
            if new_entry.get('download_url'):
                _, _, last_mod = check_url_head(new_entry['download_url'])
                date = parse_date_gmt(last_mod)
                if date:
                    new_entry['date'] = date
            versions.insert(0, new_entry)
            data['latest_version'] = new_entry['version']
            print(f"  New version added: {new_entry['version']}")
        else:
            print(f"  Version {new_entry['version']} already exists, refreshing info")
            for i, v in enumerate(versions):
                if v['version'] != new_entry['version']:
                    continue
                changed = False
                if new_entry.get('title') and versions[i].get('title') != new_entry['title']:
                    versions[i]['title'] = new_entry['title']
                    changed = True
                if new_entry.get('sections') and versions[i].get('sections') != new_entry['sections']:
                    versions[i]['sections'] = new_entry['sections']
                    changed = True
                if new_entry.get('download_url') and versions[i].get('download_url') != new_entry['download_url']:
                    versions[i]['download_url'] = new_entry['download_url']
                    changed = True
                if new_entry.get('size') and versions[i].get('size') != new_entry['size']:
                    versions[i]['size'] = new_entry['size']
                    versions[i]['size_mb'] = new_entry['size_mb']
                    changed = True
                if new_entry.get('md5') and not versions[i].get('md5'):
                    versions[i]['md5'] = new_entry['md5']
                    changed = True
                print(f"  Info updated for {new_entry['version']}" if changed
                      else f"  Info for {new_entry['version']} already up to date")
                break

    # 修复步骤：扫描所有版本，对占位日志重新抓取真实更新日志
    print("  [Repair] Scanning for placeholder changelogs...")
    repaired = 0
    for i, v in enumerate(versions):
        existing_items = []
        if v.get('sections'):
            for s in v['sections']:
                existing_items.extend(s.get('items', []))
        has_placeholder = any('Version update detected via download URL probe' in str(item) for item in existing_items)
        if has_placeholder or not v.get('sections'):
            changelog_items = fetch_changelog_from_web(v['version'])
            if changelog_items:
                versions[i]['sections'] = [{'title': 'Updates', 'items': changelog_items}]
                repaired += 1
                print(f"  ✅ Repaired changelog for {v['version']} ({len(changelog_items)} items)")
    if repaired > 0:
        print(f"  Repaired {repaired} version(s) with real changelog")
    elif not new_entry:
        print("  No version detected, preserving existing data")

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
