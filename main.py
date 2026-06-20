import argparse
import calendar
import difflib
import json
import os
import random
import re
from datetime import datetime, date, timedelta
from dataclasses import dataclass, asdict
import traceback
import unicodedata

try:
    import curses
except ModuleNotFoundError:
    curses = None

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(APP_ROOT, "data")
STATE_DIR_ENV_VAR = "BORDER_CONTROL_DATA_DIR"


def resolve_state_dir(cli_data_dir: str | None = None) -> str:
    state_dir = cli_data_dir or os.environ.get(STATE_DIR_ENV_VAR)
    if state_dir:
        return os.path.abspath(state_dir)
    return APP_ROOT


STATE_DIR = resolve_state_dir()


def asset_path(*parts: str) -> str:
    return os.path.join(ASSET_DIR, *parts)


def state_path(*parts: str) -> str:
    return os.path.join(STATE_DIR, *parts)


def ensure_parent_dir(file_path: str) -> None:
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


DATA_FILE = state_path("passenger_data.json")
SETTINGS_FILE = state_path("data", "system_settings.json")
ERROR_LOG_FILE = state_path("data", "error.log")

DEFAULT_APP_SETTINGS = {
    "login_user": "XOAPLUQA",
    "login_password": "123456",
    "printer_name": "Default Printer",
    "print_size": "A4",
    "print_size_custom_width": "",
    "print_size_custom_height": "",
    "page_orientation": "Portrait",
    "network_mode": "WiFi",
    "wifi_ssid": "",
    "wifi_password": "",
    "ip_mode": "DHCP",
    "ip_address": "",
    "subnet_mask": "",
    "gateway": "",
    "dns": "",
    "server_ip": "",
}

# Minimal ISO3166 alpha-3 and IATA samples for lookup. Extend as needed.
ISO_COUNTRIES = [
    ("USA", "United States"),
    ("CHN", "China"),
    ("GBR", "United Kingdom"),
    ("FRA", "France"),
    ("DEU", "Germany"),
    ("JPN", "Japan"),
    ("XXX", "Stateless"),
]

IATA_CODES = ["PEK", "PVG", "HKG", "LHR", "JFK", "SFO", "DXB", "SIN", "SYD"]

# Try to load full country list and airport codes if available; otherwise fall back to samples above.
try:
    import pycountry
except Exception:
    pycountry = None

try:
    import airportsdata
except Exception:
    airportsdata = None

if pycountry is not None:
    try:
        ISO_COUNTRIES = [(c.alpha_3, c.name) for c in pycountry.countries]
    except Exception:
        pass

IATA_CHOICES = []
IATA_COUNTRY_ALPHA2 = {}

# City-level IATA code mapping for major metro areas.
CITY_IATA_CODES = {
    'beijing': 'BJS',
    'shanghai': 'SHA',
    'tokyo': 'TYO',
    'london': 'LON',
    'new york': 'NYC',
    'paris': 'PAR',
    'berlin': 'BER',
    'hong kong': 'HKG',
    'seoul': 'SEL',
    'madrid': 'MAD',
    'moscow': 'MOW',
    'rome': 'ROM',
    'dubai': 'DXB',
    'singapore': 'SIN',
    'sydney': 'SYD',
}
CITY_CODE_NAMES = {
    'BJS': 'Beijing',
    'SHA': 'Shanghai',
    'TYO': 'Tokyo',
    'LON': 'London',
    'NYC': 'New York',
    'PAR': 'Paris',
    'BER': 'Berlin',
    'HKG': 'Hong Kong',
    'SEL': 'Seoul',
    'MAD': 'Madrid',
    'MOW': 'Moscow',
    'ROM': 'Rome',
    'DXB': 'Dubai',
    'SIN': 'Singapore',
    'SYD': 'Sydney',
}
CITY_IATA_COUNTRY_ALPHA2 = {
    'BJS': 'CN',
    'SHA': 'CN',
    'TYO': 'JP',
    'LON': 'GB',
    'NYC': 'US',
    'PAR': 'FR',
    'BER': 'DE',
    'HKG': 'HK',
    'SEL': 'KR',
    'MAD': 'ES',
    'MOW': 'RU',
    'ROM': 'IT',
    'DXB': 'AE',
    'SIN': 'SG',
    'SYD': 'AU',
}


def filter_iata_city_codes(codes, airport_data):
    code_map = {}
    country_map = {}
    for code in codes:
        record = airport_data.get(code)
        if record is None:
            continue
        city = (record.get('city') or '').strip().lower()
        city_code = CITY_IATA_CODES.get(city, code)
        code_map[city_code] = record
        country = (record.get('country') or '').strip().upper()
        if country:
            country_map[city_code] = country
    keep = sorted(code_map.keys())
    return keep, country_map


def sanitize_iata_name(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"\bAirport\b", "", name, flags=re.IGNORECASE).strip()

if airportsdata is not None:
    try:
        ap = airportsdata.load('IATA')
        IATA_CODES, IATA_COUNTRY_ALPHA2 = filter_iata_city_codes(sorted(ap.keys()), ap)
        IATA_CHOICES = sorted([
            (code, sanitize_iata_name(
                CITY_CODE_NAMES.get(code,
                    (ap.get(code) or {}).get('city') or
                    (ap.get(code) or {}).get('name', '')
                )
            ))
            for code in IATA_CODES
        ])
    except Exception:
        pass
else:
    IATA_CHOICES = [(code, code) for code in IATA_CODES]

# If pre-generated local JSON data exists, prefer loading it for offline use.
local_iso = asset_path('iso_countries.json')
local_iata = asset_path('iata_codes.json')
if os.path.exists(local_iso):
    try:
        loaded = json.load(open(local_iso, 'r', encoding='utf-8'))
        ISO_COUNTRIES = []
        for item in loaded:
            code = item.get('alpha_3') or item.get('alpha_2')
            if code and len(code) == 2 and pycountry is not None:
                country = pycountry.countries.get(alpha_2=code)
                if country is not None:
                    code = country.alpha_3
            if code:
                ISO_COUNTRIES.append((code, item.get('name', '')))
    except Exception:
        pass
if os.path.exists(local_iata):
    try:
        with open(local_iata, 'r', encoding='utf-8') as f:
            IATA_CODES = json.load(f)
        if airportsdata is not None:
            ap = airportsdata.load('IATA')
            IATA_CODES = [code for code in IATA_CODES if code in ap]
            IATA_CODES, IATA_COUNTRY_ALPHA2 = filter_iata_city_codes(IATA_CODES, ap)
            IATA_CHOICES = []
            for code in IATA_CODES:
                record = ap.get(code, {})
                name = sanitize_iata_name(CITY_CODE_NAMES.get(code, record.get('city') or record.get('name') or ''))
                IATA_CHOICES.append((code, name))
            IATA_CHOICES = sorted(IATA_CHOICES)
        else:
            IATA_CHOICES = [(code, code) for code in IATA_CODES]
    except Exception:
        pass


def choice_display(choice):
    if isinstance(choice, tuple):
        code, name = choice
        return f"{code} {name}" if name else code
    return str(choice)


def choice_code(choice):
    if isinstance(choice, tuple):
        return choice[0]
    return str(choice)


def char_display_width(ch: str) -> int:
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(char_display_width(ch) for ch in text)


def display_truncate(text: str, max_width: int) -> str:
    if max_width <= 0:
        return ""
    width = 0
    result = []
    for ch in str(text):
        ch_width = char_display_width(ch)
        if width + ch_width > max_width:
            break
        result.append(ch)
        width += ch_width
    return "".join(result)


def display_ljust(text: str, width: int) -> str:
    text = str(text)
    pad = max(0, width - display_width(text))
    return text + (" " * pad)


def fuzzy_search_choices(choices, query, max_results=10):
    if not query:
        return choices[:max_results]
    query = query.strip().lower()
    exact_matches = []
    fuzzy = []
    seen = set()
    for c in choices:
        code = choice_code(c).lower()
        name = (c[1].lower() if isinstance(c, tuple) and c[1] else "")
        display = choice_display(c).lower()
        if code == query or display == query:
            exact_matches.append(c)
            seen.add(c)
            continue
        if query in code or query in name or query in display:
            if c not in seen:
                exact_matches.append(c)
                seen.add(c)
            continue
        fuzzy.append((display, c))
    if exact_matches:
        return exact_matches[:max_results]
    if fuzzy:
        str_choices = [item[0] for item in fuzzy]
        mapping = {item[0]: item[1] for item in fuzzy}
        matches = difflib.get_close_matches(query, str_choices, n=max_results, cutoff=0.1)
        return [mapping[m] for m in matches]
    return []


class DateAmbiguityError(ValueError):
    def __init__(self, candidates):
        self.candidates = candidates
        super().__init__("Ambiguous date input")


def _yy_to_year(two_digit_year: int) -> int:
    current_yy = date.today().year % 100
    return (2000 if two_digit_year <= current_yy else 1900) + two_digit_year


def _build_date(y: int, m: int, d: int):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date_candidates(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    candidates = []

    def add_candidate(dt):
        if dt is None:
            return
        normalized = dt.strftime("%Y-%m-%d")
        if normalized not in candidates:
            candidates.append(normalized)

    # Digits only inputs.
    if re.match(r"^\d{8}$", text):
        y, m, d = int(text[0:4]), int(text[4:6]), int(text[6:8])
        add_candidate(_build_date(y, m, d))
        m, d, y = int(text[0:2]), int(text[2:4]), int(text[4:8])
        add_candidate(_build_date(y, m, d))
        d, m, y = int(text[0:2]), int(text[2:4]), int(text[4:8])
        add_candidate(_build_date(y, m, d))
        return candidates
    if re.match(r"^\d{6}$", text):
        yy, m, d = int(text[0:2]), int(text[2:4]), int(text[4:6])
        add_candidate(_build_date(_yy_to_year(yy), m, d))
        if not candidates:
            m, d, yy = int(text[0:2]), int(text[2:4]), int(text[4:6])
            add_candidate(_build_date(_yy_to_year(yy), m, d))
            d, m, yy = int(text[0:2]), int(text[2:4]), int(text[4:6])
            add_candidate(_build_date(_yy_to_year(yy), m, d))
        return candidates

    # Inputs with separators like 1999-12-31, 11/12/99, 31-12-1999.
    parts = re.split(r"[-/.]", text)
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        a, b, c = parts
        ia, ib, ic = int(a), int(b), int(c)
        if len(a) == 4:
            add_candidate(_build_date(ia, ib, ic))
        elif len(c) == 4:
            add_candidate(_build_date(ic, ia, ib))
            add_candidate(_build_date(ic, ib, ia))
        elif len(a) == 2 and len(b) <= 2 and len(c) <= 2:
            add_candidate(_build_date(_yy_to_year(ia), ib, ic))
        elif len(c) == 2 and len(a) <= 2 and len(b) <= 2:
            add_candidate(_build_date(_yy_to_year(ic), ia, ib))
            add_candidate(_build_date(_yy_to_year(ic), ib, ia))
        return candidates

    # Fallback to strict parser for uncommon but valid formats.
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m-%d-%Y",
        "%m/%d/%Y",
    ):
        try:
            add_candidate(datetime.strptime(text, fmt).date())
        except Exception:
            pass
    try:
        add_candidate(datetime.fromisoformat(text).date())
    except Exception:
        pass
    return candidates

def parse_date_fuzzy(text: str) -> str:
    """Parse various date inputs into YYYY-MM-DD or raise ValueError."""
    candidates = parse_date_candidates(text)
    if not candidates:
        raise ValueError("Unrecognized date format")
    if len(candidates) > 1:
        raise DateAmbiguityError(candidates)
    return candidates[0]

def get_iata_country_alpha2(iata_code: str) -> str:
    code = (iata_code or '').strip().upper()
    if not code:
        return ''
    if code in IATA_COUNTRY_ALPHA2:
        return IATA_COUNTRY_ALPHA2[code].upper()
    return CITY_IATA_COUNTRY_ALPHA2.get(code, '').upper()


def validate_document_format(doc_type: str, number: str, issuing_company: str = "") -> bool:
    number = number.strip().upper()
    issuer = (issuing_company or '').strip().upper()
    if len(number) != 9:
        return False
    if doc_type == "01":
        return bool(re.match(r'^STF\d{6}$', number))
    if doc_type == "02":
        return bool(re.match(r'^S\d{8}$', number))
    if doc_type == "03":
        return bool(re.match(r'^A[B-G]\d{7}$', number))
    if doc_type == "04":
        return bool(re.match(r'^H[H-Z]\d{7}$', number))
    if doc_type == "05":
        issuer_country = get_iata_country_alpha2(issuer)
        if not issuer_country:
            return False
        if issuer_country == 'CN':
            return bool(re.match(r'^D[O-Z]\d{7}$', number))
        return bool(re.match(rf'^D{issuer_country}[O-Z]\d{{5}}$', number))
    if doc_type == "06":
        return bool(re.match(r'^R\d{8}$', number))
    if doc_type == "07":
        if len(issuer) != 3:
            return False
        return bool(re.match(rf'^E{issuer}\d{{5}}$', number))
    return False

DATE_FORMAT = "%Y-%m-%d"


def generate_permit_id() -> str:
    charset = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    while True:
        candidate = "".join(random.choice(charset) for _ in range(9))
        if re.search(r"[A-Z]", candidate) and re.search(r"\d", candidate):
            return candidate


def validate_permit_id(permit_id: str) -> bool:
    permit_id = permit_id.strip().upper()
    return bool(
        re.match(r'^[A-Z0-9]{9}$', permit_id)
        and re.search(r'[A-Z]', permit_id)
        and re.search(r'\d', permit_id)
    )


def validate_staff_id(staff_id: str) -> bool:
    return bool(re.match(r'^[A-Z]{8}$', staff_id.strip().upper()))

def add_years(base: date, years: int) -> date:
    try:
        return base.replace(year=base.year + years)
    except ValueError:
        return base.replace(month=2, day=28, year=base.year + years)


def validate_document_dates(issue_date: date, expiry_date: date) -> None:
    if expiry_date < issue_date:
        raise ValueError("Expiry date must not be before issue date.")

@dataclass
class DocumentRecord:
    document_number: str
    doc_type: str
    name: str
    staff_id: str
    nationality: str
    expiry_date: str
    issuing_company: str = ""
    status: str = "active"

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(data):
        return DocumentRecord(
            document_number=data["document_number"],
            doc_type=data["doc_type"],
            name=data["name"],
            staff_id=data.get("staff_id", ""),
            nationality=data["nationality"],
            expiry_date=data["expiry_date"],
            issuing_company=data.get("issuing_company", ""),
            status=data.get("status", "active"),
        )

    def is_valid(self):
        if self.status != "active":
            return False
        try:
            expiry = datetime.strptime(self.expiry_date, DATE_FORMAT).date()
            return expiry >= date.today()
        except ValueError:
            return False

@dataclass
class PermitRecord:
    permit_id: str
    document_number: str
    name: str
    doc_type: str
    issue_date: str
    expiry_date: str
    status: str = "active"
    purpose: str = "entry"

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(data):
        return PermitRecord(
            permit_id=data["permit_id"],
            document_number=data["document_number"],
            name=data["name"],
            doc_type=data["doc_type"],
            issue_date=data["issue_date"],
            expiry_date=data["expiry_date"],
            status=data.get("status", "active"),
            purpose=data.get("purpose", "entry"),
        )

    def is_valid(self):
        if self.status != "active":
            return False
        try:
            expiry = datetime.strptime(self.expiry_date, DATE_FORMAT).date()
            return expiry >= date.today()
        except ValueError:
            return False

@dataclass
class PassengerRecord:
    document_number: str
    doc_type: str
    name: str
    nationality: str
    entry_mode: str
    permit_id: str
    entry_time: str
    exit_time: str = ""
    status: str = "present"

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(data):
        return PassengerRecord(
            document_number=data["document_number"],
            doc_type=data["doc_type"],
            name=data["name"],
            nationality=data["nationality"],
            entry_mode=data["entry_mode"],
            permit_id=data.get("permit_id", ""),
            entry_time=data["entry_time"],
            exit_time=data.get("exit_time", ""),
            status=data.get("status", "present"),
        )

class BorderControlSystem:
    def __init__(self, data_file=DATA_FILE):
        self.data_file = data_file
        self.documents: dict[str, DocumentRecord] = {}
        self.permits: dict[str, PermitRecord] = {}
        self.current_passengers: dict[str, PassengerRecord] = {}
        self.logs: list[PassengerRecord] = []
        self.load_data()

    def load_data(self):
        if not os.path.exists(self.data_file):
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as file:
                data = json.load(file)
                self.documents = {
                    item["document_number"]: DocumentRecord.from_dict(item)
                    for item in data.get("documents", [])
                }
                self.permits = {
                    item["permit_id"]: PermitRecord.from_dict(item)
                    for item in data.get("permits", [])
                }
                self.current_passengers = {
                    item["document_number"]: PassengerRecord.from_dict(item)
                    for item in data.get("current_passengers", [])
                }
                self.logs = [PassengerRecord.from_dict(item) for item in data.get("logs", [])]
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    def save_data(self):
        payload = {
            "documents": [record.to_dict() for record in self.documents.values()],
            "permits": [record.to_dict() for record in self.permits.values()],
            "current_passengers": [record.to_dict() for record in self.current_passengers.values()],
            "logs": [record.to_dict() for record in self.logs],
        }
        ensure_parent_dir(self.data_file)
        with open(self.data_file, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)

    def register_entry(self, document_number, doc_type, name, staff_id, nationality, expiry_date, issuing_company, entry_mode, permit_id="", permit_days=30):
        document_number = document_number.strip().upper()
        staff_id = staff_id.strip().upper()
        if document_number in self.current_passengers:
            raise ValueError("A passenger with that document is already inside.")

        document = self.documents.get(document_number)
        if document is None:
            document = DocumentRecord(
                document_number=document_number,
                doc_type=doc_type,
                name=name.strip(),
                staff_id=staff_id,
                nationality=nationality.strip(),
                expiry_date=expiry_date,
                issuing_company=issuing_company.strip(),
            )
            self.documents[document_number] = document
        else:
            document.name = name.strip()
            document.staff_id = staff_id
            document.nationality = nationality.strip()
            document.expiry_date = expiry_date
            document.issuing_company = issuing_company.strip()

        linked_permit = ""
        if entry_mode == "Use existing Visit Permit":
            if not permit_id:
                raise ValueError("A permit ID is required to use existing Visit Permit mode.")
            permit = self.permits.get(permit_id)
            if permit is None:
                raise ValueError("Permit not found.")
            if not permit.is_valid():
                raise ValueError("The selected permit is not valid.")
            linked_permit = permit_id
        elif entry_mode == "Issue Visit Permit and admit":
            permit_id = generate_permit_id()
            while permit_id in self.permits:
                permit_id = generate_permit_id()
            if not validate_permit_id(permit_id):
                raise ValueError("Permit ID must be 9 alphanumeric characters and include letters and digits.")
            if permit_id in self.permits:
                raise ValueError("Permit ID already exists.")
            issue_date = date.today().strftime(DATE_FORMAT)
            expiry_date_permit = (date.today() + timedelta(days=permit_days)).strftime(DATE_FORMAT)
            permit = PermitRecord(
                permit_id=permit_id,
                document_number=document_number,
                name=name.strip(),
                doc_type=doc_type,
                issue_date=issue_date,
                expiry_date=expiry_date_permit,
                status="active",
                purpose="entry",
            )
            self.permits[permit_id] = permit
            linked_permit = permit_id
        else:
            linked_permit = ""

        record = PassengerRecord(
            document_number=document_number,
            doc_type=doc_type,
            name=name.strip(),
            nationality=nationality.strip(),
            entry_mode=entry_mode,
            permit_id=linked_permit,
            entry_time=datetime.now().isoformat(sep=" ", timespec="seconds"),
        )
        self.current_passengers[document_number] = record
        self.logs.append(record)
        self.save_data()
        return record

    def register_exit(self, document_number):
        document_number = document_number.strip().upper()
        if document_number not in self.current_passengers:
            raise ValueError("No active passenger found with that document.")
        record = self.current_passengers.pop(document_number)
        record.exit_time = datetime.now().isoformat(sep=" ", timespec="seconds")
        record.status = "exited"
        self.logs.append(record)
        self.save_data()
        return record

    def issue_permit(self, document_number, permit_id, days=30):
        document_number = document_number.strip().upper()
        if not validate_permit_id(permit_id):
            raise ValueError("Permit ID must be 9 alphanumeric characters and include letters and digits.")
        if permit_id in self.permits:
            raise ValueError("Permit ID already exists.")
        document = self.documents.get(document_number)
        if document is None:
            raise ValueError("Document not found. Register document first.")
        issue_date = date.today().strftime(DATE_FORMAT)
        expiry_date = (date.today() + timedelta(days=days)).strftime(DATE_FORMAT)
        permit = PermitRecord(
            permit_id=permit_id,
            document_number=document_number,
            name=document.name,
            doc_type=document.doc_type,
            issue_date=issue_date,
            expiry_date=expiry_date,
            status="active",
            purpose="entry",
        )
        self.permits[permit_id] = permit
        self.save_data()
        return permit

    def revoke_permit(self, permit_id):
        permit = self.permits.get(permit_id)
        if permit is None:
            raise ValueError("Permit not found.")
        if permit.status == "revoked":
            raise ValueError("Permit is already revoked.")
        permit.status = "revoked"
        self.save_data()
        return permit

    def delete_permit(self, permit_id):
        permit = self.permits.get(permit_id)
        if permit is None:
            raise ValueError("Permit not found.")
        if permit.status != "revoked":
            raise ValueError("Only revoked permits can be deleted.")
        del self.permits[permit_id]
        self.save_data()
        return permit

    def adjust_permit(self, permit_id, action, days=0, new_document_number=None, new_doc_type=None, new_name=None):
        permit = self.permits.get(permit_id)
        if permit is None:
            raise ValueError("Permit not found.")
        if permit.status == "revoked":
            raise ValueError("Revoked permits cannot be modified.")
        if action == "extend":
            try:
                expiry = datetime.strptime(permit.expiry_date, DATE_FORMAT).date()
            except ValueError:
                raise ValueError("Invalid expiry date on permit.")
            expiry = expiry + timedelta(days=days)
            permit.expiry_date = expiry.strftime(DATE_FORMAT)
        elif action == "shorten":
            try:
                expiry = datetime.strptime(permit.expiry_date, DATE_FORMAT).date()
                issue = datetime.strptime(permit.issue_date, DATE_FORMAT).date()
            except ValueError:
                raise ValueError("Invalid date on permit.")
            new_expiry = expiry - timedelta(days=days)
            if new_expiry < issue:
                raise ValueError("Cannot shorten permit before its issue date.")
            permit.expiry_date = new_expiry.strftime(DATE_FORMAT)
        elif action == "cancel":
            permit.status = "revoked"
        elif action == "transfer":
            if not new_document_number:
                raise ValueError("New document number required for transfer.")
            nd = new_document_number.strip().upper()
            permit.document_number = nd
            if new_doc_type:
                permit.doc_type = new_doc_type
            if new_name:
                permit.name = new_name
        else:
            raise ValueError("Unknown adjustment action")
        self.save_data()
        return permit

    def query_document_validity(self, document_number):
        document_number = document_number.strip().upper()
        document = self.documents.get(document_number)
        if document is None:
            raise ValueError("Document not found.")
        return document

    def query_permit_validity(self, permit_id):
        permit = self.permits.get(permit_id)
        if permit is None:
            raise ValueError("Permit not found.")
        return permit

    def list_current_passengers(self):
        return list(self.current_passengers.values())

    def list_permits(self):
        return list(self.permits.values())

    def list_documents(self):
        return list(self.documents.values())

class InputField:
    def __init__(self, label, value="", width=30, required=True, choices=None, mask=False, date_picker=False, auto_upper=False):
        self.label = label
        self.value = value.upper() if auto_upper and isinstance(value, str) else value
        self.width = width
        self.required = required
        self.choices = choices
        self.cursor = len(value)
        self.mask = mask
        self.date_picker = date_picker
        self.auto_upper = auto_upper

    def draw(self, win, y, x, active=False):
        label = f"{self.label}: "
        try:
            max_y, max_x = win.getmaxyx()
        except Exception:
            max_y, max_x = (0, 0)
        # only draw if within window bounds
        if y < 0 or y >= max_y:
            return
        try:
            # draw label (truncate if necessary)
            label_to_draw = display_truncate(label, max(0, max_x - x - 1))
            win.addstr(y, x, label_to_draw, curses.color_pair(3) if active else curses.A_NORMAL)
            field_x = x + display_width(label_to_draw)
            if self.choices and self.value is not None and isinstance(self.choices[0], tuple):
                display_raw = next((f"{c[0]} {c[1]}" for c in self.choices if c[0] == self.value), self.value)
            else:
                display_raw = self.value
            if self.mask:
                display = ("*" * display_width(display_raw))[-(self.width - 1) :]
            else:
                display = display_truncate(display_raw, self.width - 1)
            # ensure we don't write past window edge
            max_field_len = max(0, max_x - field_x - 1)
            padded = display_ljust(display_truncate(display, max_field_len), min(self.width - 1, max_field_len))
            style = curses.color_pair(2) if active else curses.color_pair(1)
            win.attron(style)
            if field_x < max_x:
                win.addstr(y, field_x, padded)
            win.attroff(style)
            if active:
                cursor_pos = field_x + min(self.cursor, max(0, self.width - 2), max_field_len)
                if 0 <= cursor_pos < max_x:
                    win.move(y, cursor_pos)
        except curses.error:
            # drawing out of bounds or other curses error; skip drawing
            return
        except Exception:
            return

    def handle_key(self, key):
        if self.choices:
            choices = self.choices
            if isinstance(choices[0], tuple):
                codes = [c[0] for c in choices]
            else:
                codes = choices
            try:
                index = codes.index(self.value)
            except ValueError:
                index = 0
                self.value = codes[0]
            if key in (curses.KEY_LEFT, curses.KEY_UP):
                self.value = codes[(index - 1) % len(codes)]
                self.cursor = len(self.value)
                return None
            if key in (curses.KEY_RIGHT, curses.KEY_DOWN):
                self.value = codes[(index + 1) % len(codes)]
                self.cursor = len(self.value)
                return None
        if self.date_picker and key in (curses.KEY_BACKSPACE, 127, 8, curses.KEY_DC):
            self.value = ""
            self.cursor = 0
            return None
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.cursor > 0:
                self.value = self.value[: self.cursor - 1] + self.value[self.cursor:]
                self.cursor -= 1
        elif key in (curses.KEY_DC,):
            self.value = self.value[: self.cursor] + self.value[self.cursor + 1 :]
        elif key in (curses.KEY_LEFT,):
            if self.cursor > 0:
                self.cursor -= 1
        elif key in (curses.KEY_RIGHT,):
            if self.cursor < len(self.value):
                self.cursor += 1
        elif key in (curses.KEY_HOME,):
            self.cursor = 0
        elif key in (curses.KEY_END,):
            self.cursor = len(self.value)
        elif 32 <= key <= 126 and not self.choices:
            self.value = self.value[: self.cursor] + chr(key) + self.value[self.cursor:]
            self.cursor += 1
        if self.auto_upper and isinstance(self.value, str):
            self.value = self.value.upper()


class TransactionSwitchRequested(Exception):
    def __init__(self, target_index: int):
        super().__init__(f"Switch transaction to index {target_index}")
        self.target_index = target_index

class Application:
    MENU_ITEMS = [
        "Passenger Arrival",
        "Passenger Departure",
        "Travel Document/Permit Validity Check",
        "Permit Issuance",
        "Permit Adjustment",
        "View Current Passengers",
        "View Current Permits",
        "Settings",
        "Logout",
    ]

    ENTRY_MODES = ["Use existing Visit Permit", "Issue Visit Permit and admit", "Approve stay without Visit Permit"]
    DOC_TYPES = [
        "01 Staff Card",
        "02 Staff Passport",
        "03 ASP",
        "04 SMSP",
        "05 Director Passport",
        "06 DSI",
        "07 Emergency Passport",
    ]
    DOC_TYPE_FULL_NAMES = {
        "01": "Staff Card",
        "02": "Staff Passport",
        "03": "Administrators Staff Passport",
        "04": "Senior Management Staff Passport",
        "05": "Director Passport",
        "06": "Document of Staff Identity",
        "07": "Emergency Passport",
    }
    DOC_VALIDITY_RULES = {
        "01": ("years", 5),
        "02": ("years", 5),
        "03": ("years", 5),
        "04": ("years", 2),
        "05": ("years", 2),
        "06": ("days", 180),
        "07": ("days", 30),
    }

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.system = BorderControlSystem()
        self.settings = self.load_app_settings()
        self.selected = 0
        self.transaction_menu_index = None
        self.transaction_selected_index = 0
        self.transaction_topbar_regions = []
        self._message = "Use arrow keys and Enter. Tab moves between fields."
        self.message_popup_pending = False
        self.height, self.width = self.stdscr.getmaxyx()
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        if hasattr(curses, 'mousemask'):
            curses.mousemask(curses.ALL_MOUSE_EVENTS | getattr(curses, 'REPORT_MOUSE_POSITION', 0))
        if hasattr(curses, 'mouseinterval'):
            curses.mouseinterval(0)
        curses.init_pair(1, curses.COLOR_WHITE, -1)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
        curses.init_pair(3, curses.COLOR_CYAN, -1)
        curses.init_pair(4, curses.COLOR_YELLOW, -1)
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)
        self.user = None

    def load_app_settings(self):
        settings = dict(DEFAULT_APP_SETTINGS)
        ensure_parent_dir(SETTINGS_FILE)
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as file:
                    loaded = json.load(file)
                if isinstance(loaded, dict):
                    settings.update(loaded)
            except Exception:
                pass
        return settings

    def save_app_settings(self):
        ensure_parent_dir(SETTINGS_FILE)
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as file:
            json.dump(self.settings, file, indent=2, ensure_ascii=False)

    def menu_item_label(self, index):
        return self.MENU_ITEMS[index]

    def printer_page_choices(self):
        return [("A4", "A4"), ("A5", "A5"), ("Letter", "Letter"), ("Custom", "Custom")]

    def orientation_choices(self):
        return [("Portrait", "Portrait"), ("Landscape", "Landscape")]

    def network_mode_choices(self):
        return [("WiFi", "WiFi"), ("Ethernet", "Ethernet")]

    def ip_mode_choices(self):
        return [("DHCP", "DHCP"), ("Static", "Static")]

    def run(self):
        # Ensure the terminal is large enough before showing login dialog.
        while True:
            self.height, self.width = self.stdscr.getmaxyx()
            if self.width >= 64 and self.height >= 12:
                break
            self.stdscr.erase()
            self.stdscr.addstr(0, 0, "Please enlarge the terminal to at least 64x12 for login.")
            self.stdscr.addstr(1, 0, "Press Q to quit, or any other key to retry.")
            self.stdscr.refresh()
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return
        # show login first
        if not self.login_dialog():
            return
        while True:
            self.height, self.width = self.stdscr.getmaxyx()
            self.stdscr.erase()
            if self.width < 80 or self.height < 24:
                self.stdscr.addstr(0, 0, "Please enlarge the terminal to at least 80x24.")
                self.stdscr.refresh()
                self.stdscr.getch()
                continue
            self.draw_layout()
            key = self.stdscr.getch()
            # function key shortcuts F1-F9 => menu items
            for fkey in range(1, min(9, len(self.MENU_ITEMS)) + 1):
                f_const = getattr(curses, f"KEY_F{fkey}", None)
                if f_const is not None and key == f_const:
                    self.selected = fkey - 1
                    if not self.execute_menu():
                        return
                    break
            else:
            # shortcuts 1-9 => menu items
                if ord('1') <= key <= ord(str(min(9, len(self.MENU_ITEMS)))):
                    idx = key - ord('1')
                    self.selected = min(idx, len(self.MENU_ITEMS) - 1)
                    if not self.execute_menu():
                        break
                    continue
                if key in (curses.KEY_DOWN, ord("j")):
                    self.selected = (self.selected + 1) % len(self.MENU_ITEMS)
                elif key in (curses.KEY_UP, ord("k")):
                    self.selected = (self.selected - 1) % len(self.MENU_ITEMS)
                elif key in (curses.KEY_ENTER, 10, 13):
                    if not self.execute_menu():
                        break
                elif key == curses.KEY_MOUSE:
                    try:
                        _, mx, my, _, _ = curses.getmouse()
                        sidebar_width = self.get_sidebar_width()
                        if 4 <= my < 4 + len(self.MENU_ITEMS) * 2 and mx < sidebar_width and (my - 4) % 2 == 0:
                            idx = (my - 4) // 2
                            self.selected = min(idx, len(self.MENU_ITEMS) - 1)
                            if not self.execute_menu():
                                break
                    except Exception:
                        pass
                # Ctrl-S (save) or Alt+S (escape then s) to save
                elif key == 19:  # Ctrl-S
                    self.system.save_data()
                    self.message = f"Data saved to {self.system.data_file}."
                elif key == 27:  # possible Alt-<key> sequence
                    # peek next char for Alt shortcuts without blocking long
                    self.stdscr.nodelay(True)
                    try:
                        nxt = self.stdscr.getch()
                    finally:
                        self.stdscr.nodelay(False)
                    if nxt in (ord('s'), ord('S')):
                        self.system.save_data()
                        self.message = f"Data saved to {self.system.data_file}."
                elif key in (ord("q"), ord("Q")):
                    break
            self.stdscr.refresh()

    def draw_layout(self):
        self.draw_header()
        self.draw_sidebar()
        self.draw_footer()

    def get_menu_index_from_fkey(self, key):
        for fkey in range(1, min(9, len(self.MENU_ITEMS)) + 1):
            f_const = getattr(curses, f"KEY_F{fkey}", None)
            if f_const is not None and key == f_const:
                return fkey - 1
        return None

    def transaction_topbar_layout(self):
        items = []
        row = 2
        col = 1
        max_col = max(12, self.width - 2)
        for idx, item in enumerate(self.MENU_ITEMS):
            label = f" F{idx + 1} {item} "
            max_label_len = max(4, max_col - 2)
            if len(label) > max_label_len:
                label = label[:max_label_len]
            if col + len(label) > max_col:
                row += 1
                col = 1
            if row >= self.height - 4:
                break
            items.append((idx, row, col, label))
            col += len(label) + 1
        last_row = items[-1][1] if items else 2
        return items, last_row

    def maybe_switch_transaction_by_key(self, key):
        if self.transaction_menu_index is None:
            return
        target = self.get_menu_index_from_fkey(key)
        if target is None:
            return
        self.transaction_selected_index = target
        if target != self.transaction_menu_index:
            raise TransactionSwitchRequested(target)

    def maybe_switch_transaction_by_mouse(self, mx, my):
        if self.transaction_menu_index is None:
            return
        for row, x1, x2, idx in self.transaction_topbar_regions:
            if my == row and x1 <= mx <= x2:
                self.transaction_selected_index = idx
                if idx != self.transaction_menu_index:
                    raise TransactionSwitchRequested(idx)
                return

    def draw_transaction_topbar(self, current_index, selected_index=None):
        if selected_index is None:
            selected_index = self.transaction_selected_index
        self.draw_header()
        self.transaction_topbar_regions = []
        items, last_row = self.transaction_topbar_layout()
        for idx, row, col, label in items:
            style = curses.color_pair(1)
            if idx == selected_index:
                style = curses.color_pair(2)
            if idx == current_index:
                style = curses.color_pair(5)
            try:
                self.stdscr.addstr(row, col, label, style)
                self.transaction_topbar_regions.append((row, col, col + len(label) - 1, idx))
            except curses.error:
                pass
        separator_row = min(self.height - 4, last_row + 1)
        try:
            self.stdscr.hline(separator_row, 0, curses.ACS_HLINE, self.width)
        except curses.error:
            pass
        self.draw_footer()

    def get_content_rect(self):
        if self.transaction_menu_index is None:
            start_y = 3
            start_x = self.get_sidebar_width() + 2
            height = self.height - 7
            width = self.width - self.get_sidebar_width() - 4
            return start_y, start_x, height, width
        _, last_row = self.transaction_topbar_layout()
        separator_row = min(self.height - 4, last_row + 1)
        start_y = min(self.height - 4, separator_row + 1)
        start_x = 2
        height = self.height - start_y - 3
        width = self.width - 4
        return start_y, start_x, height, width

    def get_sidebar_width(self):
        return max(30, self.width // 4)

    def draw_header(self):
        title = " BORDER CONTROL ENTRY & EXIT MANAGEMENT "
        self.stdscr.attron(curses.color_pair(5))
        header = title.center(self.width)
        if self.user:
            header = (f"User: {self.user} | " + title).center(self.width)
        self.stdscr.addstr(0, 0, header)
        self.stdscr.attroff(curses.color_pair(5))
        self.stdscr.hline(1, 0, curses.ACS_HLINE, self.width)

    def login_dialog(self):
        # simple login dialog: credentials come from settings
        id_field = InputField("Employee ID", self.settings.get("login_user", "XOAPLUQA"), width=40)
        pwd_field = InputField("Password", "", width=40, mask=True)
        active = 0
        attempts = 0
        while True:
            self.height, self.width = self.stdscr.getmaxyx()
            if self.width < 64 or self.height < 12:
                self.stdscr.erase()
                self.stdscr.addstr(0, 0, "Terminal too small for login. Resize to at least 64x12.")
                self.stdscr.addstr(1, 0, "Press Esc to cancel, or any key to retry.")
                self.stdscr.refresh()
                key = self.stdscr.getch()
                if key in (27,):
                    return False
                continue
            window_height = 9
            window_width = min(60, self.width - 4)
            start_y = max(1, (self.height - window_height) // 2)
            start_x = max(2, (self.width - window_width) // 2)
            win = curses.newwin(window_height, window_width, start_y, start_x)
            win.keypad(True)
            win.erase()
            win.border()
            try:
                win.addstr(1, 2, "Login", curses.color_pair(4))
            except curses.error:
                pass
            id_field.draw(win, 3, 2, active == 0)
            pwd_field.draw(win, 5, 2, active == 1)
            try:
                win.addstr(window_height - 2, 2, "Enter: submit | Esc: cancel", curses.color_pair(3))
            except curses.error:
                pass
            self.stdscr.refresh()
            win.refresh()
            curses.curs_set(1)
            key = win.getch()
            if key in (9,):
                active = (active + 1) % 2
                continue
            if key in (27,):
                return False
            if key in (10, 13):
                emp = id_field.value.strip()
                pwd = pwd_field.value.strip()
                if emp == self.settings.get("login_user", "XOAPLUQA") and pwd == self.settings.get("login_password", "123456"):
                    self.user = emp
                    self.message = f"Logged in as {emp}."
                    curses.curs_set(0)
                    return True
                else:
                    attempts += 1
                    self.message = "Invalid credentials."
                    if attempts >= 3:
                        return False
                    continue
            if active == 0:
                id_field.handle_key(key)
            else:
                pwd_field.handle_key(key)

    def draw_sidebar(self):
        sidebar_width = self.get_sidebar_width()
        for row in range(2, self.height - 3):
            self.stdscr.addstr(row, 0, " ".ljust(sidebar_width), curses.color_pair(1))
        self.stdscr.attron(curses.color_pair(4))
        self.stdscr.addstr(2, 2, "MENU")
        self.stdscr.attroff(curses.color_pair(4))
        spacing = 2 if 4 + len(self.MENU_ITEMS) * 2 + 5 <= self.height else 1
        for index, item in enumerate(self.MENU_ITEMS):
            style = curses.color_pair(2) if index == self.selected else curses.color_pair(1)
            item_text = f"{index + 1}/F{index + 1}. {self.menu_item_label(index)}"
            row = 4 + index * spacing
            self.stdscr.addstr(row, 2, display_ljust(display_truncate(item_text, sidebar_width - 4), sidebar_width - 4), style)
        self.stdscr.vline(2, sidebar_width - 1, curses.ACS_VLINE, self.height - 5)
        info = [
            "1-9 or F1-F9: choose menu item",
            "Tab / arrows: move focus",
            "Enter: select",
            "Q: quit",
        ]
        info_start = self.height - 6
        if spacing == 2:
            min_bottom = 4 + len(self.MENU_ITEMS) * spacing + 1
            if min_bottom > info_start:
                info_start = min_bottom
        for idx, text in enumerate(info):
            row = info_start + idx
            if row < self.height - 1:
                self.stdscr.addstr(row, 2, display_truncate(text, sidebar_width - 4))

    def draw_footer(self):
        self.stdscr.hline(self.height - 3, 0, curses.ACS_HLINE, self.width)
        status = self.message[: self.width - 2]
        self.stdscr.addstr(self.height - 2, 0, " " * self.width, curses.color_pair(5))
        self.stdscr.addstr(self.height - 2, 1, status, curses.color_pair(3))
        if self.message_popup_pending and self.message:
            self.display_center_popup(self.message)
            self.message_popup_pending = False

    def display_center_popup(self, message):
        width = min(self.width - 4, max(40, len(message) + 10))
        height = 7
        start_y = max(2, (self.height - height) // 2)
        start_x = max(2, (self.width - width) // 2)
        win = curses.newwin(height, width, start_y, start_x)
        win.keypad(True)
        win.bkgd(' ', curses.color_pair(6))
        win.border()
        try:
            win.addstr(1, 2, "NOTICE", curses.color_pair(4))
            win.addstr(3, 2, message[: width - 4])
            win.addstr(5, 2, "Press any key to continue...", curses.color_pair(3))
        except curses.error:
            pass
        self.stdscr.refresh()
        win.refresh()
        win.getch()

    @property
    def message(self):
        return self._message

    @message.setter
    def message(self, value):
        self._message = value
        self.message_popup_pending = bool(value)

    def execute_menu(self):
        self.transaction_menu_index = self.selected if self.selected < len(self.MENU_ITEMS) else None
        self.transaction_selected_index = self.selected
        try:
            while True:
                try:
                    if self.selected == 0:
                        self.dialog_register_entry()
                    elif self.selected == 1:
                        self.dialog_register_exit()
                    elif self.selected == 2:
                        # combined validity check: ask which to check
                        pick = self.choose_from_list("Travel Document/Permit Validity Check", ["Travel Document", "Permit"])
                        if pick == "Travel Document":
                            self.dialog_query_document()
                        elif pick == "Permit":
                            self.dialog_query_permit()
                    elif self.selected == 3:
                        self.dialog_issue_permit()
                    elif self.selected == 4:
                        # Permit Adjustment (extend/shorten/cancel/transfer)
                        self.dialog_permit_adjustment()
                    elif self.selected == 5:
                        self.dialog_show_current_passengers()
                    elif self.selected == 6:
                        self.dialog_show_permits()
                    elif self.selected == 7:
                        self.dialog_settings()
                    elif self.selected == 8:
                        # Logout: prompt to save
                        pick = self.choose_from_list("Logout", ["Save and logout", "Logout without saving", "Cancel"])
                        if pick == "Save and logout":
                            self.system.save_data()
                            return False
                        if pick == "Logout without saving":
                            return False
                        return True
                    return True
                except TransactionSwitchRequested as nav:
                    self.selected = nav.target_index
                    self.transaction_menu_index = self.selected
                    self.transaction_selected_index = self.selected
                    continue
        except Exception as exc:
            # log full traceback to the writable state directory and show brief message
            ensure_parent_dir(ERROR_LOG_FILE)
            with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"\n--- {datetime.now().isoformat()} ---\n")
                traceback.print_exc(file=f)
            self.show_text_page("Error", [f"An unexpected error occurred: {exc}", f"See {ERROR_LOG_FILE} for details."])
            return True
        finally:
            self.transaction_menu_index = None

    def dialog_register_entry(self):
        fields = [
            InputField("Document type", self.DOC_TYPES[0], required=True, choices=self.DOC_TYPES),
            InputField("Document number", "", required=True, auto_upper=True),
            InputField("Staff ID", "", required=True, auto_upper=True),
            InputField("Surname", "", required=False, auto_upper=True),
            InputField("Given name", "", required=False, auto_upper=True),
            InputField("Middle name", "", required=False, auto_upper=True),
            InputField("Nationality", ISO_COUNTRIES[0][0], required=True, choices=ISO_COUNTRIES),
            InputField("Document Issuing Company", IATA_CHOICES[0][0] if IATA_CHOICES else "", required=True, choices=IATA_CHOICES),
            InputField("Document issue date", "", required=True, date_picker=True),
            InputField("Document expiry", "", required=True, date_picker=True),
        ]
        while True:
            values = self.input_form("Passenger Arrival", fields)
            if values is None:
                self.message = "Entry registration cancelled."
                return
            try:
                document_number = values["Document number"].strip()
                staff_id = values["Staff ID"].strip().upper()
                doc_type_label = values["Document type"].strip()
                doc_type = doc_type_label.split()[0]
                surname = values["Surname"].strip()
                given = values["Given name"].strip()
                middle = values["Middle name"].strip()
                if middle and (not surname or not given):
                    raise ValueError("If Middle name is provided, both Surname and Given name must be provided.")
                if not (surname or given):
                    raise ValueError("At least Surname or Given name must be provided.")
                name = f"{surname} {given} {middle}".strip()
                nationality = values["Nationality"].strip()
                issuing_company = values["Document Issuing Company"].strip()
                issue_date_raw = values["Document issue date"].strip()
                expiry_date_raw = values["Document expiry"].strip()
                if not expiry_date_raw:
                    try:
                        issue_date_for_default = parse_date_fuzzy(issue_date_raw)
                    except DateAmbiguityError as amb:
                        pick = self.choose_from_list("Ambiguous issue date", amb.candidates)
                        if pick is None:
                            self.message = "Issue date selection cancelled."
                            continue
                        issue_date_for_default = pick
                    options = self.get_document_expiry_candidates(doc_type, issue_date_for_default)
                    if options:
                        pick = self.choose_from_list("Select document expiry", options + ["Manual input"])
                        if pick is None:
                            self.message = "Expiry selection cancelled."
                            continue
                        if pick == "Manual input":
                            manual = self.input_form("Manual expiry date", [InputField("Document expiry", "", required=True, date_picker=True)])
                            if manual is None:
                                self.message = "Expiry input cancelled."
                                continue
                            expiry_date_raw = manual["Document expiry"].strip()
                        else:
                            expiry_date_raw = pick
                # parse dates
                try:
                    issue_date = parse_date_fuzzy(issue_date_raw)
                except DateAmbiguityError as amb:
                    pick = self.choose_from_list("Ambiguous issue date", amb.candidates)
                    if pick is None:
                        self.message = "Issue date selection cancelled."
                        continue
                    issue_date = pick
                try:
                    expiry_date = parse_date_fuzzy(expiry_date_raw)
                except DateAmbiguityError as amb:
                    pick = self.choose_from_list("Ambiguous expiry date", amb.candidates)
                    if pick is None:
                        self.message = "Expiry date selection cancelled."
                        continue
                    expiry_date = pick
                issue_date_obj = datetime.strptime(issue_date, DATE_FORMAT).date()
                expiry_date_obj = datetime.strptime(expiry_date, DATE_FORMAT).date()
                validate_document_dates(issue_date_obj, expiry_date_obj)
                if not issuing_company or issuing_company not in [c[0] for c in IATA_CHOICES]:
                    raise ValueError("Document Issuing Company must be selected from the list.")
                if not validate_staff_id(staff_id):
                    raise ValueError("Staff ID must be exactly 8 letters (A-Z).")
                entry_mode = "Approve stay without Visit Permit"
                permit_id = ""
                permit_days = 0
                if doc_type != "01":
                    mode_values = self.input_form(
                        "Permit details",
                        [InputField("Entry mode", self.ENTRY_MODES[0], required=True, choices=self.ENTRY_MODES)],
                    )
                    if mode_values is None:
                        self.message = "Entry registration cancelled."
                        continue
                    entry_mode = mode_values["Entry mode"]
                    if entry_mode == "Use existing Visit Permit":
                        permit_values = self.input_form("Permit details", [InputField("Permit ID", "", required=True, auto_upper=True)])
                        if permit_values is None:
                            self.message = "Entry registration cancelled."
                            continue
                        permit_id = permit_values["Permit ID"].strip().upper()
                        permit_days = 30
                    elif entry_mode == "Issue Visit Permit and admit":
                        days_values = self.input_form("Permit details", [InputField("Permit days", "30", required=True)])
                        if days_values is None:
                            self.message = "Entry registration cancelled."
                            continue
                        permit_days = int(days_values["Permit days"] or "30")
                        permit_id = ""
                    else:
                        permit_days = 0
                        permit_id = ""
                # validate document format
                if not validate_document_format(doc_type, document_number, issuing_company):
                    raise ValueError(f"Document number does not match issuer/type rule for {doc_type}.")
                # validate nationality exists in list (simple match)
                if nationality not in [c[0] for c in ISO_COUNTRIES]:
                    raise ValueError("Nationality code not recognized. Use the ISO country code list.")
                record = self.system.register_entry(
                    document_number,
                    doc_type,
                    name,
                    staff_id,
                    nationality,
                    expiry_date,
                    issuing_company,
                    entry_mode,
                    permit_id=permit_id,
                    permit_days=permit_days,
                )
                self.message = f"Entry recorded for {record.name} via {record.entry_mode}."
                return
            except Exception as exc:
                self.message = f"Error: {exc}"

    def dialog_register_exit(self):
        field = InputField("Document number", "", required=True, auto_upper=True)
        while True:
            values = self.input_form("Passenger Departure", [field])
            if values is None:
                self.message = "Departure registration cancelled."
                return
            try:
                record = self.system.register_exit(values["Document number"])
                self.message = f"Departure recorded for {record.name}."
                return
            except Exception as exc:
                self.message = f"Error: {exc}"

    def dialog_query_document(self):
        field = InputField("Document number", "", required=True, auto_upper=True)
        while True:
            values = self.input_form("Travel Document Validity Check", [field])
            if values is None:
                self.message = "Document query cancelled."
                return
            try:
                document = self.system.query_document_validity(values["Document number"])
                self.show_text_page("Document validity", self.format_document(document))
                self.message = "Document query complete."
                return
            except Exception as exc:
                self.message = f"Error: {exc}"

    def dialog_query_permit(self):
        field = InputField("Permit ID", "", required=True)
        while True:
            values = self.input_form("Permit Validity Check", [field])
            if values is None:
                self.message = "Permit query cancelled."
                return
            try:
                permit = self.system.query_permit_validity(values["Permit ID"])
                self.show_text_page("Permit validity", self.format_permit(permit))
                self.message = "Permit query complete."
                return
            except Exception as exc:
                self.message = f"Error: {exc}"

    def dialog_issue_permit(self):
        fields = [
            InputField("Document number", "", required=True, auto_upper=True),
            InputField("Permit days", "30", required=True),
        ]
        while True:
            values = self.input_form("Issue permit", fields)
            if values is None:
                self.message = "Permit issuance cancelled."
                return
            try:
                permit_id = generate_permit_id()
                while permit_id in self.system.permits:
                    permit_id = generate_permit_id()
                permit = self.system.issue_permit(
                    values["Document number"],
                    permit_id,
                    int(values["Permit days"]),
                )
                self.message = f"Permit issued: {permit.permit_id}."
                return
            except Exception as exc:
                self.message = f"Error: {exc}"

    def dialog_revoke_permit(self):
        active_permits = [p.permit_id for p in self.system.list_permits() if p.status != "revoked"]
        if not active_permits:
            self.message = "No active permits available to revoke."
            return
        permit_id = self.choose_from_list("Revoke permit", active_permits)
        if permit_id is None:
            self.message = "Permit revocation cancelled."
            return
        try:
            permit = self.system.revoke_permit(permit_id)
            self.message = f"Permit {permit.permit_id} revoked."
        except Exception as exc:
            self.message = f"Error: {exc}"

    def dialog_settings(self):
        change_password = "Change current user password"
        printer = "Printer"
        networking = "Networking"
        about = "About System"
        back = "Back"
        while True:
            pick = self.choose_from_list(
                "Settings",
                [
                    change_password,
                    printer,
                    networking,
                    about,
                    back,
                ],
            )
            if pick is None or pick == back:
                return
            try:
                if pick == change_password:
                    self.dialog_change_password()
                    return
                if pick == printer:
                    self.dialog_printer_settings()
                    return
                if pick == networking:
                    self.dialog_network_settings()
                    return
                if pick == about:
                    self.dialog_about_system()
                    return
            except Exception as exc:
                self.message = f"Error: {exc}"

    def dialog_change_password(self):
        fields = [
            InputField("Current password", "", required=True, mask=True),
            InputField("New password", "", required=True, mask=True),
            InputField("Confirm password", "", required=True, mask=True),
        ]
        while True:
            values = self.input_form("Change password", fields)
            if values is None:
                self.message = "Password change cancelled."
                return
            try:
                if values["Current password"] != self.settings.get("login_password", "123456"):
                    raise ValueError("Current password is incorrect.")
                new_password = values["New password"]
                confirm_password = values["Confirm password"]
                if len(new_password) < 4:
                    raise ValueError("Password must be at least 4 characters.")
                if new_password != confirm_password:
                    raise ValueError("Password confirmation does not match.")
                self.settings["login_password"] = new_password
                self.save_app_settings()
                self.message = "Password updated."
                return
            except Exception as exc:
                self.message = f"Error: {exc}"

    def dialog_printer_settings(self):
        while True:
            pick = self.choose_from_list(
                "Printer",
                ["Select printer", "Print size", "Page settings", "Back"],
            )
            if pick is None or pick == "Back":
                return
            if pick == "Select printer":
                printer_pick = self.choose_from_list(
                    "Select printer",
                    ["Default Printer", "Microsoft Print to PDF", "XPS Document Writer", "Custom"],
                )
                if printer_pick is None:
                    continue
                if printer_pick == "Custom":
                    vals = self.input_form("Custom printer", [InputField("Printer name", self.settings.get("printer_name", ""), required=True)])
                    if vals is None:
                        continue
                    self.settings["printer_name"] = vals["Printer name"]
                else:
                    self.settings["printer_name"] = printer_pick
                self.save_app_settings()
                self.message = f"Printer set to {self.settings['printer_name']}."
                return
            if pick == "Print size":
                size_pick = self.choose_from_list("Print size", ["A4", "A5", "Letter", "Custom"])
                if size_pick is None:
                    continue
                if size_pick == "Custom":
                    vals = self.input_form(
                        "Custom print size",
                        [
                            InputField("Custom width", self.settings.get("print_size_custom_width", ""), required=True),
                            InputField("Custom height", self.settings.get("print_size_custom_height", ""), required=True),
                        ],
                    )
                    if vals is None:
                        continue
                    self.settings["print_size"] = "Custom"
                    self.settings["print_size_custom_width"] = vals["Custom width"]
                    self.settings["print_size_custom_height"] = vals["Custom height"]
                    self.save_app_settings()
                    self.message = f"Print size set to custom {vals['Custom width']} x {vals['Custom height']}."
                    return
                self.settings["print_size"] = size_pick
                self.settings["print_size_custom_width"] = ""
                self.settings["print_size_custom_height"] = ""
                self.save_app_settings()
                self.message = f"Print size set to {size_pick}."
                return
            if pick == "Page settings":
                orient_pick = self.choose_from_list("Page orientation", ["Portrait", "Landscape"])
                if orient_pick is None:
                    continue
                self.settings["page_orientation"] = orient_pick
                self.save_app_settings()
                self.message = f"Page orientation set to {orient_pick}."
                return

    def dialog_network_settings(self):
        while True:
            pick = self.choose_from_list(
                "Networking",
                ["Connection mode", "WiFi settings", "IP settings", "Server IP", "Back"],
            )
            if pick is None or pick == "Back":
                return
            if pick == "Connection mode":
                mode_pick = self.choose_from_list("Connection mode", ["WiFi", "Ethernet"])
                if mode_pick is None:
                    continue
                self.settings["network_mode"] = mode_pick
                self.save_app_settings()
                self.message = f"Network mode set to {mode_pick}."
                return
            if pick == "WiFi settings":
                vals = self.input_form(
                    "WiFi settings",
                    [
                        InputField("WiFi SSID", self.settings.get("wifi_ssid", ""), required=False),
                        InputField("WiFi password", self.settings.get("wifi_password", ""), required=False, mask=True),
                    ],
                )
                if vals is None:
                    continue
                self.settings["wifi_ssid"] = vals["WiFi SSID"]
                self.settings["wifi_password"] = vals["WiFi password"]
                self.save_app_settings()
                self.message = "WiFi settings updated."
                return
            if pick == "IP settings":
                vals = self.input_form(
                    "IP settings",
                    [
                        InputField("IP mode", self.settings.get("ip_mode", "DHCP"), required=True, choices=self.ip_mode_choices()),
                        InputField("IP address", self.settings.get("ip_address", ""), required=False),
                        InputField("Subnet mask", self.settings.get("subnet_mask", ""), required=False),
                        InputField("Gateway", self.settings.get("gateway", ""), required=False),
                        InputField("DNS", self.settings.get("dns", ""), required=False),
                    ],
                )
                if vals is None:
                    continue
                self.settings["ip_mode"] = vals["IP mode"]
                self.settings["ip_address"] = vals["IP address"]
                self.settings["subnet_mask"] = vals["Subnet mask"]
                self.settings["gateway"] = vals["Gateway"]
                self.settings["dns"] = vals["DNS"]
                self.save_app_settings()
                self.message = "IP settings updated."
                return
            if pick == "Server IP":
                vals = self.input_form("Server IP", [InputField("Server IP", self.settings.get("server_ip", ""), required=False)])
                if vals is None:
                    continue
                self.settings["server_ip"] = vals["Server IP"]
                self.save_app_settings()
                self.message = "Server IP updated."
                return

    def dialog_about_system(self):
        lines = [
            "Border Control Entry & Exit Management",
            f"User: {self.user or self.settings.get('login_user', 'XOAPLUQA')}",
            f"Printer: {self.settings.get('printer_name', 'Default Printer')}",
            f"Print size: {self.settings.get('print_size', 'A4')}"
            + (
                f" ({self.settings.get('print_size_custom_width', '')} x {self.settings.get('print_size_custom_height', '')})"
                if self.settings.get('print_size') == 'Custom'
                else ""
            ),
            f"Page orientation: {self.settings.get('page_orientation', 'Portrait')}",
            f"Network mode: {self.settings.get('network_mode', 'WiFi')}",
            f"WiFi SSID: {self.settings.get('wifi_ssid', '') or '(empty)'}",
            f"IP mode: {self.settings.get('ip_mode', 'DHCP')}",
            f"Server IP: {self.settings.get('server_ip', '') or '(empty)'}",
            f"Settings file: {SETTINGS_FILE}",
        ]
        self.show_text_page("About System", lines)

    def dialog_permit_adjustment(self):
        if not self.system.permits:
            self.message = "No permits available to adjust."
            return
        permit_id = self.choose_from_list("Permit Adjustment - select permit", [p.permit_id for p in self.system.list_permits()])
        if permit_id is None:
            self.message = "Permit adjustment cancelled."
            return
        permit = self.system.permits.get(permit_id)
        if permit is None:
            self.message = "Permit not found."
            return
        if permit.status == "revoked":
            action = self.choose_from_list("Action", ["Delete revoked permit", "Cancel"])
        else:
            action = self.choose_from_list("Action", ["Extend", "Shorten", "Cancel", "Transfer"])
        if action is None or action == "Cancel":
            self.message = "Permit adjustment cancelled."
            return
        try:
            if action == "Delete revoked permit":
                deleted = self.system.delete_permit(permit_id)
                self.message = f"Revoked permit {deleted.permit_id} deleted."
                return
            if action == "Extend":
                fields = [InputField("Days to extend", "30", required=True)]
                vals = self.input_form("Extend permit", fields)
                if vals is None:
                    self.message = "Extend cancelled."
                    return
                days = int(vals["Days to extend"])
                permit = self.system.adjust_permit(permit_id, "extend", days=days)
                self.show_text_page("Permit updated", self.format_permit(permit))
                self.message = f"Permit {permit.permit_id} extended by {days} days."
            elif action == "Shorten":
                fields = [InputField("Days to shorten", "1", required=True)]
                vals = self.input_form("Shorten permit", fields)
                if vals is None:
                    self.message = "Shorten cancelled."
                    return
                days = int(vals["Days to shorten"])
                permit = self.system.adjust_permit(permit_id, "shorten", days=days)
                self.show_text_page("Permit updated", self.format_permit(permit))
                self.message = f"Permit {permit.permit_id} shortened by {days} days."
            elif action == "Cancel":
                pick = self.choose_from_list("Confirm cancel", ["Yes", "No"])
                if pick == "Yes":
                    permit = self.system.adjust_permit(permit_id, "cancel")
                    self.show_text_page("Permit updated", self.format_permit(permit))
                    self.message = f"Permit {permit.permit_id} cancelled."
                else:
                    self.message = "Cancel aborted."
            elif action == "Transfer":
                fields = [
                    InputField("New Document number", "", required=True, auto_upper=True),
                    InputField("New Document type", "", required=False),
                    InputField("New holder name", "", required=False, auto_upper=True),
                ]
                vals = self.input_form("Transfer permit", fields)
                if vals is None:
                    self.message = "Transfer cancelled."
                    return
                nd = vals["New Document number"]
                ndt = vals["New Document type"] or None
                nn = vals["New holder name"] or None
                permit = self.system.adjust_permit(permit_id, "transfer", new_document_number=nd, new_doc_type=ndt, new_name=nn)
                self.show_text_page("Permit updated", self.format_permit(permit))
                self.message = f"Permit {permit.permit_id} transferred to {permit.document_number}."
        except Exception as exc:
            self.message = f"Error: {exc}"

    def dialog_show_current_passengers(self):
        records = self.system.list_current_passengers()
        if not records:
            self.message = "No current passengers."
            return
        lines = []
        for record in records:
            lines.append(
                f"{record.name} | {record.doc_type} {record.document_number} | {record.entry_mode} | entered {record.entry_time}"
            )
        self.show_text_page("Current passengers", lines)
        self.message = "Displayed current passengers."

    def dialog_show_permits(self):
        records = self.system.list_permits()
        if not records:
            self.message = "No permits recorded."
            return
        lines = []
        for permit in records:
            valid = "valid" if permit.is_valid() else permit.status
            lines.append(
                f"{permit.permit_id} | {permit.name} | {permit.doc_type} {permit.document_number} | {permit.issue_date} -> {permit.expiry_date} | {valid}"
            )
        self.show_text_page("Permit records", lines)
        self.message = "Displayed permits."

    def open_date_picker(self, title, current_value):
        try:
            selected_date = datetime.strptime(current_value, DATE_FORMAT).date()
        except Exception:
            selected_date = date.today()
        while True:
            year = selected_date.year
            month = selected_date.month
            cal_rows = calendar.monthcalendar(year, month)
            content_start_y, content_start_x, content_height, content_width = self.get_content_rect()
            window_height = min(content_height, len(cal_rows) + 10)
            window_width = content_width
            start_y = content_start_y
            start_x = content_start_x
            win = curses.newwin(window_height, window_width, start_y, start_x)
            win.keypad(True)
            if self.transaction_menu_index is not None:
                self.stdscr.erase()
                self.draw_transaction_topbar(self.transaction_menu_index, self.transaction_selected_index)
            win.erase()
            win.border()
            header = f"{calendar.month_name[month]} {year}"
            win.addstr(1, 2, title, curses.color_pair(4))
            win.addstr(2, 2, header[: window_width - 4], curses.color_pair(3))
            week_header = "Mo Tu We Th Fr Sa Su"
            win.addstr(3, 2, week_header[: window_width - 4])
            for row_idx, week in enumerate(cal_rows):
                y = 4 + row_idx
                x = 2
                for day in week:
                    day_str = "  " if day == 0 else f"{day:2d}"
                    style = curses.color_pair(1)
                    if day == selected_date.day and selected_date.month == month and selected_date.year == year:
                        style = curses.color_pair(2)
                    try:
                        win.addstr(y, x, day_str, style)
                    except curses.error:
                        pass
                    x += 3
            hint = "Arrows: move | n/p: month | y/Y: year | Enter: accept | Esc: cancel"
            try:
                win.addstr(window_height - 3, 2, hint[: window_width - 4], curses.color_pair(3))
            except curses.error:
                pass
            self.stdscr.refresh()
            win.refresh()
            key = win.getch()
            self.maybe_switch_transaction_by_key(key)
            if key in (curses.KEY_LEFT, ord('h')):
                selected_date -= timedelta(days=1)
            elif key in (curses.KEY_RIGHT, ord('l')):
                selected_date += timedelta(days=1)
            elif key in (curses.KEY_UP, ord('k')):
                selected_date -= timedelta(days=7)
            elif key in (curses.KEY_DOWN, ord('j')):
                selected_date += timedelta(days=7)
            elif key in (ord('n'),):
                next_month = month + 1 if month < 12 else 1
                next_year = year + 1 if month == 12 else year
                selected_date = date(next_year, next_month, min(selected_date.day, calendar.monthrange(next_year, next_month)[1]))
            elif key in (ord('p'),):
                prev_month = month - 1 if month > 1 else 12
                prev_year = year - 1 if month == 1 else year
                selected_date = date(prev_year, prev_month, min(selected_date.day, calendar.monthrange(prev_year, prev_month)[1]))
            elif key in (ord('y'),):
                next_year = year + 1
                selected_date = date(next_year, month, min(selected_date.day, calendar.monthrange(next_year, month)[1]))
            elif key in (ord('Y'),):
                prev_year = year - 1
                selected_date = date(prev_year, month, min(selected_date.day, calendar.monthrange(prev_year, month)[1]))
            elif key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                    self.maybe_switch_transaction_by_mouse(mx, my)
                    if start_y + 4 <= my < start_y + 4 + len(cal_rows) and start_x + 2 <= mx < start_x + 2 + 21:
                        row = my - start_y - 4
                        col = (mx - start_x - 2) // 3
                        if 0 <= row < len(cal_rows) and 0 <= col < 7:
                            day = cal_rows[row][col]
                            if day:
                                selected_date = date(year, month, day)
                                continue
                except Exception:
                    pass
            elif key in (10, 13):
                return selected_date.strftime(DATE_FORMAT)
            elif key == 27:
                return None
            # keep selected_date within valid range
            if selected_date.day < 1:
                selected_date = date(selected_date.year, selected_date.month, 1)
            if selected_date.day > calendar.monthrange(selected_date.year, selected_date.month)[1]:
                selected_date = date(selected_date.year, selected_date.month, calendar.monthrange(selected_date.year, selected_date.month)[1])

    def format_document(self, document):
        valid_text = "VALID" if document.is_valid() else "INVALID"
        full_name = self.DOC_TYPE_FULL_NAMES.get(document.doc_type, document.doc_type)
        return [
            f"Document: {document.doc_type} {full_name} | {document.document_number}",
            f"Name: {document.name}",
            f"Staff ID: {document.staff_id}",
            f"Nationality: {document.nationality}",
            f"Expiry date: {document.expiry_date}",
            f"Status: {document.status}",
            f"Validity: {valid_text}",
        ]

    def format_permit(self, permit):
        valid_text = "VALID" if permit.is_valid() else "INVALID"
        return [
            f"Permit ID: {permit.permit_id}",
            f"Holder: {permit.name}",
            f"Document: {permit.doc_type} {permit.document_number}",
            f"Issue date: {permit.issue_date}",
            f"Expiry date: {permit.expiry_date}",
            f"Status: {permit.status}",
            f"Validity: {valid_text}",
        ]

    def get_document_expiry_candidates(self, doc_type, issue_date_str):
        try:
            issue = datetime.strptime(issue_date_str, DATE_FORMAT).date()
        except Exception:
            return []
        rule = self.DOC_VALIDITY_RULES.get(doc_type)
        if not rule:
            return []
        mode, amount = rule
        if mode == "years":
            primary = add_years(issue, amount)
        else:
            primary = issue + timedelta(days=amount)
        secondary = primary - timedelta(days=1)
        values = []
        for dt in (primary, secondary):
            s = dt.strftime(DATE_FORMAT)
            if s not in values:
                values.append(s)
        return values

    def maybe_offer_default_expiry(self, fields, issue_field_index):
        issue_field = fields[issue_field_index]
        issue_value = issue_field.value.strip()
        if not issue_value:
            return True
        expiry_field = next((f for f in fields if f.label == "Document expiry"), None)
        doc_type_field = next((f for f in fields if f.label == "Document type"), None)
        if expiry_field is None or doc_type_field is None:
            return True
        if expiry_field.value.strip():
            return True
        doc_type = doc_type_field.value.split()[0]
        options = self.get_document_expiry_candidates(doc_type, issue_value)
        if not options:
            return True
        pick = self.choose_from_list("Select document expiry", options + ["Manual input"])
        if pick is None:
            self.message = "Expiry selection cancelled."
            return False
        if pick == "Manual input":
            return True
        expiry_field.value = pick
        expiry_field.cursor = len(expiry_field.value)
        return True

    def normalize_date_field_value(self, field):
        raw = field.value.strip()
        if not raw:
            return True
        candidates = parse_date_candidates(raw)
        if not candidates:
            self.message = f"Invalid date format: {raw}"
            return False
        if len(candidates) == 1:
            field.value = candidates[0]
            field.cursor = len(field.value)
            return True
        pick = self.choose_from_list("Ambiguous date - choose one", candidates)
        if pick is None:
            self.message = "Date selection cancelled."
            return False
        field.value = pick
        field.cursor = len(field.value)
        return True

    def input_form(self, title, fields):
        # layout: try single column; if not enough vertical space, use two columns
        total = len(fields)
        single_req_height = 3 + total * 2 + 3
        avail_height = self.height - 7
        two_columns = single_req_height > avail_height
        if two_columns:
            rows = (total + 1) // 2
            window_height = min(self.height - 4, 3 + rows * 2 + 3)
        else:
            window_height = min(self.height - 4, single_req_height)
        content_start_y, content_start_x, content_height, content_width = self.get_content_rect()
        window_width = content_width
        start_y = content_start_y
        start_x = content_start_x
        win = curses.newwin(window_height, window_width, start_y, start_x)
        win.keypad(True)
        active = 0
        scroll = 0
        initial_values = [field.value for field in fields]
        esc_armed = False

        def is_dirty():
            for idx, field in enumerate(fields):
                if field.value != initial_values[idx]:
                    return True
            return False

        while True:
            win.erase()
            win.border()
            win.addstr(1, 2, title, curses.color_pair(4))
            if two_columns:
                # draw in two columns so all fields fit vertically
                left_x = 2
                right_x = 2 + window_width // 2
                for idx, field in enumerate(fields):
                    col = idx % 2
                    row_idx = idx // 2
                    y = 3 + row_idx * 2
                    x = left_x if col == 0 else right_x
                    if y >= window_height - 4:
                        continue
                    field.draw(win, y, x, active == idx)
            else:
                for idx, field in enumerate(fields[scroll:]):
                    row = 3 + idx * 2
                    if row >= window_height - 4:
                        break
                    field.draw(win, row, 2, active == scroll + idx)
            if fields[active].choices and fields[active].date_picker:
                help_text = "Tab: next | Ctrl-D/F12: search | Ctrl-E: calendar | Enter: submit | Esc: cancel"
            elif fields[active].choices:
                help_text = "Tab: next | Ctrl-D/F12: search | Enter: submit | Esc: cancel"
            elif fields[active].date_picker:
                help_text = "Tab: next | Ctrl-E: calendar | Enter: submit | Esc: cancel"
            else:
                help_text = "Tab: next | Enter: submit | Esc: cancel"
            try:
                win.addstr(window_height - 3, 2, help_text[: window_width - 4], curses.color_pair(3))
            except curses.error:
                pass
            if self.transaction_menu_index is not None:
                self.stdscr.erase()
                self.draw_transaction_topbar(self.transaction_menu_index, self.transaction_selected_index)
            self.stdscr.refresh()
            win.refresh()
            curses.curs_set(1)
            key = win.getch()
            self.maybe_switch_transaction_by_key(key)
            if key != 27:
                esc_armed = False
            visible_count = max(1, (window_height - 6) // 2)
            if key in (9, curses.KEY_BTAB):
                if fields[active].date_picker:
                    if not self.normalize_date_field_value(fields[active]):
                        continue
                    if fields[active].label == "Document issue date":
                        if not self.maybe_offer_default_expiry(fields, active):
                            continue
                active = (active + 1) % len(fields)
                if not two_columns:
                    if active >= scroll + visible_count:
                        scroll = active - visible_count + 1
                    elif active < scroll:
                        scroll = active
                continue
            if key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                    self.maybe_switch_transaction_by_mouse(mx, my)
                    if start_y <= my < start_y + window_height and start_x <= mx < start_x + window_width:
                        rel_y = my - start_y - 3
                        if rel_y >= 0:
                            if two_columns:
                                if rel_y % 2 == 0:
                                    row = rel_y // 2
                                    if row >= 0:
                                        left_region = start_x + 2 + window_width // 2
                                        if mx < left_region:
                                            candidate = row * 2
                                        else:
                                            candidate = row * 2 + 1
                                        if 0 <= candidate < len(fields):
                                            active = candidate
                                            if active >= scroll + visible_count:
                                                scroll = active - visible_count + 1
                                            elif active < scroll:
                                                scroll = active
                                            continue
                            else:
                                if rel_y % 2 == 0:
                                    candidate = rel_y // 2
                                    if 0 <= candidate < len(fields):
                                        active = candidate
                                        if active >= scroll + visible_count:
                                            scroll = active - visible_count + 1
                                        elif active < scroll:
                                            scroll = active
                                        continue
                except Exception:
                    pass
            # Ctrl-D or F12 to search choices if available
            f12_key = getattr(curses, "KEY_F12", None)
            if fields[active].choices and (key == 4 or (f12_key is not None and key == f12_key)):
                qwin = curses.newwin(6, min(max(40, self.width - self.get_sidebar_width() - 8), self.width - 4), start_y + 2, start_x + 2)
                qwin.border()
                qwin.addstr(1, 2, "Search: ", curses.color_pair(4))
                curses.curs_set(1)
                qwin.refresh()
                query = ""
                while True:
                    try:
                        qwin.addstr(2, 2, (query + " ")[: qwin.getmaxyx()[1] - 4])
                    except curses.error:
                        pass
                    qwin.clrtoeol()
                    qwin.move(2, 2 + len(query))
                    ch = qwin.getch()
                    self.maybe_switch_transaction_by_key(ch)
                    if ch == curses.KEY_MOUSE:
                        try:
                            _, mx, my, _, _ = curses.getmouse()
                            self.maybe_switch_transaction_by_mouse(mx, my)
                            continue
                        except Exception:
                            pass
                    if ch in (10, 13):
                        break
                    if ch == 27:
                        query = ""
                        break
                    if ch in (8, 127):
                        query = query[:-1]
                    elif 32 <= ch <= 126:
                        query += chr(ch)
                curses.curs_set(0)
                choices = fields[active].choices
                matches = fuzzy_search_choices(choices, query)
                if matches:
                    pick = self.choose_from_list("Search results", [choice_display(m) for m in matches])
                    if pick:
                        if isinstance(pick, str) and " " in pick:
                            fields[active].value = pick.split()[0]
                        else:
                            fields[active].value = pick
                        fields[active].cursor = len(fields[active].value)
                continue
            if key == 5 and fields[active].date_picker:
                new_date = self.open_date_picker(fields[active].label, fields[active].value)
                if new_date:
                    fields[active].value = new_date
                    fields[active].cursor = len(new_date)
                continue
            if key in (curses.KEY_UP,):
                # move up one field (in two-column layout, move two steps when appropriate)
                if two_columns:
                    # if in bottom row, jump up by 1 or 2
                    active = (active - 1) % len(fields)
                else:
                    active = (active - 1) % len(fields)
                    if active < scroll:
                        scroll = active
                continue
            if key in (curses.KEY_DOWN,):
                if two_columns:
                    active = (active + 1) % len(fields)
                else:
                    active = (active + 1) % len(fields)
                    if active >= scroll + visible_count:
                        scroll = active - visible_count + 1
                continue
            if key in (27,):
                if is_dirty() and not esc_armed:
                    self.message = "Press Esc again to cancel and discard entered values."
                    esc_armed = True
                    continue
                curses.curs_set(0)
                return None
            if key in (10, 13):
                ok = True
                for field in fields:
                    if field.date_picker:
                        if not self.normalize_date_field_value(field):
                            ok = False
                            break
                if ok:
                    issue_idx = next((idx for idx, f in enumerate(fields) if f.label == "Document issue date"), None)
                    if issue_idx is not None:
                        ok = self.maybe_offer_default_expiry(fields, issue_idx)
                if not ok:
                    continue
                if all((not field.required or field.value.strip()) for field in fields):
                    curses.curs_set(0)
                    return {field.label: field.value.strip() for field in fields}
                self.message = "Please fill required fields."
                continue
            fields[active].handle_key(key)

    def choose_from_list(self, title, options):
        selected = 0
        content_start_y, content_start_x, content_height, content_width = self.get_content_rect()
        window_height = min(content_height, len(options) * 2 + 8)
        window_width = content_width
        start_y = content_start_y
        start_x = content_start_x
        win = curses.newwin(window_height, window_width, start_y, start_x)
        win.keypad(True)
        visible_count = max(1, (window_height - 8) // 2)
        while True:
            win.erase()
            win.border()
            win.addstr(1, 2, title, curses.color_pair(4))
            visible = options[:visible_count]
            for idx, line in enumerate(visible):
                y = 3 + idx * 2
                style = curses.color_pair(2) if idx == selected else curses.color_pair(1)
                try:
                    win.addstr(y, 2, display_ljust(display_truncate(line, window_width - 4), window_width - 4), style)
                except curses.error:
                    pass
            try:
                win.addstr(window_height - 3, 2, "Enter: select | Esc: cancel", curses.color_pair(3))
            except curses.error:
                pass
            if self.transaction_menu_index is not None:
                self.stdscr.erase()
                self.draw_transaction_topbar(self.transaction_menu_index, self.transaction_selected_index)
            self.stdscr.refresh()
            win.refresh()
            key = win.getch()
            self.maybe_switch_transaction_by_key(key)
            if key in (curses.KEY_DOWN, ord("j")):
                selected = (selected + 1) % len(visible)
            elif key in (curses.KEY_UP, ord("k")):
                selected = (selected - 1) % len(visible)
            elif key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                    self.maybe_switch_transaction_by_mouse(mx, my)
                    rel_y = my - start_y - 3
                    if 0 <= rel_y < visible_count * 2 and rel_y % 2 == 0 and 0 <= mx - start_x - 2 < window_width - 4:
                        idx = rel_y // 2
                        if 0 <= idx < len(visible):
                            return visible[idx]
                except Exception:
                    pass
            elif key in (10, 13):
                return visible[selected]
            elif key == 27:
                return None

    def show_text_page(self, title, lines):
        content_start_y, content_start_x, content_height, content_width = self.get_content_rect()
        window_height = content_height
        window_width = content_width
        start_y = content_start_y
        start_x = content_start_x
        win = curses.newwin(window_height, window_width, start_y, start_x)
        win.keypad(True)
        scroll = 0
        while True:
            win.erase()
            win.border()
            win.addstr(1, 2, title, curses.color_pair(4))
            max_lines = window_height - 6
            for idx in range(max_lines):
                if scroll + idx >= len(lines):
                    break
                try:
                    win.addstr(3 + idx, 2, display_truncate(lines[scroll + idx], window_width - 4))
                except curses.error:
                    pass
            try:
                win.addstr(window_height - 3, 2, "Up/Down: scroll | Esc: back", curses.color_pair(3))
            except curses.error:
                pass
            if self.transaction_menu_index is not None:
                self.stdscr.erase()
                self.draw_transaction_topbar(self.transaction_menu_index, self.transaction_selected_index)
            self.stdscr.refresh()
            win.refresh()
            key = win.getch()
            self.maybe_switch_transaction_by_key(key)
            if key in (curses.KEY_DOWN, ord("j")) and scroll + max_lines < len(lines):
                scroll += 1
            elif key in (curses.KEY_UP, ord("k")) and scroll > 0:
                scroll -= 1
            elif key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                    self.maybe_switch_transaction_by_mouse(mx, my)
                except Exception:
                    pass
            elif key == 27:
                break

def configure_runtime(cli_data_dir: str | None = None):
    global STATE_DIR, DATA_FILE, SETTINGS_FILE, ERROR_LOG_FILE
    STATE_DIR = resolve_state_dir(cli_data_dir)
    DATA_FILE = state_path("passenger_data.json")
    SETTINGS_FILE = state_path("data", "system_settings.json")
    ERROR_LOG_FILE = state_path("data", "error.log")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Border Control Passenger Entry and Exit System"
    )
    parser.add_argument(
        "--data-dir",
        help=(
            "Writable directory for passenger data, settings, and logs. "
            "Use this when running from read-only media such as a live CD/DVD."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    configure_runtime(args.data_dir)

    if curses is None:
        print("The curses module is not available.")
        print("On Windows, install it with: python -m pip install windows-curses")
        return

    try:
        curses.wrapper(lambda stdscr: Application(stdscr).run())
    except curses.error:
        ensure_parent_dir(ERROR_LOG_FILE)
        with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"\n--- {datetime.now().isoformat()} ---\n")
            traceback.print_exc(file=f)
        print("Curses is not available or the terminal does not support full-screen mode.")
        print("Run this script in a Windows cmd or PowerShell terminal after installing windows-curses.")
    except Exception:
        ensure_parent_dir(ERROR_LOG_FILE)
        with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"\n--- {datetime.now().isoformat()} ---\n")
            traceback.print_exc(file=f)
        print(f"Unexpected error. See {ERROR_LOG_FILE} for details.")

if __name__ == "__main__":
    main()
