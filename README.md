# Maktabkhooneh Course Downloader

A Python script to log in to [maktabkhooneh.org](https://maktabkhooneh.org) and download your purchased course videos.

---

## Requirements

- Python 3.8+
- `requests` library

```bash
pip install requests
```

---

## Usage

### 1. Login only (test credentials)
```bash
python login_maktabkhooneh.py -U YOUR_PHONE -P YourPassword
```

### 2. List all download links (no download)
Saves all video URLs to `downloads/download_links.txt`:
```bash
python login_maktabkhooneh.py -U YOUR_PHONE -P YourPassword \
    --url https://maktabkhooneh.org/course/course-name-mk7044/ \
    --start-unit FIRST_UNIT_ID
```

### 3. Download all videos
```bash
python login_maktabkhooneh.py -U YOUR_PHONE -P YourPassword \
    --url https://maktabkhooneh.org/course/course-name-mk7044/ \
    --start-unit FIRST_UNIT_ID \
    --download
```

### 4. Download in a specific quality
```bash
python login_maktabkhooneh.py ... --download --quality 720
python login_maktabkhooneh.py ... --download --quality 480
```

### 5. Resume an interrupted download
```bash
python login_maktabkhooneh.py ... --download --start-unit 98050
```
The script skips files that already exist on disk, so it's safe to re-run.

---

## All Flags

| Flag | Description |
|------|-------------|
| `-U`, `--username` | Phone number or username **(required)** |
| `-P`, `--password` | Account password **(required)** |
| `--url` | Public course URL (e.g. `https://maktabkhooneh.org/course/name-mk7044/`) |
| `--start-unit` | Unit ID to start walking from (see note below) |
| `--download` | Actually download videos (default: only list links) |
| `--quality` | Preferred resolution: `720` or `480` (default: best available) |
| `--out` | Output folder (default: `./downloads`) |

---

## How to Find the First Unit ID

The script cannot auto-detect the first unit ID from the course URL alone.

1. Open the course page in your browser
2. Click on the **first lesson**
3. Look at the URL — it will look like:
   ```
   https://maktabkhooneh.org/lms/course/course-name-mk7044/unit/97960/
   ```
4. The number at the end (`97960`) is your `--start-unit` value

---

## Output Structure

```
downloads/
├── download_links.txt          ← all URLs (720p + 480p + attachments)
├── 01_Chapter Name/
│   ├── 001_Lesson Title_(720p).mp4
│   ├── 002_Lesson Title_(720p).mp4
│   └── ...
├── 02_Another Chapter/
│   └── ...
└── ...
```

---

## Notes

> **Links expire in ~30 minutes.**
> The `download_links.txt` URLs contain a signed `expire=` token.
> - For external downloaders (IDM, etc.) → re-run the script to get fresh URLs
> - For direct download → use `--download` flag; the script fetches a fresh URL for each file right before downloading

> **Resume support:** Re-running with `--download` will skip files that already exist. Use `--start-unit` with a later unit ID to jump ahead.

> **Attachments included:** The script also captures `.zip` and `.pdf` lecture files attached to lessons.

> **Quiz units are skipped** automatically (they have no video or download link).
