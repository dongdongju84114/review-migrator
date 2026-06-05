from __future__ import annotations

import ftplib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from review_migrator.schemas import ImageMatch


@dataclass(frozen=True)
class FtpStorageConfig:
    host: str
    user: str
    password: str
    remote_dir: str
    public_base_url: str
    protocol: str = "ftp"
    port: int = 21
    use_tls: bool = False
    passive: bool = True
    timeout: float = 30

    @classmethod
    def from_env(cls, *, public_base_url: str | None = None) -> "FtpStorageConfig":
        protocol = os.getenv("CAFE24_UPLOAD_PROTOCOL") or os.getenv("CAFE24_FTP_PROTOCOL", "ftp")
        protocol = protocol.strip().lower()
        if protocol not in {"ftp", "ftps", "sftp"}:
            raise ValueError("CAFE24_UPLOAD_PROTOCOL은 ftp, ftps, sftp 중 하나여야 합니다.")
        return cls(
            host=os.environ["CAFE24_FTP_HOST"],
            user=os.getenv("CAFE24_FTP_USER") or os.environ["CAFE24_FTP_USERNAME"],
            password=os.environ["CAFE24_FTP_PASSWORD"],
            remote_dir=os.environ["CAFE24_FTP_REMOTE_DIR"],
            public_base_url=public_base_url or os.environ["CAFE24_IMAGE_BASE_URL"],
            protocol=protocol,
            port=int(os.getenv("CAFE24_FTP_PORT", "22" if protocol == "sftp" else "21")),
            use_tls=protocol == "ftps" or _env_bool("CAFE24_FTP_USE_TLS", default=False),
            passive=_env_bool("CAFE24_FTP_PASSIVE", default=True),
            timeout=float(os.getenv("CAFE24_FTP_TIMEOUT", "30")),
        )

    def public_url_for(self, file_name: str) -> str:
        return f"{self.public_base_url.rstrip('/')}/{quote(file_name)}"

    def remote_file_for(self, file_name: str) -> str:
        return f"{self.remote_dir.rstrip('/')}/{file_name}"


class FtpImageUploader:
    def __init__(self, config: FtpStorageConfig) -> None:
        self.config = config

    def upload_files(self, paths: list[Path]) -> None:
        if not paths:
            return
        if self.config.protocol == "sftp":
            self._upload_files_sftp(paths)
            return
        ftp = self._connect_ftp()
        try:
            _ensure_remote_dir(ftp, self.config.remote_dir)
            for path in paths:
                with path.open("rb") as file:
                    ftp.storbinary(f"STOR {path.name}", file)
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    def _connect_ftp(self):
        ftp_class = ftplib.FTP_TLS if self.config.use_tls else ftplib.FTP
        ftp = ftp_class()
        ftp.connect(self.config.host, self.config.port, timeout=self.config.timeout)
        ftp.login(self.config.user, self.config.password)
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        ftp.set_pasv(self.config.passive)
        return ftp

    def _upload_files_sftp(self, paths: list[Path]) -> None:
        try:
            import paramiko
        except ImportError as error:
            raise RuntimeError("SFTP 업로드에는 paramiko 패키지가 필요합니다. 설치 후 다시 실행해주세요.") from error

        transport = paramiko.Transport((self.config.host, self.config.port))
        transport.banner_timeout = self.config.timeout
        transport.auth_timeout = self.config.timeout
        transport.connect(username=self.config.user, password=self.config.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            remote_dir = _ensure_sftp_remote_dir(sftp, self.config.remote_dir)
            for path in paths:
                remote_path = f"{remote_dir.rstrip('/')}/{path.name}" if remote_dir != "/" else f"/{path.name}"
                sftp.put(str(path), remote_path)
        finally:
            sftp.close()
            transport.close()


def missing_cafe24_ftp_settings(*, public_base_url: str | None = None) -> list[str]:
    missing = []
    if not os.getenv("CAFE24_FTP_HOST"):
        missing.append("CAFE24_FTP_HOST")
    if not (os.getenv("CAFE24_FTP_USER") or os.getenv("CAFE24_FTP_USERNAME")):
        missing.append("CAFE24_FTP_USER")
    if not os.getenv("CAFE24_FTP_PASSWORD"):
        missing.append("CAFE24_FTP_PASSWORD")
    if not os.getenv("CAFE24_FTP_REMOTE_DIR"):
        missing.append("CAFE24_FTP_REMOTE_DIR")
    if not (public_base_url or os.getenv("CAFE24_IMAGE_BASE_URL")):
        missing.append("CAFE24_IMAGE_BASE_URL 또는 GUI 이미지 공개 URL")
    return missing


def has_any_cafe24_ftp_setting() -> bool:
    keys = [
        "CAFE24_FTP_HOST",
        "CAFE24_FTP_USER",
        "CAFE24_FTP_USERNAME",
        "CAFE24_FTP_PASSWORD",
        "CAFE24_FTP_REMOTE_DIR",
        "CAFE24_IMAGE_BASE_URL",
        "CAFE24_UPLOAD_PROTOCOL",
        "CAFE24_FTP_PROTOCOL",
    ]
    return any(os.getenv(key) for key in keys)


def stage_or_upload_matches_to_ftp(
    matches: list[ImageMatch],
    manifest_rows: list[dict[str, object]],
    *,
    config: FtpStorageConfig,
    upload: bool,
    uploader: FtpImageUploader | None = None,
) -> tuple[list[ImageMatch], list[dict[str, object]]]:
    rows_by_local_file = {
        str(row.get("local_file")): row
        for row in manifest_rows
        if row.get("status") == "downloaded" and row.get("local_file")
    }
    upload_paths = [Path(path) for path in rows_by_local_file]

    if upload:
        (uploader or FtpImageUploader(config)).upload_files(upload_paths)

    local_file_to_public_url: dict[str, str] = {}
    for local_file, row in rows_by_local_file.items():
        file_name = Path(local_file).name
        public_url = config.public_url_for(file_name)
        row["remote_file"] = config.remote_file_for(file_name)
        row["public_url"] = public_url
        row["status"] = "uploaded" if upload else "planned"
        local_file_to_public_url[local_file] = public_url

    updated_matches = []
    for match in matches:
        image_urls = [local_file_to_public_url[path] for path in match.image_files if path in local_file_to_public_url]
        updated_matches.append(
            match.model_copy(
                update={
                    "image_urls": image_urls,
                    "warning": None if image_urls else match.warning,
                }
            )
        )
    return updated_matches, manifest_rows


def _ensure_remote_dir(ftp, remote_dir: str) -> None:
    parts = [part for part in remote_dir.strip("/").split("/") if part]
    if remote_dir.startswith("/"):
        try:
            ftp.cwd("/")
        except ftplib.error_perm:
            pass
    for part in parts:
        try:
            ftp.cwd(part)
        except ftplib.error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def _ensure_sftp_remote_dir(sftp, remote_dir: str) -> str:
    parts = [part for part in remote_dir.strip("/").split("/") if part]
    current = "/"
    if remote_dir.startswith("/"):
        try:
            sftp.chdir("/")
        except OSError:
            current = ""
    else:
        current = sftp.getcwd() or ""
    for part in parts:
        next_dir = f"{current.rstrip('/')}/{part}" if current else part
        try:
            sftp.chdir(next_dir)
        except OSError:
            sftp.mkdir(next_dir)
            sftp.chdir(next_dir)
        current = sftp.getcwd() or next_dir
    return current or "."


def _env_bool(key: str, *, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
