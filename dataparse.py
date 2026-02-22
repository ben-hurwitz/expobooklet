import pandas as pd
import requests
import io
import re

# --- Load CSVs (from URLs; falls back to local files if needed) ---

ROOM_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRU55NCazcagM1ugIwGa-oTuqATCc-Ilye0P8AnoPXZFeEMuvO9B6r51Uxh8ktLiRiDCR-q_O-7TQ-F"
    "/pub?gid=920592641&single=true&output=csv"
)

EXHIBIT_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vTlzXK2SdVT1gPIO5pPNaGx1T9uAoCsXKszEin1ZrmS7w2NmcxXbKgAynkYEvrPy15Gol7xwfKcWyrl"
    "/pub?output=csv"
)


def load_csv(url, fallback=None):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        print(f"Warning: Could not fetch {url} ({e})")
        if fallback:
            print(f"  Loading from local file: {fallback}")
            return pd.read_csv(fallback)
        raise


rooms = load_csv(
    ROOM_URL,
    fallback="_For_Ben__Copy_of_Master_Spreadsheet_2026_-_Room_Assignments.csv",
)

exhibits = load_csv(
    EXHIBIT_URL,
    fallback="Copy_of_EXPO_2026_-_Student_Exhibits__Responses__-_Form_Responses_1.csv",
)

# --- 1. Build booklet_location ---

def make_booklet_location(row):
    building = str(row["Building"]).strip()
    room = str(row["Room #"]).strip()

    # Lobby check (case-insensitive)
    if "lobby" in room.lower():
        return f"{building} | Lobby"

    # Floor from leading digit
    if room and room[0] == "1":
        floor = "Floor 1"
    elif room and room[0] == "2":
        floor = "Floor 2"
    else:
        # Fallback: just use the room value as-is
        return f"{building} | {room}"

    return f"{building} | {floor}"


def make_booklet_location(row):
    building = str(row["Building"]).strip()
    room = str(row["Room #"]).strip()

    # Lobby check (case-insensitive) — covers "E Hall Lobby Table X", "ME Lobby Table X", plain "Lobby"
    if "lobby" in room.lower():
        return f"{building} | Lobby"

    # ECB Atrium table entries → just "ECB | Atrium"
    if re.search(r'atrium', room, re.IGNORECASE):
        return f"{building} | Atrium"

    # Any remaining "Table ##" pattern → strip the table part, keep the prefix area name
    table_match = re.match(r'^(.*?)\s*Table\s*[\d\-]+', room, re.IGNORECASE)
    if table_match:
        area = table_match.group(1).strip(" |,")
        if area:
            return f"{building} | {area}"
        return f"{building} | Lobby"

    # Floor from leading digit
    if room and room[0] == "1":
        floor = "Floor 1"
    elif room and room[0] == "2":
        floor = "Floor 2"
    else:
        # Fallback: just use the room value as-is
        return f"{building} | {room}"

    return f"{building} | {floor}"


rooms["booklet_location"] = rooms.apply(make_booklet_location, axis=1)

# --- 2. Build day_warning ---

def parse_bool(val):
    """Convert various truthy/falsy representations to Python bool."""
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("true", "1", "yes")


def make_day_warning(row):
    fri = parse_bool(row["Friday"])
    sat = parse_bool(row["Saturday"])
    if fri and not sat:
        return "Friday Only"
    if sat and not fri:
        return "Saturday Only"
    return ""  # Both true (or both false) → no warning


rooms["day_warning"] = rooms.apply(make_day_warning, axis=1)

# --- 3. Keep only required columns from rooms ---
# Note: the source sheet uses "Award" loosely; the actual column may be
# "2025 Award Recipient" or similar — we check and rename if needed.

# Rename award column if needed
if "Award" not in rooms.columns and "2025 Award Recipient" in rooms.columns:
    rooms = rooms.rename(columns={"2025 Award Recipient": "Award"})

keep_cols = ["Award", "booklet_location", "day_warning", "Organization", "Exhibit Title"]
rooms = rooms[[c for c in keep_cols if c in rooms.columns]]

# --- 4. Merge exhibit descriptions ---

# Identify the relevant columns in the exhibits CSV
title_col = "Exhibit Title: The title that will be displayed and used to refer to your exhibit"
desc_col = (
    "Exhibit Description: Short description of what your exhibit will be/do. "
    "Note the highlights of your exhibit and how you will present it. "
    "This description will be used and made publicly available when describing your exhibit. "
    "(Note: NO SLIME ALLOWED)"
)

exhibits_slim = exhibits[[title_col, desc_col]].copy()
exhibits_slim.columns = ["Exhibit Title", "exhibit_description"]

# Merge on Exhibit Title (left join keeps all room entries)
result = rooms.merge(exhibits_slim, on="Exhibit Title", how="left")

# --- 4b. Fill missing descriptions ---
result["exhibit_description"] = result["exhibit_description"].fillna(
    "No exhibit description - attention needed"
)

# --- 4c. Filter out logistics/non-exhibit rows ---
exclude_keywords = ["lunch", "sponsor", "speakers", "storage", "changing room", "activities"]

def should_exclude(org):
    org_str = str(org).strip()
    if org_str == "" or org_str.lower() == "nan":
        return True
    return any(kw in org_str.lower() for kw in exclude_keywords)

result = result[~result["Organization"].apply(should_exclude)]
result = result[~result["Exhibit Title"].str.contains("SPONSOR", na=False)].reset_index(drop=True)

# Final column order
final_cols = ["Award", "booklet_location", "day_warning", "Organization", "Exhibit Title", "exhibit_description"]
result = result[[c for c in final_cols if c in result.columns]]

# --- 6. Sort by booklet_location in custom order ---
location_order = [
    "E Hall | Lobby",
    "E Hall | Floor 1",
    "E Hall | Floor 2",
    "ME | Lobby",
    "ME | Floor 1",
    "ME | Floor 2",
    "ECB | Atrium",
]

def location_sort_key(loc):
    try:
        return location_order.index(loc)
    except ValueError:
        return len(location_order)  # anything else goes at the end

result["_sort_key"] = result["booklet_location"].apply(location_sort_key)
result = result.sort_values("_sort_key").drop(columns=["_sort_key"]).reset_index(drop=True)

# --- 5. Save ---
output_path = "expo_booklet_data.csv"
result.to_csv(output_path, index=False)
print(f"Saved {len(result)} rows to {output_path}")
print(result.head(10).to_string())