# Preluare

Se execută când proprietarul scrie „preia” (sau `/preia`). Continui munca unui agent anterior.

1. **Citește obligatoriu, în această ordine:**
   - `AGENTS.md` (regulile, interdicțiile și cine face ce).
   - `PROGRESS.md` (în special tabelul de progres și secțiunea „Pasul următor exact”).
   - `docs/GHID_EXECUTIE_AGENTI.md` (rețeta „mură în gură” cu importurile exacte, numele fișierelor, semnăturile
     funcțiilor și formulele pentru pasul tău).
2. **Verifică ordinea modelelor:**
   - După ce Claude Code termină B3, **orice agent deschis de proprietar** (Antigravity pe Gemini 4 Argon High, apoi
     Gemini 3.8 Flash High sau Codex pe GPT Go / Luna 6 High) are voie să execute pasul următor (B4, B5, B6c, B7),
     urmând la milimetru rețeta din `docs/GHID_EXECUTIE_AGENTI.md`.
   - Folosește sub-agenți ieftini (`flash_lite` / `flash` în Antigravity, `haiku` în Claude Code) pentru sarcinile de
     rutină, ca să nu consumi inutil limita modelului principal.
3. **Vezi starea reală în terminal:**
   - Rulează: `git fetch --all --prune && git status -sb && git log --oneline -8 && bash scripts/check_fast.sh`
4. **Treci pe branch-ul corect** (indicat în „Pasul următor exact” din `PROGRESS.md`):
   - Dacă branch-ul nu există încă, creează-l din `main` actualizat: `git checkout main && git pull && git checkout -b <branch>`.
   - Dacă există deja pe GitHub: `git checkout <branch> && git pull`.
5. **Reconciliază:** Dacă `PROGRESS.md` nu se potrivește cu `git log`, crede git-ul: actualizează `PROGRESS.md`,
   fă commit `preluare: reconciliere PROGRESS.md` și `git push`.
6. **Repară testele roșii** înainte să scrii orice cod nou.
7. **Execută mecanic, pas cu pas**, doar sub-pasul din „Pasul următor exact” (`PROGRESS.md`) și rețeta din
   `docs/GHID_EXECUTIE_AGENTI.md`:
   - Nu inventa funcții deja existente (verifică tabelul din `docs/GHID_EXECUTIE_AGENTI.md` Secțiunea 2).
   - Nu folosi internetul în testele `pytest`.
   - După ce ai scris codul și testele: rulează `bash scripts/check.sh` (trebuie să treacă 100% fără erori ruff sau pytest).
   - Actualizează `PROGRESS.md` (cu pasul următor scris „mură în gură”), fă commit + push, deschide PR spre `main` și
     unește-l după ce CI este verde.
   - **Deploy în Git și în Vercel după fiecare etapă:** după ce PR-ul e unit în `main`, asigură-te că totul este urcat
     pe GitHub și rulează `cd dashboard && vercel --prod --yes` (ca dashboard-ul live de la
     `https://theo-trading-bot.vercel.app` să fie mereu actualizat).
   - La final raportezi proprietarului în română simplă (maximum 5 rânduri) și îi spui să deschidă o conversație nouă.
