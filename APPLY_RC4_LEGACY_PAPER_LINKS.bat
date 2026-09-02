@echo off
cd /d "%~dp0"
echo This applies only unique, exact plan matches. Ambiguous rows are never changed.
python migrate_rc4_legacy_paper_links.py --apply
pause
