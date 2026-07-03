import csv
import os
import sqlite3
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class ScoreManagerApp:
    MASTER_COLUMNS = [
        "이름",
        "종합점수",
        "참가횟수",
        "연간총중량",
        "연간총마리수",
        "시드번호",
    ]
    MATCH_COLUMNS = [
        "대회ID",
        "대회명",
        "일시",
        "대회종류",
        "순위",
        "이름",
        "시드번호",
        "마리수",
        "최종중량",
        "획득점수",
    ]
    OPTIONAL_MASTER_COLUMNS = ["연간총중량", "연간총마리수", "시드번호"]
    OPTIONAL_MATCH_COLUMNS = ["시드번호", "마리수"]
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
    SCORE_ALIASES = ("획득점수", "점수", "score", "points")

    def __init__(self, root):
        self.root = root
        self.root.title("대회 종합성적 관리 프로그램")
        self.root.geometry("920x650")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_file = os.path.join(base_dir, "score_web.db")
        self.master_file = os.path.join(base_dir, "total_scores.csv")
        self.match_file = os.path.join(base_dir, "match_scores.csv")
        self.match_lookup = {}

        self.init_db()
        self.configure_styles()
        self.create_widgets()
        self.load_master_data()
        self.load_match_list()

    def configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Score.TNotebook",
            background="#d8e7f7",
            borderwidth=0,
            tabmargins=(2, 5, 2, 0),
        )
        style.configure(
            "Score.TNotebook.Tab",
            background="#d6e6f5",
            foreground="#1f2937",
            padding=(16, 8),
        )
        style.map(
            "Score.TNotebook.Tab",
            background=[("selected", "#2f80ed"), ("active", "#b9d7f2")],
            foreground=[("selected", "#ffffff"), ("active", "#111827")],
        )

    def create_widgets(self):
        input_frame = tk.LabelFrame(self.root, text="대회 결과 입력", padx=10, pady=10)
        input_frame.pack(fill="x", padx=10, pady=10)

        self.filepath = tk.StringVar()
        tk.Entry(input_frame, textvariable=self.filepath, width=58, state="readonly").grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5
        )
        tk.Button(input_frame, text="CSV 파일 찾기", command=self.select_file).grid(
            row=0, column=2, padx=5, pady=5
        )

        tk.Label(input_frame, text="대회명").grid(row=1, column=0, sticky="w", padx=5)
        self.match_name = tk.StringVar()
        tk.Entry(input_frame, textvariable=self.match_name, width=35).grid(
            row=1, column=1, sticky="ew", padx=5, pady=5
        )

        self.match_type = tk.StringVar(value="정규전")
        tk.Radiobutton(
            input_frame,
            text="정규전(1등 100점, 2등 99점...)",
            variable=self.match_type,
            value="정규전",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=5)
        tk.Radiobutton(
            input_frame,
            text="스페셜(전원 30점)",
            variable=self.match_type,
            value="스페셜",
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=5)

        self.open_name_mode = tk.BooleanVar(value=True)
        tk.Checkbutton(
            input_frame,
            text="오픈전 이름 처리: 쉼표 앞 이름만 종합성적 반영",
            variable=self.open_name_mode,
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=5)

        tk.Button(
            input_frame,
            text="성적 산출 및 누적하기",
            command=self.process_data,
            bg="lightblue",
        ).grid(row=1, column=2, rowspan=4, sticky="nsew", padx=5, pady=5)

        input_frame.columnconfigure(1, weight=1)

        filter_frame = tk.Frame(self.root)
        filter_frame.pack(fill="x", padx=10, pady=(0, 10))

        tk.Label(filter_frame, text="이름 검색").pack(side=tk.LEFT, padx=(0, 8))
        self.name_filter = tk.StringVar()
        self.name_filter.trace_add("write", self.on_name_filter_changed)
        tk.Entry(filter_frame, textvariable=self.name_filter, width=30).pack(
            side=tk.LEFT, fill="x", expand=True
        )
        tk.Button(filter_frame, text="검색 초기화", command=self.clear_name_filter).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        notebook = ttk.Notebook(self.root, style="Score.TNotebook")
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        total_tab = ttk.Frame(notebook)
        match_tab = ttk.Frame(notebook)
        notebook.add(total_tab, text="종합성적")
        notebook.add(match_tab, text="대회별 성적")

        self.create_total_tab(total_tab)
        self.create_match_tab(match_tab)

        tk.Button(
            self.root,
            text="전체 성적 데이터 초기화",
            command=self.reset_data,
            fg="red",
        ).pack(pady=(0, 10))

    def create_total_tab(self, parent):
        display_frame = tk.LabelFrame(parent, text="현재 종합성적 현황", padx=10, pady=10)
        display_frame.pack(fill="both", expand=True, padx=10, pady=10)

        columns = (
            "Rank",
            "SeedNumber",
            "Name",
            "TotalScore",
            "TotalWeight",
            "TotalFishCount",
            "MatchCount",
        )
        self.tree = ttk.Treeview(display_frame, columns=columns, show="headings")
        self.tree.heading("Rank", text="현재 순위")
        self.tree.heading("SeedNumber", text="시드번호")
        self.tree.heading("Name", text="이름")
        self.tree.heading("TotalScore", text="종합 점수")
        self.tree.heading("TotalWeight", text="연간 총중량")
        self.tree.heading("TotalFishCount", text="연간 총마리수")
        self.tree.heading("MatchCount", text="참가 횟수")

        self.tree.column("Rank", width=90, anchor="center")
        self.tree.column("SeedNumber", width=100, anchor="center")
        self.tree.column("Name", width=150, anchor="center")
        self.tree.column("TotalScore", width=110, anchor="center")
        self.tree.column("TotalWeight", width=130, anchor="center")
        self.tree.column("TotalFishCount", width=130, anchor="center")
        self.tree.column("MatchCount", width=100, anchor="center")
        self.tree.tag_configure("even_row", background="#ffffff")
        self.tree.tag_configure("odd_row", background="#eef5ff")

        scrollbar = ttk.Scrollbar(display_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.pack(side=tk.RIGHT, fill="y")

    def create_match_tab(self, parent):
        self.match_notebook = ttk.Notebook(parent, style="Score.TNotebook")
        self.match_notebook.pack(fill="both", expand=True, padx=10, pady=10)

    def select_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if file_path:
            self.filepath.set(file_path)
            if not self.match_name.get().strip():
                self.match_name.set(os.path.splitext(os.path.basename(file_path))[0])

    def db(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
        with self.db() as conn:
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
                    match_id TEXT NOT NULL,
                    rank TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    seed_number TEXT NOT NULL DEFAULT '',
                    fish_count INTEGER NOT NULL DEFAULT 0,
                    final_weight REAL NOT NULL DEFAULT 0,
                    points INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE
                )
                """
            )

    def process_data(self):
        file_path = self.filepath.get()
        if not file_path:
            messagebox.showwarning("경고", "대회 결과 CSV 파일을 먼저 선택해주세요.")
            return

        try:
            rows, columns = self.read_csv_with_fallback(file_path)

            if "이름" not in columns:
                messagebox.showerror("오류", "CSV 파일에 '이름' 열이 존재하지 않습니다.")
                return

            if not rows:
                messagebox.showwarning("경고", "CSV 파일에 처리할 데이터가 없습니다.")
                return

            match_type = self.match_type.get()
            if match_type == "정규전":
                if not self.has_column_alias(columns, self.WEIGHT_ALIASES):
                    messagebox.showerror("오류", "정규전에는 '최종중량' 열이 필요합니다.")
                    return

                current_match = self.score_regular_match(rows)
                if current_match is None:
                    return
            else:
                current_match = self.score_special_match(rows)
                if current_match is None:
                    return

            match_id = self.append_match_rows(current_match, file_path)

            messagebox.showinfo(
                "성공",
                f"성공적으로 데이터를 반영했습니다!\n({self.match_type.get()})",
            )
            self.filepath.set("")
            self.match_name.set("")
            self.load_master_data()
            self.load_match_list(selected_match_id=match_id)

        except Exception as e:
            messagebox.showerror(
                "에러 발생",
                f"데이터 처리 중 문제가 발생했습니다:\n{e}",
            )

    def load_master_data(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        try:
            master_rows = self.read_master_rows()
            filter_text = self.get_name_filter()
            visible_index = 0
            for rank, row in enumerate(master_rows, start=1):
                if not self.name_matches_filter(row.get("이름", ""), filter_text):
                    continue

                self.tree.insert(
                    "",
                    tk.END,
                    values=(
                        rank,
                        row["시드번호"] or "-",
                        row["이름"],
                        int(row["종합점수"]),
                        self.format_number(row["연간총중량"]),
                        int(row["연간총마리수"]),
                        int(row["참가횟수"]),
                    ),
                    tags=("odd_row" if visible_index % 2 else "even_row",),
                )
                visible_index += 1
        except Exception as e:
            print("데이터를 불러오는 데 실패했습니다:", e)

    def load_match_list(self, selected_match_id=None):
        for tab_id in self.match_notebook.tabs():
            self.match_notebook.forget(tab_id)

        rows = self.read_match_rows()
        matches = {}

        for row in rows:
            match_id = row.get("대회ID")
            if not match_id:
                continue

            if match_id not in matches:
                matches[match_id] = {"label": self.build_match_label(row), "rows": []}
            matches[match_id]["rows"].append(row)

        if not matches:
            empty_frame = ttk.Frame(self.match_notebook)
            self.match_notebook.add(empty_frame, text="기록 없음")
            ttk.Label(
                empty_frame,
                text="아직 저장된 대회별 성적이 없습니다.",
                anchor="center",
            ).pack(fill="both", expand=True, padx=20, pady=20)
            return

        selected_index = 0
        for index, (match_id, match_info) in enumerate(
            sorted(matches.items(), key=lambda item: item[0], reverse=True)
        ):
            match_rows = match_info["rows"]
            match_rows.sort(
                key=lambda row: (self.rank_sort_key(row.get("순위")), row.get("이름", ""))
            )
            visible_rows = [
                row
                for row in match_rows
                if self.name_matches_filter(row.get("이름", ""), self.get_name_filter())
            ]

            frame = ttk.Frame(self.match_notebook)
            self.match_notebook.add(frame, text=self.build_match_tab_text(match_rows[0]))
            self.create_match_result_table(
                frame,
                match_id,
                match_info["label"],
                visible_rows,
            )

            if selected_match_id and match_id == selected_match_id:
                selected_index = index

        self.match_notebook.select(selected_index)

    def create_match_result_table(self, parent, match_id, title, rows):
        header_frame = tk.Frame(parent)
        header_frame.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Label(header_frame, text=title, anchor="w").pack(
            side=tk.LEFT,
            fill="x",
            expand=True,
        )
        tk.Button(
            header_frame,
            text="이 대회 삭제",
            command=lambda: self.delete_match(match_id, title),
            fg="red",
        ).pack(side=tk.RIGHT)

        columns = ("Rank", "Name", "FishCount", "Weight", "Score")
        display_frame = tk.LabelFrame(parent, text="대회 성적", padx=10, pady=10)
        display_frame.pack(fill="both", expand=True, padx=10, pady=10)

        match_tree = ttk.Treeview(display_frame, columns=columns, show="headings")
        match_tree.heading("Rank", text="대회 순위")
        match_tree.heading("Name", text="이름")
        match_tree.heading("FishCount", text="마리수")
        match_tree.heading("Weight", text="최종중량")
        match_tree.heading("Score", text="획득점수")

        match_tree.column("Rank", width=100, anchor="center")
        match_tree.column("Name", width=180, anchor="center")
        match_tree.column("FishCount", width=100, anchor="center")
        match_tree.column("Weight", width=160, anchor="center")
        match_tree.column("Score", width=140, anchor="center")
        match_tree.tag_configure("even_row", background="#ffffff")
        match_tree.tag_configure("odd_row", background="#eef5ff")

        scrollbar = ttk.Scrollbar(display_frame, orient=tk.VERTICAL, command=match_tree.yview)
        match_tree.configure(yscroll=scrollbar.set)

        match_tree.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.pack(side=tk.RIGHT, fill="y")

        if not rows:
            match_tree.insert(
                "",
                tk.END,
                values=("-", "검색 결과 없음", "-", "-", "-"),
                tags=("even_row",),
            )
            return

        for index, row in enumerate(rows):
            match_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("순위") or "-",
                    row.get("이름") or "",
                    row.get("마리수") or "-",
                    row.get("최종중량") or "-",
                    row.get("획득점수") or "0",
                ),
                tags=("odd_row" if index % 2 else "even_row",),
            )

    def on_name_filter_changed(self, *_args):
        self.load_master_data()
        self.load_match_list()

    def clear_name_filter(self):
        self.name_filter.set("")

    def delete_match(self, match_id, title):
        if not messagebox.askyesno(
            "대회 삭제",
            f"이 대회 성적을 삭제하시겠습니까?\n\n{title}\n\n"
            "삭제 후 종합성적은 남은 대회 기록 기준으로 다시 계산됩니다.",
        ):
            return

        try:
            with self.db() as conn:
                conn.execute("DELETE FROM entries WHERE match_id = ?", (match_id,))
                conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
            self.load_master_data()
            self.load_match_list()
            messagebox.showinfo(
                "삭제 완료",
                "선택한 대회 성적을 삭제했습니다. 이제 같은 대회를 다시 업로드할 수 있습니다.",
            )
        except Exception as e:
            messagebox.showerror(
                "삭제 실패",
                f"대회 성적 삭제 중 문제가 발생했습니다:\n{e}",
            )

    def reset_data(self):
        if messagebox.askyesno(
            "경고",
            "정말로 모든 종합성적과 대회별 성적 데이터를 삭제하시겠습니까?\n"
            "(이 작업은 되돌릴 수 없습니다.)",
        ):
            with self.db() as conn:
                conn.execute("DELETE FROM entries")
                conn.execute("DELETE FROM matches")
            self.load_master_data()
            self.load_match_list()
            messagebox.showinfo("초기화 완료", "모든 데이터가 초기화되었습니다.")

    def score_regular_match(self, rows):
        scored_rows = []

        for line_number, row in enumerate(rows, start=2):
            if self.is_blank_row(row):
                continue

            name = self.get_entry_name(row.get("이름"))
            raw_weight = self.get_value_by_alias(row, self.WEIGHT_ALIASES)
            zero_points = self.has_score_dash_marker(row)

            if not name:
                messagebox.showerror(
                    "오류",
                    f"CSV/엑셀 기준 {line_number}행의 이름 칸이 비어 있습니다.\n"
                    "헤더를 1행으로 보고 계산한 줄 번호입니다.",
                )
                return None

            if zero_points and self.is_dash_value(raw_weight):
                weight = 0.0
            else:
                try:
                    weight = float(raw_weight)
                except ValueError:
                    messagebox.showerror(
                        "오류",
                        f"{line_number}행의 최종중량은 숫자로 입력해주세요.",
                    )
                    return None
            zero_points = zero_points or weight < 0
            fish_count = self.safe_int(self.get_fish_count(row))
            if zero_points:
                weight = 0.0
                fish_count = 0

            scored_rows.append(
                {
                    "이름": name,
                    "마리수": fish_count,
                    "시드번호": self.get_seed_number(row),
                    "최종중량": weight,
                    "zero_points": zero_points,
                }
            )

        sorted_weights = sorted(
            (row["최종중량"] for row in scored_rows if not row["zero_points"]),
            reverse=True,
        )
        rank_by_weight = {}
        for rank, weight in enumerate(sorted_weights, start=1):
            rank_by_weight.setdefault(weight, rank)

        result = []
        for row in scored_rows:
            if row["zero_points"]:
                result.append(
                    {
                        "이름": row["이름"],
                        "순위": "",
                        "마리수": row["마리수"],
                        "시드번호": row["시드번호"],
                        "최종중량": self.format_number(row["최종중량"]),
                        "Score": 0,
                    }
                )
                continue
            rank = rank_by_weight[row["최종중량"]]
            score = 30 if self.safe_int(row["마리수"]) == 0 else max(101 - rank, 0)
            result.append(
                {
                    "이름": row["이름"],
                    "순위": rank,
                    "마리수": row["마리수"],
                    "시드번호": row["시드번호"],
                    "최종중량": self.format_number(row["최종중량"]),
                    "Score": score,
                }
            )

        return sorted(
            result,
            key=lambda row: (10**9 if row["순위"] == "" else row["순위"], row["이름"]),
        )

    def score_special_match(self, rows):
        scored_rows = []

        for line_number, row in enumerate(rows, start=2):
            if self.is_blank_row(row):
                continue

            name = self.get_entry_name(row.get("이름"))
            if not name:
                messagebox.showerror(
                    "오류",
                    f"CSV/엑셀 기준 {line_number}행의 이름 칸이 비어 있습니다.\n"
                    "헤더를 1행으로 보고 계산한 줄 번호입니다.",
                )
                return None
            scored_rows.append(
                {
                    "이름": name,
                    "순위": "",
                    "마리수": self.get_fish_count(row),
                    "시드번호": self.get_seed_number(row),
                    "최종중량": "",
                    "Score": 0 if self.has_score_dash_marker(row) else 30,
                }
            )

        return scored_rows

    def merge_scores(self, current_match):
        master_by_name = {
            row["이름"]: {
                "이름": row["이름"],
                "종합점수": self.safe_int(row.get("종합점수")),
                "참가횟수": self.safe_int(row.get("참가횟수")),
                "연간총중량": self.safe_float(row.get("연간총중량")),
                "연간총마리수": self.safe_int(row.get("연간총마리수")),
                "시드번호": self.clean_cell(row.get("시드번호")),
            }
            for row in self.read_master_rows()
            if row.get("이름")
        }

        for row in current_match:
            name = row["이름"]
            score = int(row["Score"])

            if name not in master_by_name:
                master_by_name[name] = {
                    "이름": name,
                    "종합점수": 0,
                    "참가횟수": 0,
                    "연간총중량": 0.0,
                    "연간총마리수": 0,
                    "시드번호": "",
                }

            master_by_name[name]["종합점수"] += score
            master_by_name[name]["참가횟수"] += 1
            master_by_name[name]["연간총중량"] += self.safe_float(row.get("최종중량"))
            master_by_name[name]["연간총마리수"] += self.safe_int(row.get("마리수"))
            if row.get("시드번호"):
                master_by_name[name]["시드번호"] = self.clean_cell(row.get("시드번호"))

        return sorted(
            master_by_name.values(),
            key=self.master_sort_key,
        )

    def append_match_rows(self, current_match, file_path):
        now = datetime.now()
        match_id = now.strftime("%Y%m%d%H%M%S%f")
        match_name = self.clean_cell(self.match_name.get())
        if not match_name:
            match_name = os.path.splitext(os.path.basename(file_path))[0]

        uploaded_at = now.strftime("%Y-%m-%d %H:%M:%S")
        with self.db() as conn:
            conn.execute(
                "INSERT INTO matches (id, name, uploaded_at, match_type) VALUES (?, ?, ?, ?)",
                (match_id, match_name, uploaded_at, self.match_type.get()),
            )
            for row in current_match:
                conn.execute(
                    """
                    INSERT INTO entries
                    (match_id, rank, name, seed_number, fish_count, final_weight, points)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        self.clean_cell(row.get("순위")),
                        row["이름"],
                        self.clean_cell(row.get("시드번호")),
                        self.safe_int(row.get("마리수")),
                        self.safe_float(row.get("최종중량")),
                        int(row["Score"]),
                    ),
                )

        return match_id

    def read_master_rows(self):
        master_by_name = {}
        for row in self.read_match_rows():
            name = self.get_primary_name(row.get("이름"))
            if not name:
                continue

            if name not in master_by_name:
                master_by_name[name] = {
                    "이름": name,
                    "종합점수": 0,
                    "참가횟수": 0,
                    "연간총중량": 0.0,
                    "연간총마리수": 0,
                    "시드번호": "",
                }

            master_by_name[name]["종합점수"] += self.safe_int(row.get("획득점수"))
            master_by_name[name]["참가횟수"] += 1
            master_by_name[name]["연간총중량"] += self.safe_float(row.get("최종중량"))
            master_by_name[name]["연간총마리수"] += self.safe_int(row.get("마리수"))
            if row.get("시드번호"):
                master_by_name[name]["시드번호"] = self.clean_cell(row.get("시드번호"))

        master_rows = list(master_by_name.values())
        return sorted(master_rows, key=self.master_sort_key)

    def write_master_rows(self, rows):
        with open(self.master_file, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=self.MASTER_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def write_match_rows(self, rows):
        with open(self.match_file, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=self.MATCH_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in self.MATCH_COLUMNS})

    def rebuild_master_from_match_rows(self, match_rows):
        master_by_name = {}

        for row in match_rows:
            name = self.get_primary_name(row.get("이름"))
            if not name:
                continue

            if name not in master_by_name:
                master_by_name[name] = {
                    "이름": name,
                    "종합점수": 0,
                    "참가횟수": 0,
                    "연간총중량": 0.0,
                    "연간총마리수": 0,
                    "시드번호": "",
                }

            master_by_name[name]["종합점수"] += self.safe_int(row.get("획득점수"))
            master_by_name[name]["참가횟수"] += 1
            master_by_name[name]["연간총중량"] += self.safe_float(row.get("최종중량"))
            master_by_name[name]["연간총마리수"] += self.safe_int(row.get("마리수"))
            if row.get("시드번호"):
                master_by_name[name]["시드번호"] = self.clean_cell(row.get("시드번호"))

        rebuilt_rows = sorted(master_by_name.values(), key=self.master_sort_key)
        self.write_master_rows(rebuilt_rows)

    def apply_match_aggregates(self, master_rows):
        if not os.path.exists(self.match_file):
            return

        try:
            match_rows = self.read_match_rows()
        except Exception:
            return

        aggregate_by_name = {}
        for row in match_rows:
            name = self.get_primary_name(row.get("이름"))
            if not name:
                continue

            if name not in aggregate_by_name:
                aggregate_by_name[name] = {
                    "종합점수": 0,
                    "참가횟수": 0,
                    "연간총중량": 0.0,
                    "연간총마리수": 0,
                    "시드번호": "",
                }

            aggregate_by_name[name]["종합점수"] += self.safe_int(row.get("획득점수"))
            aggregate_by_name[name]["참가횟수"] += 1
            aggregate_by_name[name]["연간총중량"] += self.safe_float(row.get("최종중량"))
            aggregate_by_name[name]["연간총마리수"] += self.safe_int(row.get("마리수"))
            if row.get("시드번호"):
                aggregate_by_name[name]["시드번호"] = self.clean_cell(row.get("시드번호"))

        existing_names = {row["이름"] for row in master_rows}
        for name, aggregate in aggregate_by_name.items():
            if name not in existing_names:
                master_rows.append(
                    {
                        "이름": name,
                        "종합점수": 0,
                        "참가횟수": 0,
                        "연간총중량": 0.0,
                        "연간총마리수": 0,
                        "시드번호": "",
                    }
                )
                existing_names.add(name)

        for row in master_rows:
            aggregate = aggregate_by_name.get(row["이름"])
            if not aggregate:
                continue

            row["종합점수"] = aggregate["종합점수"]
            row["참가횟수"] = aggregate["참가횟수"]
            row["연간총중량"] = aggregate["연간총중량"]
            row["연간총마리수"] = aggregate["연간총마리수"]
            if aggregate["시드번호"]:
                row["시드번호"] = aggregate["시드번호"]

    def read_match_rows(self):
        with self.db() as conn:
            db_rows = conn.execute(
                """
                SELECT
                    m.id AS match_id,
                    m.name AS match_name,
                    m.uploaded_at,
                    m.match_type,
                    e.rank,
                    e.name,
                    e.seed_number,
                    e.fish_count,
                    e.final_weight,
                    e.points
                FROM entries e
                JOIN matches m ON m.id = e.match_id
                ORDER BY m.id DESC, e.id ASC
                """
            ).fetchall()

        rows = []
        for row in db_rows:
            match_row = {
                "대회ID": row["match_id"],
                "대회명": row["match_name"],
                "일시": row["uploaded_at"],
                "대회종류": row["match_type"],
                "순위": row["rank"],
                "이름": self.get_primary_name(row["name"]),
                "시드번호": row["seed_number"],
                "마리수": row["fish_count"],
                "최종중량": self.format_number(row["final_weight"]),
                "획득점수": row["points"],
            }
            rows.append(match_row)
        return rows

    def ensure_match_file_columns(self):
        if not os.path.exists(self.match_file) or os.path.getsize(self.match_file) == 0:
            return

        rows, columns = self.read_csv_with_fallback(self.match_file)
        if set(self.MATCH_COLUMNS).issubset(columns):
            return

        required_columns = [
            column for column in self.MATCH_COLUMNS if column not in self.OPTIONAL_MATCH_COLUMNS
        ]
        if not set(required_columns).issubset(columns):
            return

        normalized_rows = []
        for row in rows:
            normalized_rows.append({column: row.get(column, "") for column in self.MATCH_COLUMNS})

        with open(self.match_file, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=self.MATCH_COLUMNS)
            writer.writeheader()
            writer.writerows(normalized_rows)

    @staticmethod
    def read_csv_with_fallback(file_path):
        last_error = None
        for encoding in ("utf-8-sig", "cp949"):
            try:
                with open(file_path, newline="", encoding=encoding) as csv_file:
                    reader = csv.DictReader(csv_file)
                    fieldnames = [
                        ScoreManagerApp.clean_cell(fieldname)
                        for fieldname in (reader.fieldnames or [])
                    ]
                    rows = []
                    for row in reader:
                        normalized_row = {}
                        for key, value in row.items():
                            normalized_key = ScoreManagerApp.clean_cell(key)
                            if normalized_key:
                                normalized_row[normalized_key] = ScoreManagerApp.clean_cell(value)
                        rows.append(normalized_row)
                    return rows, fieldnames
            except UnicodeDecodeError as e:
                last_error = e

        raise last_error

    @staticmethod
    def build_match_label(row):
        return (
            f"{row.get('일시', '')} | "
            f"{row.get('대회종류', '')} | "
            f"{row.get('대회명', '')}"
        )

    @staticmethod
    def build_match_tab_text(row):
        match_name = row.get("대회명", "") or "대회"
        label = ScoreManagerApp.extract_parenthesized_text(match_name) or match_name
        return label[:24]

    @staticmethod
    def extract_parenthesized_text(value):
        text = ScoreManagerApp.clean_cell(value)
        start = text.find("(")
        end = text.rfind(")")
        if start == -1 or end == -1 or end <= start:
            return ""
        return text[start + 1 : end].strip()

    def get_name_filter(self):
        if not hasattr(self, "name_filter"):
            return ""
        return self.clean_cell(self.name_filter.get()).lower()

    def get_entry_name(self, value):
        if not hasattr(self, "open_name_mode") or self.open_name_mode.get():
            return self.get_primary_name(value)
        return self.clean_cell(value)

    @staticmethod
    def name_matches_filter(name, filter_text):
        normalized_filter = ScoreManagerApp.clean_cell(filter_text).lower()
        if not normalized_filter:
            return True
        return normalized_filter in ScoreManagerApp.clean_cell(name).lower()

    @staticmethod
    def clean_cell(value):
        return "" if value is None else str(value).strip()

    @staticmethod
    def is_dash_value(value):
        return ScoreManagerApp.clean_cell(value) in {"-", "－", "—", "–"}

    @classmethod
    def has_dash_value_by_alias(cls, row, aliases):
        for alias in aliases:
            if cls.is_dash_value(row.get(alias)):
                return True

        normalized_aliases = {cls.normalize_key(alias) for alias in aliases}
        for key, value in row.items():
            if cls.normalize_key(key) in normalized_aliases and cls.is_dash_value(value):
                return True
        return False

    @classmethod
    def has_score_dash_marker(cls, row):
        return (
            cls.has_dash_value_by_alias(row, cls.FISH_COUNT_ALIASES)
            or cls.has_dash_value_by_alias(row, cls.WEIGHT_ALIASES)
            or cls.has_dash_value_by_alias(row, cls.SCORE_ALIASES)
        )

    @staticmethod
    def get_primary_name(value):
        name = ScoreManagerApp.clean_cell(value)
        if not name:
            return ""

        for separator in (",", "，"):
            if separator in name:
                name = name.split(separator, 1)[0]
                break

        return ScoreManagerApp.clean_cell(name)

    @staticmethod
    def is_blank_row(row):
        return not any(ScoreManagerApp.clean_cell(value) for value in row.values())

    @classmethod
    def get_fish_count(cls, row):
        return cls.get_value_by_alias(row, cls.FISH_COUNT_ALIASES)

    @classmethod
    def get_seed_number(cls, row):
        return cls.get_value_by_alias(row, cls.SEED_NUMBER_ALIASES)

    @classmethod
    def get_value_by_alias(cls, row, aliases):
        for alias in aliases:
            value = cls.clean_cell(row.get(alias))
            if value:
                return value

        normalized_aliases = {cls.normalize_key(alias) for alias in aliases}
        for key, value in row.items():
            if cls.normalize_key(key) in normalized_aliases:
                cleaned_value = cls.clean_cell(value)
                if cleaned_value:
                    return cleaned_value
        return ""

    @classmethod
    def has_column_alias(cls, columns, aliases):
        normalized_columns = {cls.normalize_key(column) for column in columns}
        return any(cls.normalize_key(alias) in normalized_columns for alias in aliases)

    @staticmethod
    def normalize_key(value):
        return "".join(
            char
            for char in ScoreManagerApp.clean_cell(value).lower()
            if char.isalnum()
        )

    @staticmethod
    def format_number(value):
        return f"{value:g}"

    @classmethod
    def master_sort_key(cls, row):
        return (
            -cls.safe_int(row.get("종합점수")),
            -cls.safe_float(row.get("연간총중량")),
            -cls.safe_int(row.get("연간총마리수")),
            cls.seed_sort_key(row.get("시드번호")),
            cls.clean_cell(row.get("이름")),
        )

    @classmethod
    def seed_sort_key(cls, value):
        seed_text = cls.clean_cell(value)
        if not seed_text:
            return (1, 10**9, "")
        try:
            return (0, int(float(seed_text)), seed_text)
        except ValueError:
            return (0, 10**9, seed_text)

    @classmethod
    def get_stored_match_score(cls, row):
        if row.get("대회종류") == "정규전" and cls.safe_float(row.get("최종중량")) < 0:
            return 0
        if row.get("대회종류") == "정규전" and cls.safe_int(row.get("마리수")) == 0:
            return 30
        if row.get("대회종류") == "스페셜":
            return 30 if cls.safe_int(row.get("획득점수")) != 0 else 0
        return cls.safe_int(row.get("획득점수"))

    @staticmethod
    def rank_sort_key(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 10**9

    @staticmethod
    def safe_int(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def safe_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


if __name__ == "__main__":
    root = tk.Tk()
    app = ScoreManagerApp(root)
    root.mainloop()
