"""Stage 6 (owner-gated): upload final.mp4 to YouTube via Data API v3.

This is a scaffold. It will NOT run until the owner creates OAuth credentials.
Without pipeline/credentials.json it exits with a clear Russian instruction on
exactly what to do at console.cloud.google.com.

Metadata is read from the reviewed publish-package.json, never from a filename.

    python upload.py --episode ../episodes/ep001-shortest-war
    python upload.py --episode ../episodes/ep001-shortest-war --privacy public
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import EpisodePaths, PIPELINE_DIR, load_config, read_json, write_json
from product import release_approval_valid

CREDENTIALS_PATH = PIPELINE_DIR / "credentials.json"
TOKEN_PATH = PIPELINE_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

CREDS_HELP_RU = f"""
[upload] НЕ НАЙДЕН файл с OAuth-ключами: {CREDENTIALS_PATH}

Загрузка на YouTube пока НЕ настроена. Чтобы включить её, владельцу нужно один раз
создать OAuth-креды (бесплатно):

  1. Открой https://console.cloud.google.com/ и создай новый проект
     (например "agent-shorts-uploader").
  2. APIs & Services -> Library -> найди "YouTube Data API v3" -> Enable.
  3. APIs & Services -> OAuth consent screen -> тип External -> заполни название,
     e-mail; в разделе Test users ДОБАВЬ свой Google-аккаунт (иначе доступа не будет).
  4. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID ->
     Application type: "Desktop app" -> Create.
  5. Скачай JSON и положи его СЮДА:
     {CREDENTIALS_PATH}
  6. Установи библиотеки (один раз):
     ./.venv/bin/pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
  7. Запусти снова: ./.venv/bin/python upload.py --episode <dir>
     Откроется браузер для входа; токен сохранится в token.json (спросит только раз).

ВАЖНО (квоты и приватность, правила с декабря 2025):
  - Один вызов videos.insert стоит ~100 единиц квоты. Дневная квота по умолчанию
    10 000 единиц => примерно 100 загрузок в сутки бесплатно. Обычно хватает с запасом.
  - Пока приложение в статусе "Testing"/непроверенное, YouTube ПРИНУДИТЕЛЬНО ставит
    загруженные видео в приватный доступ (privacyStatus=private), даже если просишь public.
    Чтобы публиковать публично, проект нужно провести через верификацию Google
    (OAuth verification) ИЛИ переключать видео вручную в YouTube Studio после загрузки.
""".strip()

LIBS_HELP_RU = """
[upload] Не установлены Google-библиотеки. Установи их в venv:
  ./.venv/bin/pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
""".strip()


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _load_credentials():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        _fail(LIBS_HELP_RU)

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _build_body(package: dict, privacy: str) -> dict:
    hashtags = " ".join(package.get("hashtags", []))
    description = (package.get("description", "") + "\n\n" + hashtags).strip()
    return {
        "snippet": {
            "title": package.get("title", "Untitled Short")[:100],
            "description": description[:4900],
            "tags": package.get("tags", [])[:30],
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }


def upload(episode_dir: Path, privacy: str = "private") -> str:
    paths = EpisodePaths.for_dir(episode_dir)
    if not paths.final_mp4.exists():
        _fail(f"[upload] Нет файла для загрузки: {paths.final_mp4}. Сначала собери видео (run.py).")
    release_ok, release_reasons = release_approval_valid(paths.root, privacy)
    if not release_ok:
        _fail(
            "[upload] BLOCKED: release approval is missing or stale:\n  - "
            + "\n  - ".join(release_reasons)
            + "\nRun shorts.py qa, release, review the package, then approve-release."
        )
    if not CREDENTIALS_PATH.exists():
        _fail(CREDS_HELP_RU)

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        _fail(LIBS_HELP_RU)

    package = read_json(paths.root / "publish-package.json")
    creds = _load_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    body = _build_body(package, privacy)
    media = MediaFileUpload(str(paths.final_mp4), chunksize=-1, resumable=True, mimetype="video/mp4")

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _status, response = request.next_chunk()
    video_id = response["id"]
    verification = youtube.videos().list(part="snippet,status", id=video_id).execute()
    item = (verification.get("items") or [{}])[0]
    actual_title = (item.get("snippet") or {}).get("title")
    actual_privacy = (item.get("status") or {}).get("privacyStatus")
    release_status = {
        "version": 2,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "video_id": video_id,
        "url": f"https://youtube.com/shorts/{video_id}",
        "requested_privacy": privacy,
        "actual_privacy": actual_privacy,
        "expected_title": package["title"],
        "actual_title": actual_title,
        "verified": actual_title == package["title"] and actual_privacy == privacy,
        "youtube_response": item,
    }
    write_json(paths.root / "release-status.json", release_status)
    if actual_title != package["title"]:
        _fail(f"[upload] Uploaded but title verification failed: {actual_title!r}")
    if actual_privacy != privacy:
        _fail(
            f"[upload] Uploaded but privacy verification failed: "
            f"requested={privacy!r}, actual={actual_privacy!r}"
        )
    print(
        f"[upload] OK https://youtube.com/shorts/{video_id} "
        f"(requested={privacy}, actual={actual_privacy}, title={actual_title!r})"
    )
    return video_id


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload final.mp4 to YouTube")
    parser.add_argument("--episode", required=True, help="episode working directory")
    parser.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    load_config()  # validate config presence early
    upload(Path(args.episode), privacy=args.privacy)


if __name__ == "__main__":
    main()
