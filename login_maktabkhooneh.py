"""
Maktabkhooneh.org - Login + Course Downloader
==============================================
Usage:
    # Login + list all download links (saves links.txt, no download):
    python login_maktabkhooneh.py -U YOUR_PHONE -P YourPassword --url https://maktabkhooneh.org/course/course-slug-mk7044/

    # Login + download all videos (default quality: best available):
    python login_maktabkhooneh.py -U YOUR_PHONE -P YourPassword --url https://maktabkhooneh.org/course/course-slug-mk7044/ --download

    # Choose quality (720 or 480):
    python login_maktabkhooneh.py -U YOUR_PHONE -P YourPassword --url ... --download --quality 720

    # Start from a specific unit ID (to resume):
    python login_maktabkhooneh.py -U YOUR_PHONE -P YourPassword --url ... --download --start-unit 98013
"""

import os
import re
import sys
import json
import time
import argparse
import requests
import io

# Force UTF-8 output on Windows so Persian/Arabic text doesn't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_URL = "https://maktabkhooneh.org"
OUTPUT_DIR = "downloads"

HEADERS = {
    "User-Agent":        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
    "Accept":            "application/json",
    "Accept-Language":   "en-US,en;q=0.9",
    "Referer":           "https://maktabkhooneh.org/",
    "Origin":            "https://maktabkhooneh.org",
    "X-Requested-With":  "XMLHttpRequest",
}

# ─────────────────────────────────────────────────────────
#  Auth helpers
# ─────────────────────────────────────────────────────────

def get_csrf(session):
    resp = session.get(BASE_URL, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)
    csrf = session.cookies.get("csrftoken")
    if csrf:
        return csrf
    for val in resp.raw.headers.getlist("Set-Cookie"):
        m = re.search(r"csrftoken=([A-Za-z0-9_-]+)", val)
        if m:
            csrf = m.group(1)
            session.cookies.set("csrftoken", csrf, domain="maktabkhooneh.org")
            return csrf
    return ""


def login(session, username, password):
    print("[Auth] Logging in as {} ...".format(username))
    csrf = get_csrf(session)

    # Step 1 - check user
    session.post(
        "{}/api/v1/auth/check-active-user".format(BASE_URL),
        params={"channel": ""},
        data={"csrfmiddlewaretoken": csrf, "tessera": username,
              "g-recaptcha-response": "recaptcha-token"},
        headers={**HEADERS, "X-Csrftoken": csrf},
        timeout=15,
    )
    csrf = session.cookies.get("csrftoken", csrf)

    # Step 2 - password
    resp = session.post(
        "{}/api/v1/auth/login-authentication".format(BASE_URL),
        data={"csrfmiddlewaretoken": csrf, "tessera": username,
              "hidden_username": username, "password": password,
              "g-recaptcha-response": "recaptcha-token"},
        headers={**HEADERS, "X-Csrftoken": csrf},
        timeout=15,
    )
    csrf = session.cookies.get("csrftoken", csrf)

    result = resp.json()
    if result.get("status") != "success":
        sys.exit("[ERROR] Login failed: {}".format(result))

    print("[Auth] OK - user_id={}  phone={}".format(
        result.get("user_id"), result.get("phone")))
    return csrf


# ─────────────────────────────────────────────────────────
#  Course helpers
# ─────────────────────────────────────────────────────────

def extract_course_id(course_url):
    """
    Extracts the numeric course ID from the slug, e.g. mk7044 -> 7044.
    Works on both the /course/ and /lms/course/ URL forms.
    """
    m = re.search(r"mk(\d+)", course_url)
    if not m:
        sys.exit("[ERROR] Could not extract course ID from URL: {}".format(course_url))
    return int(m.group(1))


def get_first_unit_id(session, csrf, course_id):
    """
    Fetches the course public page to find the first unit ID from the HTML.
    Falls back to walking the API to locate the start of the navigation chain.
    """
    h = {**HEADERS, "Accept": "text/html,application/json", "X-Csrftoken": csrf}

    # Try public course page (not LMS)
    course_slug_url = "{}/api/v1/courses/{}/".format(BASE_URL, course_id)
    r = session.get(course_slug_url, headers={**HEADERS, "X-Csrftoken": csrf}, timeout=15)
    if r.status_code == 200:
        d = r.json()
        # Try common fields that hold a starting unit
        for field in ("first_unit_id", "first_unit", "start_unit"):
            if field in d:
                return int(d[field]) if isinstance(d[field], (int, str)) else d[field].get("id")

    # Try the LMS enrollment info
    r2 = session.get(
        "{}/api/v1/lms/enrollments/?course={}".format(BASE_URL, course_id),
        headers={**HEADERS, "X-Csrftoken": csrf}, timeout=15
    )
    if r2.status_code == 200:
        d2 = r2.json()
        results = d2.get("results", d2) if isinstance(d2, dict) else d2
        for item in (results if isinstance(results, list) else [results]):
            uid = item.get("first_unit_id") or item.get("last_unit_id")
            if uid:
                return int(uid)

    return None


def get_all_units(session, csrf, start_unit_id):
    """
    Walks the navigation.next chain to collect all unit IDs and metadata.
    Returns a list of dicts: {id, title, chapter_title, order}
    """
    h = {**HEADERS, "X-Csrftoken": csrf}
    units = []
    visited = set()
    current_id = start_unit_id

    print("\n[Course] Walking units via navigation chain (this may take a while) ...")

    while current_id and current_id not in visited:
        visited.add(current_id)
        r = session.get(
            "{}/api/v1/lms/units/{}/".format(BASE_URL, current_id),
            headers=h, timeout=20
        )
        if r.status_code != 200:
            print("  [WARN] Unit {} returned HTTP {}".format(current_id, r.status_code))
            break

        data = r.json()
        units.append(data)
        title   = data.get("title", "") or ""
        chapter = data.get("chapter_title", "") or ""
        print("  [{:>3}] {:>6}  |  {}  /  {}".format(
            len(units), current_id,
            chapter[:30].encode('utf-8', errors='replace').decode('utf-8'),
            title[:40].encode('utf-8', errors='replace').decode('utf-8')))

        nxt = data.get("navigation", {}).get("next")
        current_id = nxt["id"] if nxt else None
        time.sleep(0.3)   # be polite

    print("[Course] Total units found: {}".format(len(units)))
    return units


# ─────────────────────────────────────────────────────────
#  Download helpers
# ─────────────────────────────────────────────────────────

def pick_resource(resources, preferred_quality):
    """
    Picks the best video resource from a unit's resources list.
    preferred_quality: int like 720 or 480; None = pick highest available.
    """
    videos = [r for r in resources if r.get("type") == 1 and r.get("download_url")]
    if not videos:
        return None
    if preferred_quality:
        exact = [v for v in videos if v.get("resolution_height") == preferred_quality]
        if exact:
            return exact[0]
    # highest resolution
    return max(videos, key=lambda v: v.get("resolution_height") or 0)


def safe_filename(text):
    """Strip characters that are illegal in Windows filenames."""
    return re.sub(r'[\\/:*?"<>|]', "_", text).strip()


def download_file(session, url, dest_path):
    """Streams a file to disk with a simple progress indicator."""
    tmp = dest_path + ".part"
    r = session.get(url, stream=True, timeout=60)
    r.raise_for_status()
    total = int(r.headers.get("Content-Length", 0))
    downloaded = 0
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 512):  # 512 KB
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print("\r    {:>3}%  {}/{} MB".format(
                    pct, downloaded // 1048576, total // 1048576), end="", flush=True)
    print()
    os.rename(tmp, dest_path)


# ─────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Login and download courses from maktabkhooneh.org",
        formatter_class=argparse.RawTextHelpFormatter
    )
    p.add_argument("-U", "--username", required=True,
                   help="Phone number or username")
    p.add_argument("-P", "--password", required=True,
                   help="Account password")
    p.add_argument("--url", required=False,
                   help="Public course URL  (e.g. https://maktabkhooneh.org/course/name-mk7044/)")
    p.add_argument("--download", action="store_true",
                   help="Actually download the videos (default: only list links)")
    p.add_argument("--quality", type=int, default=None,
                   help="Preferred video quality in pixels height: 720 or 480 (default: best)")
    p.add_argument("--start-unit", type=int, default=None,
                   help="Unit ID to start from (useful to resume an interrupted run)")
    p.add_argument("--out", default=OUTPUT_DIR,
                   help="Output directory for downloads (default: ./downloads)")
    return p.parse_args()


# ─────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────

def main():
    args = parse_args()
    session = requests.Session()

    # ── 1. Login ──────────────────────────────────────────
    csrf = login(session, args.username, args.password)

    if not args.url and not args.start_unit:
        print("\n[INFO] No --url or --start-unit given. Login successful, nothing else to do.")
        print("       sessionid : {}".format(session.cookies.get("sessionid")))
        return

    # ── 2. Resolve starting unit ──────────────────────────
    start_unit = args.start_unit
    course_id = None

    if args.url:
        course_id = extract_course_id(args.url)
        print("[Course] Course ID: {}".format(course_id))

        if not start_unit:
            start_unit = get_first_unit_id(session, csrf, course_id)

        if not start_unit:
            sys.exit(
                "[ERROR] Could not auto-detect the first unit ID.\n"
                "        Please open the course in your browser, navigate to the first lesson,\n"
                "        and pass its ID with --start-unit <ID>"
            )

    print("[Course] Starting from unit: {}".format(start_unit))

    # ── 3. Collect all units ───────────────────────────────
    units = get_all_units(session, csrf, start_unit)

    # ── 4. Save links file ────────────────────────────────
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    links_file = os.path.join(out_dir, "download_links.txt")

    with open(links_file, "w", encoding="utf-8") as lf:
        for unit in units:
            lf.write("# Unit {:>6}  |  {}  /  {}\n".format(
                unit.get("id"), unit.get("chapter_title", ""), unit.get("title", "")))
            for res in unit.get("resources", []):
                if res.get("download_url"):
                    lf.write("  [{}]  {}\n".format(
                        res.get("quality_display", res.get("quality", "?")),
                        res["download_url"]))
            lf.write("\n")

    print("\n[Links] Saved all download URLs -> {}".format(links_file))

    # ── 5. Download ───────────────────────────────────────
    if not args.download:
        print("[Info] Pass --download to actually download the videos.")
        return

    print("\n[Download] Starting downloads (quality preference: {}) ...".format(
        "{}p".format(args.quality) if args.quality else "best"))

    chapter_seen = {}
    for idx, unit in enumerate(units, 1):
        unit_id    = unit.get("id")
        unit_title = safe_filename(unit.get("title") or "unit_{}".format(unit_id))
        chapter    = safe_filename(unit.get("chapter_title") or "chapter")
        utype      = unit.get("type_display", "")

        # Skip non-video units
        if "Video" not in utype:
            print("[{:>3}/{}] SKIP  ({}): {}".format(idx, len(units), utype, unit_title[:50]))
            continue

        resource = pick_resource(unit.get("resources", []), args.quality)
        if not resource:
            print("[{:>3}/{}] SKIP  (no downloadable resource): {}".format(
                idx, len(units), unit_title[:50]))
            continue

        # Chapter sub-folder
        if chapter not in chapter_seen:
            chapter_seen[chapter] = len(chapter_seen) + 1
        chapter_dir = os.path.join(out_dir, "{:02d}_{}".format(chapter_seen[chapter], chapter[:50]))
        os.makedirs(chapter_dir, exist_ok=True)

        quality_label = resource.get("quality", "?")
        filename = "{:03d}_{}_({}).mp4".format(unit.get("order", idx), unit_title[:60], quality_label)
        dest = os.path.join(chapter_dir, filename)

        if os.path.exists(dest):
            print("[{:>3}/{}] SKIP  (already exists): {}".format(idx, len(units), filename))
            continue

        print("[{:>3}/{}] Downloading ({}) -> {}".format(
            idx, len(units), quality_label, filename[:60]))

        try:
            download_file(session, resource["download_url"], dest)
        except Exception as e:
            print("    [ERROR] {}".format(e))
            # Refresh unit to get a fresh signed URL and retry once
            try:
                print("    Refreshing URL and retrying ...")
                r2 = session.get(
                    "{}/api/v1/lms/units/{}/".format(BASE_URL, unit_id),
                    headers={**HEADERS, "X-Csrftoken": csrf}, timeout=20
                )
                fresh_data = r2.json()
                fresh_res  = pick_resource(fresh_data.get("resources", []), args.quality)
                if fresh_res:
                    download_file(session, fresh_res["download_url"], dest)
            except Exception as e2:
                print("    [FAILED] {}".format(e2))

        time.sleep(0.5)

    print("\n[Done] All videos saved to: {}".format(os.path.abspath(out_dir)))


if __name__ == "__main__":
    main()
