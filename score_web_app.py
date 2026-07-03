import csv
import html
import io
import os
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
DB_PATH = Path(os.environ.get("SCORE_DB_PATH", DATA_DIR / "score_web.db"))
LEGACY_MATCH_FILE = BASE_DIR / "match_scores.csv"

app = FastAPI(title="대회 종합성적 웹 관리")


FISH_COUNT_ALIASES = (
    "마리수",
    "마릿수",
    "총마리수",
    "연간총마리수",
    "마리",
    "수량",
    "개체수",
    "fish_count",
    "fishcount",
    "fish",
    "count",
)
SEED_NUMBER_ALIASES = (
    "시드번호",
    "시드",
    "seed",
    "seed_no",
    "seedno",
    "seed_number",
    "seednumber",
)
WEIGHT_ALIASES = ("최종중량", "중량", "총중량", "weight", "total_weight")


def clean_cell(value: Any) -> str:
    return "" if value is None else str(value).strip()


def is_dash_value(value: Any) -> bool:
    return clean_cell(value) in {"-", "－", "—", "–"}


def normalize_key(value: Any) -> str:
    return "".join(char for char in clean_cell(value).lower() if char.isalnum())


def safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def format_number(value: Any) -> str:
    number = safe_float(value)
    return f"{number:g}"


def primary_name(value: Any) -> str:
    name = clean_cell(value)
    for separator in (",", "，"):
        if separator in name:
            name = name.split(separator, 1)[0]
            break
    return clean_cell(name)


def get_value_by_alias(row: dict[str, Any], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = clean_cell(row.get(alias))
        if value:
            return value

    normalized_aliases = {normalize_key(alias) for alias in aliases}
    for key, value in row.items():
        if normalize_key(key) in normalized_aliases:
            cleaned_value = clean_cell(value)
            if cleaned_value:
                return cleaned_value
    return ""


def has_dash_value_by_alias(row: dict[str, Any], aliases: tuple[str, ...]) -> bool:
    normalized_aliases = {normalize_key(alias) for alias in aliases}
    for key, value in row.items():
        if normalize_key(key) in normalized_aliases and is_dash_value(value):
            return True
    return False


def has_score_dash_marker(row: dict[str, Any]) -> bool:
    return has_dash_value_by_alias(
        row,
        FISH_COUNT_ALIASES + WEIGHT_ALIASES + ("획득점수", "점수", "score", "points"),
    )


def has_column_alias(columns: list[str], aliases: tuple[str, ...]) -> bool:
    normalized_columns = {normalize_key(column) for column in columns}
    return any(normalize_key(alias) in normalized_columns for alias in aliases)


def read_csv_bytes(data: bytes) -> tuple[list[dict[str, str]], list[str]]:
    last_error = None
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = data.decode(encoding)
            reader = csv.DictReader(io.StringIO(text))
            fieldnames = [clean_cell(fieldname) for fieldname in (reader.fieldnames or [])]
            rows = []
            for row in reader:
                normalized = {}
                for key, value in row.items():
                    normalized_key = clean_cell(key)
                    if normalized_key:
                        normalized[normalized_key] = clean_cell(value)
                rows.append(normalized)
            return rows, fieldnames
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error or UnicodeDecodeError("unknown", b"", 0, 1, "CSV decode failed")


def read_csv_file(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    return read_csv_bytes(path.read_bytes())


def is_blank_row(row: dict[str, Any]) -> bool:
    return not any(clean_cell(value) for value in row.values())


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                match_type TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
                rank TEXT,
                name TEXT NOT NULL,
                seed_number TEXT,
                fish_count INTEGER NOT NULL DEFAULT 0,
                final_weight REAL NOT NULL DEFAULT 0,
                points INTEGER NOT NULL DEFAULT 0
            )
            """
        )


def legacy_import_if_needed() -> None:
    if not LEGACY_MATCH_FILE.exists():
        return

    with db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        if count:
            return

    rows, _columns = read_csv_file(LEGACY_MATCH_FILE)
    if not rows:
        return

    matches: dict[str, dict[str, str]] = {}
    entries: list[dict[str, Any]] = []
    for row in rows:
        match_id = clean_cell(row.get("대회ID"))
        if not match_id:
            continue
        match_type = clean_cell(row.get("대회종류"))
        points = stored_points(row)

        matches.setdefault(
            match_id,
            {
                "id": match_id,
                "name": clean_cell(row.get("대회명")) or "대회",
                "uploaded_at": clean_cell(row.get("일시")) or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "match_type": match_type or "정규전",
            },
        )
        entries.append(
            {
                "match_id": match_id,
                "rank": clean_cell(row.get("순위")),
                "name": primary_name(row.get("이름")),
                "seed_number": clean_cell(row.get("시드번호")),
                "fish_count": safe_int(row.get("마리수")),
                "final_weight": safe_float(row.get("최종중량")),
                "points": points,
            }
        )

    with db() as conn:
        for match in matches.values():
            conn.execute(
                "INSERT OR IGNORE INTO matches (id, name, uploaded_at, match_type) VALUES (?, ?, ?, ?)",
                (match["id"], match["name"], match["uploaded_at"], match["match_type"]),
            )
        for entry in entries:
            if not entry["name"]:
                continue
            conn.execute(
                """
                INSERT INTO entries
                (match_id, rank, name, seed_number, fish_count, final_weight, points)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["match_id"],
                    entry["rank"],
                    entry["name"],
                    entry["seed_number"],
                    entry["fish_count"],
                    entry["final_weight"],
                    entry["points"],
                ),
            )


@app.on_event("startup")
def startup() -> None:
    init_db()
    legacy_import_if_needed()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def stored_points(row: dict[str, Any]) -> int:
    if has_score_dash_marker(row):
        return 0
    if clean_cell(row.get("대회종류")) == "정규전" and safe_float(row.get("최종중량")) < 0:
        return 0
    if clean_cell(row.get("대회종류")) == "정규전" and safe_int(row.get("마리수")) == 0:
        return 30
    if clean_cell(row.get("대회종류")) == "스페셜":
        return 30
    return safe_int(row.get("획득점수"))


def score_regular(rows: list[dict[str, str]], open_name_mode: bool) -> list[dict[str, Any]]:
    scored = []
    for line_number, row in enumerate(rows, start=2):
        if is_blank_row(row):
            continue
        name = primary_name(row.get("이름")) if open_name_mode else clean_cell(row.get("이름"))
        if not name:
            raise ValueError(f"CSV/엑셀 기준 {line_number}행의 이름 칸이 비어 있습니다.")
        raw_weight = get_value_by_alias(row, WEIGHT_ALIASES)
        zero_points = has_score_dash_marker(row)
        if zero_points and is_dash_value(raw_weight):
            weight = 0.0
        else:
            try:
                weight = float(raw_weight)
            except ValueError as exc:
                raise ValueError(f"{line_number}행의 최종중량은 숫자로 입력해주세요.") from exc
        zero_points = zero_points or weight < 0
        fish_count = safe_int(get_value_by_alias(row, FISH_COUNT_ALIASES))
        if zero_points:
            weight = 0.0
            fish_count = 0
        scored.append(
            {
                "name": name,
                "seed_number": get_value_by_alias(row, SEED_NUMBER_ALIASES),
                "fish_count": fish_count,
                "final_weight": weight,
                "zero_points": zero_points,
            }
        )

    ranked_rows = [row for row in scored if not row["zero_points"]]
    sorted_weights = sorted((row["final_weight"] for row in ranked_rows), reverse=True)
    rank_by_weight = {}
    for rank, weight in enumerate(sorted_weights, start=1):
        rank_by_weight.setdefault(weight, rank)

    result = []
    for row in scored:
        if row["zero_points"]:
            result.append({**row, "rank": "", "points": 0})
            continue

        rank = rank_by_weight[row["final_weight"]]
        points = 30 if row["fish_count"] == 0 else max(101 - rank, 0)
        result.append({**row, "rank": str(rank), "points": points})
    return sorted(
        result,
        key=lambda row: (10**9 if not row["rank"] else safe_int(row["rank"]), row["name"]),
    )


def score_special(rows: list[dict[str, str]], open_name_mode: bool) -> list[dict[str, Any]]:
    scored = []
    for line_number, row in enumerate(rows, start=2):
        if is_blank_row(row):
            continue
        name = primary_name(row.get("이름")) if open_name_mode else clean_cell(row.get("이름"))
        if not name:
            raise ValueError(f"CSV/엑셀 기준 {line_number}행의 이름 칸이 비어 있습니다.")
        scored.append(
            {
                "name": name,
                "seed_number": get_value_by_alias(row, SEED_NUMBER_ALIASES),
                "fish_count": safe_int(get_value_by_alias(row, FISH_COUNT_ALIASES)),
                "final_weight": 0,
                "rank": "",
                "points": 0 if has_score_dash_marker(row) else 30,
            }
        )
    return scored


def add_match(match_name: str, match_type: str, entries: list[dict[str, Any]]) -> str:
    match_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    uploaded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db() as conn:
        conn.execute(
            "INSERT INTO matches (id, name, uploaded_at, match_type) VALUES (?, ?, ?, ?)",
            (match_id, match_name, uploaded_at, match_type),
        )
        for entry in entries:
            conn.execute(
                """
                INSERT INTO entries
                (match_id, rank, name, seed_number, fish_count, final_weight, points)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    entry["rank"],
                    entry["name"],
                    entry["seed_number"],
                    entry["fish_count"],
                    entry["final_weight"],
                    entry["points"],
                ),
            )
    return match_id


def total_scores() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT
                name,
                SUM(points) AS total_points,
                COUNT(*) AS match_count,
                SUM(final_weight) AS total_weight,
                SUM(fish_count) AS total_fish_count,
                MAX(seed_number) AS seed_number
            FROM entries
            GROUP BY name
            """
        ).fetchall()

    totals = [dict(row) for row in rows]
    totals.sort(
        key=lambda row: (
            -safe_int(row["total_points"]),
            -safe_float(row["total_weight"]),
            -safe_int(row["total_fish_count"]),
            seed_sort_key(row["seed_number"]),
            clean_cell(row["name"]),
        )
    )
    for index, row in enumerate(totals, start=1):
        row["rank"] = index
    return totals


def seed_sort_key(value: Any) -> tuple[int, int, str]:
    seed_text = clean_cell(value)
    if not seed_text:
        return (1, 10**9, "")
    try:
        return (0, int(float(seed_text)), seed_text)
    except ValueError:
        return (0, 10**9, seed_text)


def matches_with_entries() -> list[dict[str, Any]]:
    with db() as conn:
        matches = conn.execute(
            "SELECT * FROM matches ORDER BY id DESC"
        ).fetchall()
        result = []
        for match in matches:
            entries = conn.execute(
                """
                SELECT * FROM entries
                WHERE match_id = ?
                ORDER BY
                    CASE WHEN rank = '' THEN 999999 ELSE CAST(rank AS INTEGER) END,
                    name
                """,
                (match["id"],),
            ).fetchall()
            result.append({"match": dict(match), "entries": [dict(row) for row in entries]})
    return result


def table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = ""
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in row)
        body += f"<tr>{cells}</tr>"
    if not rows:
        body = f"<tr><td colspan='{len(headers)}' class='empty'>표시할 데이터가 없습니다.</td></tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_page(message: str = "", query: str = "") -> str:
    totals = total_scores()
    matches = matches_with_entries()
    normalized_query = clean_cell(query).lower()

    if normalized_query:
        totals = [row for row in totals if normalized_query in clean_cell(row["name"]).lower()]

    total_rows = [
        [
            row["rank"],
            row["seed_number"] or "-",
            row["name"],
            safe_int(row["total_points"]),
            format_number(row["total_weight"]),
            safe_int(row["total_fish_count"]),
            safe_int(row["match_count"]),
        ]
        for row in totals
    ]

    match_sections = ""
    for match_info in matches:
        match = match_info["match"]
        entries = match_info["entries"]
        if normalized_query:
            entries = [row for row in entries if normalized_query in clean_cell(row["name"]).lower()]
        rows = [
            [
                entry["rank"] or "-",
                entry["seed_number"] or "-",
                entry["name"],
                entry["fish_count"],
                format_number(entry["final_weight"]),
                entry["points"],
            ]
            for entry in entries
        ]
        title = html.escape(extract_parenthesized_text(match["name"]) or match["name"])
        match_sections += f"""
        <section class="match-card" id="match-{html.escape(match['id'])}">
          <div class="match-head">
            <div>
              <h3>{title}</h3>
              <p>{html.escape(match['uploaded_at'])} | {html.escape(match['match_type'])}</p>
            </div>
            <form method="post" action="/matches/{html.escape(match['id'])}/delete" onsubmit="return confirm('이 대회 성적을 삭제하시겠습니까?');">
              <button class="danger" type="submit">이 대회 삭제</button>
            </form>
          </div>
          {table(["대회 순위", "시드번호", "이름", "마리수", "최종중량", "획득점수"], rows)}
        </section>
        """

    return f"""
    <!doctype html>
    <html lang="ko">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>대회 종합성적 관리</title>
      <style>
        body {{ margin: 0; font-family: 'Malgun Gothic', Arial, sans-serif; background: #f4f7fb; color: #172033; }}
        header {{ background: #1f5ea8; color: white; padding: 18px 24px; }}
        main {{ padding: 18px 24px 40px; }}
        .panel, .match-card {{ background: white; border: 1px solid #d9e2ef; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
        .grid {{ display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 10px; align-items: end; }}
        label {{ display: block; font-size: 13px; font-weight: 700; margin-bottom: 5px; }}
        input, select {{ box-sizing: border-box; width: 100%; padding: 8px; border: 1px solid #b8c7db; border-radius: 5px; }}
        .inline {{ display: flex; align-items: center; gap: 8px; }}
        .inline input {{ width: auto; }}
        button, .button {{ display: inline-block; border: 0; background: #2f80ed; color: white; padding: 9px 12px; border-radius: 5px; cursor: pointer; text-decoration: none; font-size: 14px; }}
        .danger {{ background: #d83a3a; }}
        .message {{ background: #fff7d6; border: 1px solid #ecd37c; padding: 10px; border-radius: 6px; margin-bottom: 14px; }}
        .tabs {{ display: flex; gap: 8px; margin: 16px 0; }}
        .tabs a {{ background: #d6e6f5; color: #172033; padding: 10px 14px; border-radius: 6px; text-decoration: none; font-weight: 700; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        th {{ background: #2f80ed; color: white; padding: 8px; text-align: center; }}
        td {{ padding: 7px 8px; border-bottom: 1px solid #dde6f1; text-align: center; }}
        tbody tr:nth-child(even) {{ background: #eef5ff; }}
        .empty {{ color: #667085; }}
        .match-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: start; }}
        h2, h3 {{ margin: 0 0 10px; }}
        .match-head p {{ margin: 0; color: #667085; }}
        @media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} .match-head {{ flex-direction: column; }} }}
      </style>
    </head>
    <body>
      <header><h1>대회 종합성적 관리</h1></header>
      <main>
        {f'<div class="message">{html.escape(message)}</div>' if message else ''}
        <section class="panel">
          <h2>대회 결과 업로드</h2>
          <form method="post" action="/upload" enctype="multipart/form-data" class="grid">
            <div><label>CSV 파일</label><input type="file" name="file" accept=".csv" required></div>
            <div><label>대회명</label><input type="text" name="match_name" placeholder="비우면 파일명 사용"></div>
            <div><label>점수 방식</label><select name="match_type"><option value="정규전">정규전</option><option value="스페셜">스페셜(전원 30점)</option></select></div>
            <div class="inline"><input id="open-name" type="checkbox" name="open_name_mode" value="1" checked><label for="open-name">쉼표 앞 이름만 반영</label></div>
            <div><button type="submit">성적 산출 및 저장</button></div>
          </form>
        </section>
        <section class="panel">
          <form method="get" action="/" class="grid">
            <div><label>이름 검색</label><input type="text" name="q" value="{html.escape(query)}"></div>
            <div><button type="submit">검색</button></div>
            <div><a class="button" href="/">검색 초기화</a></div>
            <div><a class="button" href="/download/total.xlsx">종합성적 엑셀 다운로드</a></div>
          </form>
        </section>
        <nav class="tabs"><a href="#total">종합성적</a><a href="#matches">대회별 성적</a></nav>
        <section class="panel" id="total">
          <h2>종합성적</h2>
          {table(["현재 순위", "시드번호", "이름", "종합 점수", "연간 총중량", "연간 총마리수", "참가 횟수"], total_rows)}
        </section>
        <section id="matches">
          <h2>대회별 성적</h2>
          {match_sections or '<section class="match-card">아직 저장된 대회별 성적이 없습니다.</section>'}
        </section>
      </main>
    </body>
    </html>
    """


def extract_parenthesized_text(value: Any) -> str:
    text = clean_cell(value)
    start = text.find("(")
    end = text.rfind(")")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start + 1 : end].strip()


@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", message: str = "") -> HTMLResponse:
    return HTMLResponse(render_page(message=message, query=q))


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    match_name: str = Form(""),
    match_type: str = Form("정규전"),
    open_name_mode: str | None = Form(None),
) -> RedirectResponse:
    data = await file.read()
    rows, columns = read_csv_bytes(data)
    if "이름" not in columns:
        return redirect_with_message("CSV 파일에 '이름' 열이 없습니다.")
    if not rows:
        return redirect_with_message("CSV 파일에 처리할 데이터가 없습니다.")

    try:
        use_primary_name = open_name_mode == "1"
        if match_type == "정규전":
            if not has_column_alias(columns, WEIGHT_ALIASES):
                return redirect_with_message("정규전에는 '최종중량' 열이 필요합니다.")
            entries = score_regular(rows, use_primary_name)
        else:
            entries = score_special(rows, use_primary_name)
    except ValueError as exc:
        return redirect_with_message(str(exc))

    name = clean_cell(match_name) or Path(file.filename or "대회").stem
    add_match(name, match_type, entries)
    return redirect_with_message(f"{match_type} 대회 성적을 저장했습니다.")


@app.post("/matches/{match_id}/delete")
def delete_match(match_id: str) -> RedirectResponse:
    with db() as conn:
        conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
    return redirect_with_message("선택한 대회 성적을 삭제했습니다.")


@app.get("/download/total.xlsx")
def download_total() -> Response:
    headers = ["현재 순위", "시드번호", "이름", "종합 점수", "연간 총중량", "연간 총마리수", "참가 횟수"]
    rows = [
        [
            row["rank"],
            row["seed_number"] or "",
            row["name"],
            safe_int(row["total_points"]),
            format_number(row["total_weight"]),
            safe_int(row["total_fish_count"]),
            safe_int(row["match_count"]),
        ]
        for row in total_scores()
    ]
    content = make_xlsx(headers, rows, sheet_name="종합성적")
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=total_scores.xlsx"},
    )


def redirect_with_message(message: str) -> RedirectResponse:
    from urllib.parse import urlencode

    return RedirectResponse(f"/?{urlencode({'message': message})}", status_code=303)


def make_xlsx(headers: list[str], rows: list[list[Any]], sheet_name: str) -> bytes:
    all_rows = [headers] + rows

    def col_name(index: int) -> str:
        name = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            name = chr(65 + remainder) + name
        return name

    sheet_rows = []
    for row_index, row in enumerate(all_rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{col_name(col_index)}{row_index}"
            text = html.escape(str(value))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>{"".join(sheet_rows)}</sheetData>
</worksheet>"""
    workbook_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="{html.escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()
