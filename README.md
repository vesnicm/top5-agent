# Top 5 agent (Telegram)

Svakog dana u 9h (po beogradskom vremenu) šalje ti Telegram poruku sa 5 najslušanijih pesama na Deezer-u. Kad god poželiš, ručno ga pokreneš i poruka stiže za minut.

U poruci: pozicija, naslov, izvođač, trajanje, link „Slušaj na Deezer-u“ i oznaka promene u odnosu na prethodni dan (▲ / ▼ / = / NOVO).

Opciono (LLM): ako dodaš tajnu `ANTHROPIC_API_KEY`, agent pozove Claude (Anthropic Messages API) koji na osnovu današnje liste napiše kratak komentar dana na srpskom, pa se on doda na kraj poruke. LLM dobija samo podatke sa liste (naslov, izvođač, promena pozicije). Ako ključa nema ili poziv ne uspe, poruka se šalje normalno, samo bez komentara. Model se menja promenljivom `ANTHROPIC_MODEL` (podrazumevano `claude-haiku-5-5`).

## Šta je u paketu

| Fajl | Čemu služi |
|---|---|
| `top5_agent.py` | Agent: preuzima listu sa Deezer-a i šalje poruku na Telegram |
| `.github/workflows/top5.yml` | Raspored (9h svaki dan) i dugme za ručno pokretanje |
| `state/history.json` | Memorija agenta: liste od prethodnih dana, za poređenje |

Ne treba ništa da se instalira.

## Postavljanje (jednom, oko 10 minuta)

### 1. Napravi Telegram bota

1. U Telegramu potraži **@BotFather** (ima plavu kvačicu) i otvori ga.
2. Pošalji `/newbot`.
3. Upiši ime bota (bilo šta, npr. `Moj Top 5`).
4. Upiši korisničko ime bota; mora da se završava sa `bot`, npr. `mateja_top5_bot`. Ako je zauzeto, probaj drugo.
5. BotFather ti šalje **token**, dugačak niz oblika `123456789:AAH...`. Kopiraj ga i čuvaj, to je lozinka bota.

### 2. Pokreni svog bota i nađi svoj Chat ID

1. Klikni na link koji ti je BotFather dao (`t.me/tvoj_bot`) i pritisni **Start**. Pošalji botu bilo koju poruku, npr. `zdravo`. Bez ovoga bot ne sme da ti piše.
2. U pregledaču otvori ovu adresu, a umesto `TVOJ_TOKEN` stavi svoj token (bez razmaka):

   `https://api.telegram.org/botTVOJ_TOKEN/getUpdates`

3. Na stranici potraži deo `"chat":{"id":123456789` i kopiraj taj **broj**. To je tvoj Chat ID.

Ako je stranica prazna (`"result":[]`), pošalji botu još jednu poruku u Telegramu i osveži stranicu.

### 3. Napravi repozitorijum na GitHub-u

1. Na github.com klikni **New repository**.
2. Ime npr. `top5-agent`, izaberi **Private** i klikni **Create repository**.
3. Klikni **uploading an existing file** i prevuci sve fajlove iz paketa, uključujući folder `.github`.

> Na Mac-u je `.github` skriven u Finder-u: pritisni `Cmd + Shift + .` da ga vidiš. Na Windows-u uključi „Hidden items“ u File Explorer-u.

4. Klikni **Commit changes**.

Proveri da u repozitorijumu postoji putanja `.github/workflows/top5.yml`. Bez nje raspored ne radi.

### 4. Dodaj tajne

U repozitorijumu: **Settings → Secrets and variables → Actions → New repository secret**. Dodaj dve tajne:

| Ime | Vrednost |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token iz koraka 1 |
| `TELEGRAM_CHAT_ID` | broj iz koraka 2 |

Imena moraju biti tačno ovakva (velika slova).

Opciono, za LLM komentar: ključ napraviš na console.anthropic.com (API keys) i dodaš kao treću tajnu `ANTHROPIC_API_KEY`. Bez nje sve radi kao do sada.

### 5. Probaj odmah

1. Otvori karticu **Actions**. Ako GitHub pita, omogući workflow-e.
2. Levo izaberi **Top 5 pesama**.
3. Klikni **Run workflow** → **Run workflow**.
4. Za oko minut poruka stiže na Telegram. Ako ne stigne, otvori to pokretanje u Actions i pogledaj poruku o grešci (najčešće je token ili Chat ID pogrešno prekopiran).

Od sutra poruka stiže sama u 9h.

## Kako se koristi

- **Svako jutro:** ništa ne radiš.
- **Na zahtev:** Actions → Top 5 pesama → **Run workflow**. Radi i iz GitHub aplikacije na telefonu.
- **Oznake promene** pojavljuju se od drugog dana, kad agent ima jučerašnju listu za poređenje.

## Kako radi

1. GitHub pokreće workflow u 07:00 i 08:00 UTC. Pošto Beograd zimi ima UTC+1, a leti UTC+2, skripta propušta samo onaj termin koji je tog dana tačno 9h, pa ništa ne moraš da menjaš kad se pomera sat.
2. Preuzima top listu sa `api.deezer.com/chart/0/tracks` (javni API, bez ključa). Ako Deezer ne odgovori, pokušava još dva puta.
3. Upoređuje je sa prethodnim danom iz `state/history.json` i sastavlja poruku.
4. Šalje poruku preko Telegram bota.
5. Čuva današnju listu u repozitorijumu (videćeš automatske commit-ove „Lista za ...“), poslednjih 14 dana.
6. Ako nešto pukne, šalje ti kratku poruku sa greškom umesto da ćuti.

## Dobro je da znaš

- **Kašnjenje:** GitHub zakazane poslove ponekad pokrene sa zakašnjenjem od nekoliko minuta, pa poruka može stići npr. u 9:05.
- **Koja lista:** koristi se Deezer-ova glavna top lista. Pošto GitHub serveri su uglavnom u SAD, može malo odstupati od liste u Deezer aplikaciji u Srbiji.
- **Cena:** besplatno. Telegram botovi su besplatni, a jedno pokretanje troši oko minut GitHub Actions vremena, daleko ispod besplatnog limita.
- **Token je lozinka:** nikome ga ne šalji. Ako ti procuri, u @BotFather-u pošalji `/revoke` pa napravi novi i zameni ga u GitHub tajnama.

## Prilagođavanje

U vrhu `top5_agent.py`:

- `TOP_N = 5` → koliko pesama ide u poruku.
- `SEND_HOUR = 9` → sat slanja. Ako ga menjaš, promeni i oba `cron` reda u `top5.yml` (UTC sat = željeni sat − 1 za zimu, − 2 za leto).
