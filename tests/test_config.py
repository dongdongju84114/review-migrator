import os

from review_migrator.config import crema_token_refresh_callback, update_env_file_value


def test_update_env_file_value_replaces_existing_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "CREMA_APP_ID=app",
                "CREMA_ACCESS_TOKEN=old-token",
                "CAFE24_IMAGE_BASE_URL=https://example.com/images",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CREMA_ACCESS_TOKEN", "old-token")

    update_env_file_value(env_file, "CREMA_ACCESS_TOKEN", "new-token")

    assert "CREMA_ACCESS_TOKEN=new-token" in env_file.read_text(encoding="utf-8")
    assert "CREMA_ACCESS_TOKEN=old-token" not in env_file.read_text(encoding="utf-8")
    assert os.environ["CREMA_ACCESS_TOKEN"] == "new-token"


def test_crema_token_refresh_callback_appends_missing_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CREMA_APP_ID=app\n", encoding="utf-8")
    monkeypatch.delenv("CREMA_ACCESS_TOKEN", raising=False)

    crema_token_refresh_callback(env_file)("fresh-token")

    assert env_file.read_text(encoding="utf-8").endswith("CREMA_ACCESS_TOKEN=fresh-token\n")
    assert os.environ["CREMA_ACCESS_TOKEN"] == "fresh-token"
