from __future__ import annotations

import queue
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk

from review_migrator.config import Settings, crema_token_refresh_callback, load_env_file
from review_migrator.crema.auth import TokenProvider
from review_migrator.crema.client import CremaClient
from review_migrator.crema.permissions import (
    required_permission_failures,
    run_crema_permission_checks,
    write_permission_checks_csv,
)
from review_migrator.crema.products import ProductService
from review_migrator.crema.reviews import ReviewService
from review_migrator.gui_paths import default_env_file, default_output_dir, path_from_text
from review_migrator.pipeline import RunAllOptions, run_all


class ReviewMigratorGui:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("네이버 리뷰 → 크리마 등록 도구")
        self.root.geometry("1280x860")
        self.root.minsize(1120, 760)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False
        self.last_output_dir: Path | None = None
        self.upload_ready = False

        self.naver_export_path = StringVar()
        self.output_dir = StringVar(value=str(default_output_dir()))
        self.env_file = StringVar(value=str(default_env_file()))
        self.crema_products_csv = StringVar()
        self.cafe24_products_csv = StringVar()
        self.additional_image_csv = StringVar()
        self.approve_upload = BooleanVar(value=False)

        self._build()
        self._poll_log_queue()

    def _build(self) -> None:
        style = ttk.Style()
        style.configure("Title.TLabel", font=("", 26, "bold"))
        style.configure("Subtitle.TLabel", font=("", 13))
        style.configure("Status.TLabel", font=("", 14, "bold"))
        style.configure("Primary.TButton", font=("", 13), padding=(14, 10))
        style.configure("Large.TButton", font=("", 13), padding=(14, 10))
        style.configure("Large.TCheckbutton", font=("", 13))
        style.configure("TLabelframe.Label", font=("", 13, "bold"))

        root_frame = ttk.Frame(self.root, padding=22)
        root_frame.pack(fill="both", expand=True)

        title = ttk.Label(root_frame, text="네이버 스마트스토어 리뷰 → 크리마 리뷰 등록", style="Title.TLabel")
        title.pack(anchor="w")
        subtitle = ttk.Label(
            root_frame,
            text="3개 파일을 선택한 뒤 안전 검증을 먼저 실행하세요. 통과한 경우에만 실제 등록을 진행합니다.",
            style="Subtitle.TLabel",
        )
        subtitle.pack(anchor="w", pady=(6, 18))

        form = ttk.LabelFrame(root_frame, text="입력 파일")
        form.pack(fill="x", pady=(0, 12))
        self._file_row(form, "네이버 리뷰 엑셀", self.naver_export_path, self._choose_naver_export, 0)
        self._file_row(form, "마켓플러스 CSV", self.crema_products_csv, self._choose_crema_products_csv, 1)
        self._file_row(form, "카페24 상품 CSV", self.cafe24_products_csv, self._choose_cafe24_products_csv, 2)
        self._file_row(form, "추가 이미지 CSV(선택)", self.additional_image_csv, self._choose_additional_image_csv, 3)
        helper = ttk.Label(
            form,
            text=f"결과 저장 폴더: {self.output_dir.get()} / .env는 실행 파일 또는 프로젝트 폴더의 기본 설정을 사용합니다.",
            wraplength=980,
        )
        helper.grid(row=4, column=1, sticky="w", padx=8, pady=(2, 10))

        controls = ttk.LabelFrame(root_frame, text="실행")
        controls.pack(fill="x", pady=(0, 12))

        button_row = ttk.Frame(controls)
        button_row.pack(fill="x", padx=10, pady=10)
        self.dry_run_button = ttk.Button(
            button_row,
            text="안전 검증 파일 만들기",
            command=self.run_dry_run,
            style="Primary.TButton",
        )
        self.dry_run_button.pack(side="left", padx=(0, 10))
        self.permission_button = ttk.Button(
            button_row,
            text="크리마 권한 확인",
            command=self.check_crema_permissions,
            style="Large.TButton",
        )
        self.permission_button.pack(side="left", padx=(0, 10))
        self.upload_button = ttk.Button(
            button_row,
            text="실제 크리마 등록 실행",
            command=self.run_upload,
            style="Large.TButton",
        )
        self.upload_button.pack(side="left", padx=(0, 10))
        self.open_output_button = ttk.Button(
            button_row,
            text="결과 폴더 열기",
            command=self.open_output_folder,
            style="Large.TButton",
        )
        self.open_output_button.pack(side="left")

        approval = ttk.Checkbutton(
            controls,
            text="실제 등록 승인: 안전 검증 결과가 업로드 가능이고, 크리마에 리뷰를 생성/수정할 수 있음을 확인했습니다.",
            variable=self.approve_upload,
            style="Large.TCheckbutton",
        )
        approval.pack(anchor="w", padx=12, pady=(0, 12))

        self.status = ttk.Label(root_frame, text="대기 중", style="Status.TLabel")
        self.status.pack(anchor="w", pady=(0, 4))

        log_frame = ttk.LabelFrame(root_frame, text="실행 로그")
        log_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text = self._create_log_text(log_frame)

    def _file_row(self, parent: ttk.Frame, label: str, variable: StringVar, command, row: int) -> None:
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text=label, font=("", 13)).grid(row=row, column=0, sticky="w", padx=10, pady=8)
        ttk.Entry(parent, textvariable=variable, font=("", 13)).grid(row=row, column=1, sticky="ew", padx=10, pady=8)
        ttk.Button(parent, text="선택", command=command, style="Large.TButton").grid(
            row=row,
            column=2,
            sticky="e",
            padx=10,
            pady=8,
        )

    def _create_log_text(self, parent: ttk.Frame):
        import tkinter as tk

        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        text = tk.Text(frame, height=26, wrap="word", font=("Menlo", 13))
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return text

    def _choose_naver_export(self) -> None:
        path = filedialog.askopenfilename(
            title="네이버 리뷰 엑셀 선택",
            filetypes=[("Excel/CSV", "*.xlsx *.xls *.csv *.tsv"), ("All files", "*.*")],
        )
        if path:
            self.naver_export_path.set(path)

    def _choose_crema_products_csv(self) -> None:
        path = filedialog.askopenfilename(title="마켓플러스 CSV 선택", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.crema_products_csv.set(path)

    def _choose_cafe24_products_csv(self) -> None:
        path = filedialog.askopenfilename(title="카페24 상품 CSV 선택", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.cafe24_products_csv.set(path)

    def _choose_additional_image_csv(self) -> None:
        path = filedialog.askopenfilename(title="추가 이미지 CSV 선택", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.additional_image_csv.set(path)

    def run_dry_run(self) -> None:
        self._run(approve_upload=False)

    def check_crema_permissions(self) -> None:
        if self.running:
            messagebox.showinfo("실행 중", "이미 실행 중입니다.")
            return
        self.running = True
        self._set_buttons_enabled(False)
        self.status.configure(text="크리마 권한 확인 중")
        self._append_log("\n=== 크리마 권한 확인 시작 ===\n")
        thread = threading.Thread(target=self._check_crema_permissions_thread, daemon=True)
        thread.start()

    def run_upload(self) -> None:
        if not self.upload_ready:
            messagebox.showwarning("안전 검증 필요", "먼저 안전 검증 파일 만들기를 실행하고 상태가 업로드 가능인지 확인해주세요.")
            return
        if not self.approve_upload.get():
            messagebox.showwarning("승인 필요", "실제 등록 승인 체크박스를 먼저 체크해주세요.")
            return
        confirmed = messagebox.askyesno(
            "실제 등록 확인",
            "크리마에 리뷰가 실제로 생성/수정될 수 있습니다.\n계속 진행할까요?",
        )
        if confirmed:
            self._run(approve_upload=True)

    def _run(self, approve_upload: bool) -> None:
        if self.running:
            messagebox.showinfo("실행 중", "이미 실행 중입니다.")
            return
        try:
            options = self._options(approve_upload=approve_upload)
        except ValueError as error:
            messagebox.showerror("입력 확인", str(error))
            return

        if not approve_upload:
            self.upload_ready = False
            self.approve_upload.set(False)
        self.running = True
        self._set_buttons_enabled(False)
        self.status.configure(text="실제 등록 중" if approve_upload else "안전 검증 중")
        self._append_log("\n=== 실제 등록 시작 ===\n" if approve_upload else "\n=== 안전 검증 시작 ===\n")

        thread = threading.Thread(target=self._run_thread, args=(options,), daemon=True)
        thread.start()

    def _options(self, approve_upload: bool) -> RunAllOptions:
        if not self.naver_export_path.get():
            raise ValueError("네이버 리뷰 엑셀을 선택해주세요.")
        if not self.crema_products_csv.get():
            raise ValueError("마켓플러스 CSV를 선택해주세요.")
        if not self.cafe24_products_csv.get():
            raise ValueError("카페24 상품 CSV를 선택해주세요.")
        output_base = path_from_text(self.output_dir.get(), default_output_dir())
        return RunAllOptions(
            naver_export_path=Path(self.naver_export_path.get()),
            product_mapping_path=None,
            image_dir=None,
            additional_image_csv_path=Path(self.additional_image_csv.get()) if self.additional_image_csv.get() else None,
            image_base_url=None,
            image_public_dir=None,
            output_base_dir=output_base,
            env_file=path_from_text(self.env_file.get(), default_env_file()),
            approve_upload=approve_upload,
            auto_build_mapping=True,
            crema_products_csv=Path(self.crema_products_csv.get()) if self.crema_products_csv.get() else None,
            cafe24_products_csv=Path(self.cafe24_products_csv.get()) if self.cafe24_products_csv.get() else None,
        )

    def _run_thread(self, options: RunAllOptions) -> None:
        try:
            summary = run_all(options, log=self.log_queue.put)
            self.last_output_dir = summary.output_dir
            if summary.upload_failed_count:
                self.log_queue.put(f"크리마 등록 실패 {summary.upload_failed_count}건이 있습니다. failed_records.csv를 확인하세요.")
                self.upload_ready = False
                marker = "__WARNING__"
            elif summary.blocking_messages:
                self.log_queue.put("검토 필요 항목이 있습니다. run_summary.html과 failed_mapping.csv를 확인하세요.")
                self.upload_ready = False
                marker = "__WARNING__"
            else:
                if options.approve_upload:
                    self.upload_ready = False
                    self.log_queue.put("__RESET_APPROVAL__")
                else:
                    self.upload_ready = True
                    self.log_queue.put("안전 검증 통과: 실제 등록 승인 체크 후 실제 크리마 등록을 실행할 수 있습니다.")
                self.log_queue.put("완료되었습니다. 결과 폴더를 확인하세요.")
                marker = "__DONE__"
            self.log_queue.put(f"결과 폴더: {summary.output_dir}")
            self.log_queue.put(marker)
        except Exception:
            self.upload_ready = False
            self.log_queue.put(traceback.format_exc())
            self.log_queue.put("__FAILED__")

    def _check_crema_permissions_thread(self) -> None:
        try:
            output_base = path_from_text(self.output_dir.get(), default_output_dir())
            run_dir = output_base / "crema_permissions"
            run_dir.mkdir(parents=True, exist_ok=True)
            output_path = run_dir / "crema_permission_checks.csv"

            self.log_queue.put(".env에서 크리마 인증 정보를 읽습니다.")
            env_file = path_from_text(self.env_file.get(), default_env_file())
            load_env_file(env_file)
            settings = Settings.from_env()
            provider = TokenProvider(
                base_url=settings.crema_api_base_url,
                app_id=settings.crema_app_id,
                secret=settings.crema_secret,
                access_token=settings.crema_access_token,
                on_token_refresh=crema_token_refresh_callback(env_file),
            )
            client = CremaClient(base_url=settings.crema_api_base_url, token_provider=provider)
            checks = run_crema_permission_checks(
                review_service=ReviewService(client),
                product_service=ProductService(client),
                require_product_read=True,
            )
            write_permission_checks_csv(output_path, checks)
            for check in checks:
                self.log_queue.put(
                    f"{check.label}: {check.severity} / required={check.required} / {check.message}"
                )
            self.last_output_dir = run_dir
            self.log_queue.put(f"권한 체크 파일: {output_path}")
            if required_permission_failures(checks):
                self.log_queue.put("__WARNING__")
            else:
                self.log_queue.put("__DONE__")
        except Exception:
            self.log_queue.put(traceback.format_exc())
            self.log_queue.put("__FAILED__")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                message = self.log_queue.get_nowait()
                if message == "__DONE__":
                    self.running = False
                    self.status.configure(text="완료")
                    self._set_buttons_enabled(True)
                    messagebox.showinfo("완료", "실행이 끝났습니다. 결과 폴더를 확인하세요.")
                elif message == "__WARNING__":
                    self.running = False
                    self.status.configure(text="확인 필요")
                    self._set_buttons_enabled(True)
                    messagebox.showwarning("확인 필요", "실행은 끝났지만 확인이 필요한 항목이 있습니다. 결과 폴더를 확인하세요.")
                elif message == "__FAILED__":
                    self.running = False
                    self.status.configure(text="실패")
                    self._set_buttons_enabled(True)
                    messagebox.showerror("실패", "실행 중 오류가 발생했습니다. 실행 로그를 확인하세요.")
                elif message == "__RESET_APPROVAL__":
                    self.approve_upload.set(False)
                else:
                    self._append_log(message + "\n")
        except queue.Empty:
            pass
        self.root.after(50, self._poll_log_queue)

    def _append_log(self, text: str) -> None:
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.root.update_idletasks()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.dry_run_button.configure(state=state)
        self.permission_button.configure(state=state)
        self.upload_button.configure(state=state)
        self.open_output_button.configure(state=state)

    def open_output_folder(self) -> None:
        path = self.last_output_dir or Path(self.output_dir.get())
        if path.exists():
            webbrowser.open(path.resolve().as_uri())
        else:
            messagebox.showwarning("폴더 없음", "아직 결과 폴더가 없습니다.")


def main() -> None:
    root = Tk()
    ReviewMigratorGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
