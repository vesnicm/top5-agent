#!/usr/bin/env python3
"""
Top 5 agent: uzima 5 najslušanijih pesama sa Deezer top liste
i šalje ih kao poruku na Telegram.

Pokreće se:
  - automatski svakog dana u 9h po beogradskom vremenu (GitHub Actions),
  - ručno, kad god pritisneš "Run workflow" na GitHub-u.

Potrebne promenljive okruženja (na GitHub-u se podešavaju kao "Secrets"):
  TELEGRAM_BOT_TOKEN  token bota koji dobiješ od @BotFather
  TELEGRAM_CHAT_ID    broj tvog četa sa botom

Opciono:
  ANTHROPIC_API_KEY   ključ za Anthropic (Claude) API; ako postoji, poruci se dodaje
                      kratak komentar koji napiše LLM. Bez ključa (ili ako poziv
                      ne uspe) poruka se šalje normalno, samo bez komentara.
  ANTHROPIC_MODEL     model koji piše komentar (podrazumevano claude-haiku-5-5)
  DRY_RUN=1           ne šalje poruku, nego je samo ispiše
"""

import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------- podešavanja
TZ = ZoneInfo("Europe/Belgrade")
SEND_HOUR = 9                 # sat slanja po beogradskom vremenu
TOP_N = 5                     # koliko pesama ide u poruku
COMPARE_DEPTH = 50            # koliko pesama pamtimo radi poređenja sa jučerašnjom listom
DEEZER_URL = f"https://api.deezer.com/chart/0/tracks?limit={COMPARE_DEPTH}"
STATE_FILE = Path(__file__).resolve().parent / "state" / "history.json"
HISTORY_DAYS = 14

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-5-5"
COMMENT_MAX_CHARS = 400       # LLM komentar se seče na ovu dužinu, da poruka ostane kratka

DANI = ["ponedeljak", "utorak", "sreda", "četvrtak", "petak", "subota", "nedelja"]
MESECI = ["januar", "februar", "mart", "april", "maj", "jun", "jul",
          "avgust", "septembar", "oktobar", "novembar", "decembar"]


# ------------------------------------------------------------ kada se šalje
def should_run_now(now: datetime) -> bool:
    """
    GitHub zakazuje samo po UTC vremenu, a Beograd menja vreme (zimsko/letnje).
    Zato workflow ima dva rasporeda (07:00 i 08:00 UTC), a ovde propuštamo
    samo onaj koji odgovara 9h po beogradskom vremenu tog dana.
    Ručno pokretanje (workflow_dispatch) uvek prolazi.
    """
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return True
    schedule = os.environ.get("TRIGGER_SCHEDULE", "").split()
    if len(schedule) >= 2 and schedule[1].isdigit():
        utc_hour = int(schedule[1])
        offset_hours = int(now.utcoffset().total_seconds() // 3600)
        return (utc_hour + offset_hours) % 24 == SEND_HOUR
    return now.hour == SEND_HOUR


# --------------------------------------------------------------- Deezer API
def fetch_chart(attempts: int = 3) -> list[dict]:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(DEEZER_URL, headers={"User-Agent": "top5-agent/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.load(resp)
            if "error" in payload:
                raise RuntimeError(f"Deezer je vratio grešku: {payload['error']}")
            tracks = payload.get("data") or []
            if len(tracks) < TOP_N:
                raise RuntimeError(f"Deezer je vratio samo {len(tracks)} pesama")
            return [
                {
                    "id": t["id"],
                    "title": t.get("title_short") or t.get("title", "Nepoznato"),
                    "artist": (t.get("artist") or {}).get("name", "Nepoznat izvođač"),
                    "album": (t.get("album") or {}).get("title", ""),
                    "cover": (t.get("album") or {}).get("cover_medium", ""),
                    "link": t.get("link", ""),
                    "duration": int(t.get("duration") or 0),
                }
                for t in tracks
            ]
        except Exception as exc:  # mreža, JSON, prazan odgovor...
            last_error = exc
            print(f"Pokušaj {attempt}/{attempts} nije uspeo: {exc}", file=sys.stderr)
            if attempt < attempts:
                time.sleep(20 * attempt)
    raise RuntimeError(f"Ne mogu da preuzmem Deezer listu: {last_error}")


# ------------------------------------------------- memorija (jučerašnja lista)
def load_history() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_history(history: dict, today: str, chart: list[dict]) -> None:
    history[today] = [t["id"] for t in chart]
    for old in sorted(history)[:-HISTORY_DAYS]:
        del history[old]
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(history, indent=2, sort_keys=True), encoding="utf-8")


def previous_positions(history: dict, today: str) -> dict | None:
    earlier = [d for d in history if d < today]
    if not earlier:
        return None
    ids = history[max(earlier)]
    return {track_id: pos for pos, track_id in enumerate(ids, start=1)}


def movement(track_id: int, position: int, prev: dict | None) -> tuple[str, str]:
    """Vraća (tekst, boja) za oznaku promene u odnosu na prethodni dan."""
    if prev is None:
        return "", ""
    old = prev.get(track_id)
    if old is None:
        return "NOVO", "#1D9E75"
    if old > position:
        return f"▲ {old - position}", "#1D9E75"
    if old < position:
        return f"▼ {position - old}", "#D85A30"
    return "=", "#888780"


# ------------------------------------------------- LLM komentar (Anthropic API)
def generate_comment(top: list[dict], prev: dict | None, attempts: int = 2) -> str | None:
    """
    Traži od LLM-a (Claude, preko Anthropic Messages API-ja) kratak komentar dana
    na osnovu današnjeg top 5. Vraća tekst ili None.

    Komentar je dodatak: ako nema ključa ili poziv ne uspe, vraća None i
    agent svejedno šalje običnu poruku (LLM nikad ne sme da obori slanje liste).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ANTHROPIC_API_KEY nije podešen, šaljem poruku bez komentara.", file=sys.stderr)
        return None

    # LLM dobija samo podatke koje već imamo; ne tražimo od njega da "zna" pesme.
    lista = []
    for pos, t in enumerate(top, start=1):
        label, _ = movement(t["id"], pos, prev)
        lista.append(f"{pos}. {t['title']} - {t['artist']}" + (f" ({label})" if label else ""))

    prompt = (
        "Evo današnjih 5 najslušanijih pesama na Deezer-u"
        + (" (u zagradi je promena u odnosu na juče: NOVO, ▲ ili ▼ je promena pozicije, = bez promene)"
           if prev is not None else "")
        + ":\n\n" + "\n".join(lista)
    )
    system = (
        "Pišeš kratak jutarnji komentar uz dnevnu top listu pesama, za poruku na Telegramu. "
        "Piši na srpskom jezikom (latinica), najviše 2 rečenice, opušteno i bez emotikona. "
        "Osvrni se na ono što se vidi u listi: ko je na vrhu, ima li novih pesama, ko se penje ili pada. "
        "Koristi isključivo podatke koje dobiješ. Ne izmišljaj činjenice o pesmama, "
        "albumima, izvođačima ili njihovim rezultatima. Vrati samo tekst komentara."
    )
    body = json.dumps({
        "model": os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "max_tokens": 200,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(
                ANTHROPIC_URL, data=body,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
            text = "".join(
                block.get("text", "") for block in payload.get("content", [])
                if block.get("type") == "text"
            ).strip()
            if not text:
                raise RuntimeError("LLM je vratio prazan odgovor")
            return text[:COMMENT_MAX_CHARS]
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}"
            if exc.code < 500 and exc.code != 429:
                break  # pogrešan ključ ili zahtev: ponovni pokušaj ne pomaže
        except Exception as exc:  # mreža, JSON, prazan odgovor...
            last_error = exc
        print(f"LLM pokušaj {attempt}/{attempts} nije uspeo: {last_error}", file=sys.stderr)
        if attempt < attempts:
            time.sleep(5)
    print(f"Komentar nije generisan ({last_error}), šaljem poruku bez njega.", file=sys.stderr)
    return None


# ------------------------------------------------------------------- poruka
def format_date(now: datetime) -> str:
    text = f"{DANI[now.weekday()]}, {now.day}. {MESECI[now.month - 1]} {now.year}."
    return text[0].upper() + text[1:]


def build_message(top: list[dict], prev: dict | None, now: datetime, manual: bool,
                  comment: str | None = None) -> str:
    """Sastavlja Telegram poruku (HTML format koji Telegram podržava)."""
    e = lambda x: html.escape(x, quote=False)
    lines = [f"<b>Top {TOP_N} najslušanijih na Deezer-u</b>", e(format_date(now)), ""]
    for pos, t in enumerate(top, start=1):
        label, _ = movement(t["id"], pos, prev)
        mins, secs = divmod(t["duration"], 60)
        lines.append(f"<b>{pos}. {e(t['title'])}</b>" + (f"   {e(label)}" if label else ""))
        lines.append(f"{e(t['artist'])} · {mins}:{secs:02d}")
        if t["link"]:
            lines.append(f'<a href="{html.escape(t["link"], quote=True)}">Slušaj na Deezer-u</a>')
        lines.append("")
    if comment:
        lines.append(f"<b>Komentar dana:</b> {e(comment)}")
        lines.append("")
    lines.append("<i>" + ("Poslato na tvoj zahtev." if manual else "Tvoj jutarnji pregled, svakog dana u 9h.")
                 + ("" if prev is None else " Oznake pokazuju promenu u odnosu na prethodni dan.") + "</i>")
    return "\n".join(lines)


def send_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
    body = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Telegram je odbio poruku ({exc.code}): {detail}") from None
    if not result.get("ok"):
        raise RuntimeError(f"Telegram je vratio grešku: {result}")


def send_error_message(error: Exception) -> None:
    """Ako nešto pukne, javi to porukom umesto da agent samo ćuti."""
    try:
        send_telegram(html.escape(
            f"Top 5 agent danas nije uspeo da pošalje listu.\n\nGreška: {error}\n\n"
            "Proveri poslednje pokretanje na GitHub-u (kartica Actions).", quote=False))
    except Exception as exc:
        print(f"Ni poruka o grešci nije poslata: {exc}", file=sys.stderr)


# ------------------------------------------------------------------- glavni tok
def main() -> int:
    now = datetime.now(TZ)
    if not should_run_now(now):
        print("Ovaj zakazani termin ne odgovara 9h po beogradskom vremenu, preskačem.")
        return 0

    manual = os.environ.get("GITHUB_EVENT_NAME") not in (None, "", "schedule")
    dry_run = os.environ.get("DRY_RUN") == "1"
    today = now.date().isoformat()

    try:
        chart = fetch_chart()
        history = load_history()
        prev = previous_positions(history, today)
        comment = generate_comment(chart[:TOP_N], prev)
        message = build_message(chart[:TOP_N], prev, now, manual, comment)

        if dry_run:
            print(f"DRY_RUN: poruka nije poslata\n\n{message}")
        else:
            send_telegram(message)
            print("Poruka poslata na Telegram.")

        save_history(history, today, chart)
        return 0
    except Exception as exc:
        print(f"Greška: {exc}", file=sys.stderr)
        if not dry_run:
            send_error_message(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
