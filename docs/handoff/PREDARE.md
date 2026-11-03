# Predare

Se execută imediat când proprietarul scrie doar „limită” sau „predare” (sau `/predare`).
Scopul: munca poate fi continuată de alt agent care nu știe nimic despre conversația de acum. Nu începi nimic nou.

1. **Verificare.** Rulează `scripts/check_fast.sh` (dacă există). Reține ce trece și ce pică.
2. **Actualizează `PROGRESS.md`:** statusul etapei, branch-ul, agentul; ce e gata; ce e pe jumătate (fișierele exacte și
   ce lipsește din fiecare); „Pasul următor exact”, scris pentru un agent care nu știe nimic; „Bug-uri cunoscute”
   (inclusiv testele care pică); „Ultima actualizare”: data, agentul, etapa.
3. **Salvează pe GitHub.** `git status`: verifică că `.env` NU apare. Dacă apare, oprește-te și repară `.gitignore`.
   Dacă ești pe `main` și etapa are branch propriu, `git checkout -b etapa-<N>-<nume>`. Apoi `git add -A`,
   `git commit -m "handoff: etapa <N> – <ce urmează>"` (și cu teste roșii, notate la bug-uri), `git push -u origin HEAD`.
4. **Mesaj pentru proprietar**, o frază: unde se continuă (branch și pas) și ce agent, după tabelul „Cine face ce” din `AGENTS.md`.
