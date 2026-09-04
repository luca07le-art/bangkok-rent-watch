@echo off
REM Passe hebdomadaire : collecte, regenere index.html, publie sur GitHub Pages.
REM Lance par la tache planifiee "bangkok-rent-watch". Tout est journalise dans data\crawl.log.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

py -u main.py       >> data\crawl.log 2>&1
py -u report.py     >> data\crawl.log 2>&1

git add index.html
REM Sans changement de donnees, pas de commit vide.
git diff --cached --quiet && (echo   index.html inchange, rien a publier >> data\crawl.log) || (
  git commit -q -m "Donnees du %DATE%" >> data\crawl.log 2>&1
  git push -q            >> data\crawl.log 2>&1
)
