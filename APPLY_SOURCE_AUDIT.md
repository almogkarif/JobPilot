# החלת תיקוני המקורות — 26.09.2026

זהו עדכון לקובץ jobpilot-source-20260926-190035.zip שהועלה. אין שינוי בדירוג, באיחוד שלושת המסלולים, בברירות המחדל של המקורות, בסכמת הנתונים או בתלויות.

**לפני פריסה:** גבה את הפרויקט ואת מסד הנתונים. הבדיקות כאן הן מקומיות; איסוף HTTP חי אינו מאומת. אל תמחק .env, data או קבצי משתמש בגלל שאינם כלולים ב-ZIP הנקי.

## החלה באמצעות patch

הצב את קובץ ה-patch בשורש הפרויקט והריץ:

```bash
git status --short
git apply --check jobpilot-source-audit-20260926.patch
git apply jobpilot-source-audit-20260926.patch
```

במקרה של כשל בבדיקת ההתאמה, עצור: הקוד המקומי אינו תואם בדיוק לנקודת המוצא, ואין לדרוס את השינויים שלך.

אפשר גם להשתמש בעותק ה-ZIP המלא כפרויקט נפרד לצורך בדיקה. ה-ZIP אינו מחליף את בסיס הנתונים או את הגדרות הענן.

## אימות ללא DB

מתוך ה-venv הקיים:

```bash
python -m pytest -q tests/test_source_audit_20260926.py tests/test_source_recovery.py tests/test_collector_completeness.py
python scripts/audit_source_health.py
```

בדיקת הרשת מייצרת source-health-live.json ומבקרת שמונה יעדים. היא אינה שומרת משרות, אינה נוגעת ב-DB ואינה שולחת מועמדויות. האיסוף החדש עדיין דורש אימות מהמחשב/שרת שלך. הרחבה לכל המועמדים:

```bash
python scripts/audit_source_health.py --all-flagged --output source-health-live-all.json
```

## רפאל: dry-run לפני שינוי מפורש

רק בסביבה המכוונת למסד הנתונים הנכון, לאחר גיבוי:

```bash
python scripts/repair_source_audit.py
```

בדוק את התכנית. רק כשמופיעה retire_invalid_ashby_duplicate עם מקור רשמי תואם, ולא needs_review, ניתן להחיל:

```bash
python scripts/repair_source_audit.py --apply
```

הכלי פורש את רשומת Ashby הפגומה בלבד. אין מחיקת משרות ואין הבטחה שגישת אתר רפאל הרשמי תעבוד. עדיף לבדוק תחילה מול עותק מקומי.

## שמירה ב-Git

רק לאחר בדיקת התוצאה וה-diff. הפקודה הבאה מוסיפה רק את שמות הקבצים המופיעים ב-patch; שמותיהם בחבילה הזו אינם מכילים רווחים. בכל זאת, שינויים קודמים באותם קבצים ייכללו, ולכן יש לבדוק את ה-diff לפני commit.

```bash
git add -- $(git apply --numstat jobpilot-source-audit-20260926.patch | cut -f3)
git diff --cached --stat
git diff --cached
git commit -m "Audit job sources and harden collection safety"
git push
```

לא בוצעו commit, push או פריסה במסגרת הביקורת. הרצת pytest המסוננת: 1,524 עברו, 89 דולגו, 5 לא נבחרו; עוד 13 קובצי דפדפן הוחרגו. מידע מלא והחרגות ב-docs/audits/verification_2026-09-26.json.

## הדוח

פתח docs/audits/source_audit_2026-09-26.html לדוח עברי עם חיפוש וסינון של 104 המקורות. גרסאות Markdown, CSV ו-JSON נמצאות לידו. לא כל מקור שוחזר; גבולות האימות מפורטים לכל מקור.
