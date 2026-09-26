# החלת תיקון מקורות v4 — JobPilot

מיועד רק לפרויקט שכבר מכיל את פאטצ׳ v3. שמור את הפאטצ׳ **בתוך תיקיית jobpilot**, לא בתיקיית Downloads שמעליה. אין צורך להחליף תיקיות באמצעות ה־ZIP המלא.

## החלה

מתוך תיקיית `jobpilot`:

```bash
PATCH="./jobpilot-source-audit-v4-20260926.patch"
git apply --check "$PATCH" && git apply "$PATCH"
```

אם אין שגיאה ואין פלט, ההחלה הצליחה. במקרה של שגיאת התאמה, לעצור ולא להשתמש ב־`--reject`, לא להפעיל force ולא לדרוס את הפרויקט. הודעת ״כבר הוחל״ אינה סיבה להחיל שוב.

## בדיקה ממוקדת — פקודה אחת

אם הסביבה אינה פעילה, הפעל אותה:

```bash
source .venv/bin/activate
```

לאחר מכן:

```bash
python scripts/audit_source_health.py --v4 --output source-health-live-v4.json
```

נבדקים אותם 16 מקורות של v3, כולל בקרות. אין צורך בבדיקה נוספת של כל 104 המקורות. האבחון כולל קטעי מבנה מסוננים מהעמודים הציבוריים בתוך אותו JSON. לא נכתבות משרות למסד הנתונים, לא נשלחות מועמדויות ולא משתנות הגדרות הפעלה.

כשתופיע `Report:`, הצג את הקובץ ב־Finder:

```bash
open -R source-health-live-v4.json
```

העלה לצ׳אט רק את הקובץ הזה. הדוח נשמר גם אחרי כל מקור שהושלם, ולכן עצירה לא מאבדת תוצאות קודמות. עצירה אינה בדיקה מלאה.

## בדיקות יחידה מקומיות (לא חובה לצורך הפקת הדוח)

```bash
python -m pytest -q tests/test_source_audit_v4_20260926.py tests/test_dynamic_official_api_adapters.py
```

בדיקות אלה סינתטיות; הן אינן מאמתות את זמינות אתרי המעסיקים ברשת.

## שמירה ב־Git, לאחר סקירת הדוח והשינויים

אין לבצע push רק בגלל שהפאטצ׳ הוחל. בדוק תחילה את תוצאות האיסוף החי; push עלול להפעיל פריסה אוטומטית בסביבתך. הפקודות הבאות כוללות רק את קובצי v4; שינויים מוקדמים יותר שלא נשמרו דורשים סקירה נפרדת ב־`git status`.

```bash
git status --short
git add .gitignore app/collectors/audit_diagnostics.py app/collectors/elad.py app/collectors/expansion_ats.py app/collectors/official.py app/collectors/workday.py scripts/audit_source_health.py tests/test_source_audit_v3_20260926.py tests/test_source_audit_v4_20260926.py docs/audits/source_audit_v4_2026-09-26.md APPLY_SOURCE_AUDIT_V4.md SOURCE_AUDIT_V4_MANIFEST.json
git diff --cached --stat
git commit -m "Improve source recovery and bounded audit diagnostics"
git push
```

אין להוסיף `source-health-live*.json`, `.env`, קורות חיים או פרופיל דפדפן ל־Git. החרגת דוחות ב־`.gitignore` אינה מסירה קבצים שכבר נוהלו ב־Git.

## גבולות v4

תיקון וריאציות HTML של Elad וגיבוי Retym נבדקו מקומית, אך טרם התקבל איסוף חי לאחר השינוי. שיפור אבחון של כאל, SCD, Siemens, מגדל, StarkWare, Analog Devices ו־Jabil אינו אישור לשחזורם. המקורות הכבויים לא הופעלו אוטומטית, ו־partial אינו שקול לאיסוף מלא.
