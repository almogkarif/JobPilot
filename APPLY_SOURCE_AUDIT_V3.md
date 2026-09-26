# התקנת תיקון מקורות v3

מיועד **לגרסה שכבר קיבלה את שני הפאטצ׳ים הקודמים**. אין צורך לשחזר ZIP או למחוק קבצים. אין לפרוס מקורות חדשים על בסיס בדיקות מקומיות בלבד.

## 1. החלה מתוך תיקיית jobpilot
שמור את `jobpilot-source-audit-v3-20260926.patch` **בתוך תיקיית jobpilot**, כפי ששמרת את הפאטצ׳ הקודם.

```bash
PATCH="./jobpilot-source-audit-v3-20260926.patch"
git apply --check "$PATCH" && git apply "$PATCH"
```

אין הודעה בהצלחה. אם מופיעה שגיאת התאמה, עצור; אין להפעיל `--reject`, לדרוס את כל הפרויקט או לבצע reset. הקובץ נבדק מול ה-ZIP של גרסת followup, לא מול שינויים נוספים שאולי נעשו מקומית.

## 2. בדיקה ממוקדת אחת
כאשר הסביבה `.venv` פעילה:

```bash
python scripts/audit_source_health.py --v3 --output source-health-live-v3.json
```

זו בדיקת 16 מקורות: 12 יעדי שינוי ועוד Arbe, Flex, Matrix ו-Sunflower להשוואה. היא כוללת גם מקורות כבויים לבדיקה, אבל **לא מפעילה אותם** ולא שומרת משרות במסד הנתונים. תוצאות נשמרות אחרי כל מקור. מזהה הגרסה בדוח: `source-audit-v3-20260926`.

בסיום, כשמופיעה שורת `Report:`:

```bash
open -R source-health-live-v3.json
```

העלה לצ׳אט את הקובץ המסומן. לא צריך שוב את כל 104 המקורות או את ZIP הקוד לצורך בדיקת התיקון הזה.

## 3. בדיקות תוכנה מקומיות
לבדיקות המקורות החדשות והקודמות בלבד:

```bash
python -m pytest -q tests/test_source_audit_v3_20260926.py tests/test_source_audit_followup_20260926.py tests/test_source_audit_20260926.py tests/test_source_quality.py tests/test_source_recovery.py tests/test_retym_speedata_recovery.py
```

בדיקות mock אינן אימות של תגובת אתר חי. אל תפעיל מקור שהיה כבוי רק משום שה-fixture שלו עבר.

## 4. שמירה ב-Git — אחרי בדיקת התוצאות וה-diff
לא בוצע commit, push או deploy בחבילה הזו. הפקודות הבאות עשויות לכלול גם עריכות קודמות שלך באותם קבצים; בדוק אותן לפני commit. יתר הקבצים מהפאטצ׳ים הקודמים אינם נכנסים אוטומטית ל-commit הזה.

```bash
git status --short
git diff -- app/collectors/elad.py app/collectors/expansion_ats.py app/collectors/official.py app/collectors/workday.py app/services/source_quality.py scripts/audit_source_health.py tests/test_retym_speedata_recovery.py tests/test_source_audit_v3_20260926.py

git add app/collectors/elad.py app/collectors/expansion_ats.py app/collectors/official.py app/collectors/workday.py app/services/source_quality.py scripts/audit_source_health.py tests/test_retym_speedata_recovery.py tests/test_source_audit_v3_20260926.py docs/audits/source_audit_v3_2026-09-26.md docs/audits/source_audit_v3_2026-09-26.json docs/audits/verification_v3_2026-09-26.json docs/audits/verification/v3 APPLY_SOURCE_AUDIT_V3.md SOURCE_AUDIT_V3_MANIFEST.json
git diff --cached --stat
git commit -m "Repair bounded source routes and reject directory payloads"
git push origin main
```

אם push מפעיל פריסה אוטומטית אצלך, הוא גם מפעיל תהליך פריסה. אל תריץ אותו לפני סקירת הבדיקה החיה. לא נדרשת מיגרציה; איחוד המקורות, הדירוג וברירות המחדל להפעלת מקורות לא שונו.

## מה צפוי ומה אינו מובטח
שבעה קוראים חדשים/חלופיים נוספו, אך טרם התקבלה בדיקת רשת של קוד v3. ב-Cal וב-Migdal תוקנה הכתובת בלבד. ב-SCD וב-Siemens נחסמות רשומות שגויות; זה אינו אישור לשחזור האיסוף. רשומות שלא מופיעות באיסוף חלקי נשמרות, ולכן מעבר ל-ID של ATS עשוי להצדיק בדיקת כפילויות היסטוריות נפרדת.

דוח מלא: `docs/audits/source_audit_v3_2026-09-26.md`.
