# Predare

Se execută imediat când proprietarul scrie „limită” sau „predare” (sau `/predare`).
Scopul: munca poate fi continuată fără greșeală de **orice agent** (inclusiv un model rapid precum Gemini Flash sau
Codex / GPT Go) care nu știe nimic despre conversația de acum. Nu începi nimic nou.

1. **Verificare rapidă:** Rulează `bash scripts/check_fast.sh`. Reține câte teste trec și dacă pică vreunul.
2. **Actualizează `PROGRESS.md` (în stil „mură în gură”):**
   - Tabelul de status: statusul etapei (`În lucru` sau `Gata`), branch-ul, agentul, note scurte.
   - **„Pasul următor exact”** (scris detaliat pentru un model rapid care nu are voie să ghicească):
     a. Ce este deja gata (numele exacte ale fișierelor și funcțiilor scrise).
     b. Ce lipsește exact: **calea completă a fișierelor** de creat/modificat, **semnăturile funcțiilor**, **formula /
        logica pas cu pas** și trimiterea la secțiunea din `docs/GHID_EXECUTIE_AGENTI.md`.
     c. Comanda exactă de verificare (`uv run pytest ...` și `bash scripts/check.sh`).
     d. Ce agent trebuie să preia pasul următor (`Claude Code` pentru B3/B5, sau `Orice agent: Gemini Flash / Codex / Antigravity` pentru B4/B6c/B7).
   - **„Bug-uri cunoscute”**: numărul de teste pytest verzi și eventualele teste roșii.
   - **„Ultima actualizare”**: data, agentul, ce s-a salvat.
3. **Salvează pe GitHub:**
   - Rulează `git status -s`: verifică obligatoriu că `.env` NU apare în listă!
   - Rulează `git add -A && git commit -m "handoff: <etapa> - <ce urmeaza>" && git push -u origin HEAD`.
4. **Mesaj pentru proprietar** (în română simplă, maximum 3–4 rânduri): ce s-a salvat pe GitHub, pe ce branch, și în ce
   agent să deschidă conversația următoare cu `/preia`.
