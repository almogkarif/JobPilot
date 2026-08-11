# JobPilot Cloud v0.3.2 — מדריך התקנה ל־Multi‑User

הגרסה הזו מיועדת גם לקבוצה קטנה של בערך **10 משתמשים**. האתר, מסד הנתונים וסריקת המשרות נמצאים בענן; לכל משתמש יש סביבת JobPilot פרטית לחלוטין, בעוד סוכן ההגשות שלו נשאר על ה־Mac האישי שלו.

## מה מופרד בין המשתמשים

לכל חשבון נשמרים בנפרד: פרופיל, שני מסלולי המקצוע, Skills, העדפות חיפוש, מקורות והמצב שלהם, משרות, ציוני Matching, קורות חיים, הגשות, Blockers, תשובות שמורות, היסטוריה ו־Agent devices. גם קבצים ב־Storage נשמרים תחת namespace נפרד לכל משתמש.

הדפדפן לא ניגש ישירות ל־PostgreSQL. כל בקשה עוברת דרך FastAPI, שמוסיף `user_id` באופן אוטומטי לכל SELECT/UPDATE/DELETE/INSERT של מידע פרטי. Agent token מקושר גם הוא ל־`user_id` אחד בלבד.

## 1. יצירת פרויקט Supabase

צור פרויקט חדש ב־Supabase. תחת Authentication הפעל Email/Password, ואם רוצים גם Google — הפעל Google provider והגדר את כתובת JobPilot הסופית כ־redirect URL מורשה.

שמור:

- Project URL
- Publishable key (`sb_publishable_...`) — מותר בדפדפן
- Secret key (`sb_secret_...`) — **שרת בלבד**
- PostgreSQL Session Pooler connection string עם SSL

JobPilot יוצר לבד את הטבלאות ואת bucket הפרטי `jobpilot-private`.

## 2. מי מורשה להיכנס

ב־Render הגדר:

```text
JOBPILOT_MAX_USERS=10
JOBPILOT_ALLOWED_EMAILS=you@example.com,friend1@example.com,friend2@example.com
JOBPILOT_OWNER_EMAIL=you@example.com
JOBPILOT_APPLICATION_AGENT_OWNER_EMAIL=almogkarif@gmail.com
```

`JOBPILOT_ALLOWED_EMAILS` הוא allowlist אופציונלי אך מומלץ מאוד לקבוצה פרטית. אם הוא ריק, כל משתמש Supabase מאומת יכול להצטרף עד שמגיעים ל־`JOBPILOT_MAX_USERS`.

`JOBPILOT_OWNER_EMAIL` כבר **לא נועל את האתר למשתמש יחיד**. הוא רק מסמן את החשבון הזה כ־admin. אם הוא ריק, המשתמש הראשון שמתקבל הופך ל־admin.

## 3. העברת JobPilot המקומי הקיים לענן

מומלץ לבצע migration לפני השימוש הראשון בענן:

```bash
source .venv/bin/activate
export JOBPILOT_CLOUD_DATABASE_URL='postgresql://...'
export JOBPILOT_SUPABASE_URL='https://YOUR_PROJECT.supabase.co'
export JOBPILOT_SUPABASE_SECRET_KEY='sb_secret_...'
export JOBPILOT_SUPABASE_STORAGE_BUCKET='jobpilot-private'
python scripts/migrate_to_cloud.py
```

המידע המקומי הקיים נכתב זמנית תחת workspace בשם `legacy-owner`. **המשתמש הראשון שמורשה ונכנס ל־JobPilot מקבל אוטומטית את כל המידע הקיים הזה**, כך שאין צורך לדעת מראש את Supabase User UUID שלו.

אם רוצים לשייך את המידע מראש ל־UUID מסוים, אפשר להוסיף:

```bash
export JOBPILOT_MIGRATION_USER_ID='SUPABASE_USER_UUID'
```

קורות החיים וה־screenshots עוברים ל־Storage תחת תיקיית משתמש נפרדת.

## 4. העלאה ל־Render

העלה את הפרויקט ל־GitHub private repository וצור Render Blueprint דרך `render.yaml`.

מלא את כל המשתנים עם `sync: false`, במיוחד:

```text
JOBPILOT_ALLOWED_EMAILS
JOBPILOT_OWNER_EMAIL
JOBPILOT_DATABASE_URL
JOBPILOT_BASE_URL
JOBPILOT_SUPABASE_URL
JOBPILOT_SUPABASE_PUBLISHABLE_KEY
JOBPILOT_SUPABASE_SECRET_KEY
JOBPILOT_CRON_SECRET
```

הגדרות ברירת המחדל לקבוצה קטנה הן:

```text
JOBPILOT_MAX_USERS=10
JOBPILOT_MAX_CONCURRENT_USER_SCANS=2
JOBPILOT_SCAN_CONCURRENCY=3
JOBPILOT_SOURCE_SCAN_TIMEOUT_SECONDS=45
```

כלומר עד שני משתמשים נסרקים במקביל, ובכל סריקה עד שלושה מקורות רצים במקביל. זה מונע מעשרה משתמשים לפתוח בבת אחת עשרות Chromium/network collectors על שרת קטן.

## 5. התחברות

כל משתמש נכנס עם Google או Email/Password. לאחר ההתחברות JobPilot יוצר לו workspace נפרד עם שני המסלולים:

```text
User A
├── Computer Science
└── Industrial Engineering & Management

User B
├── Computer Science
└── Industrial Engineering & Management
```

המסלול הפעיל, המקורות, הסקילים והמשרות של User A אינם משפיעים על User B.

בחשבון ה־admin חלון החשבון מציג גם מונה ורשימה של המשתמשים שנרשמו (למשל `3/10`) עם role ו־last seen. משתמש רגיל אינו יכול לקרוא את רשימת החשבונות. הוספה/הגבלה של כתובות נעשית דרך `JOBPILOT_ALLOWED_EMAILS`, כך שאין כפתור מחיקה מסוכן שמוחק בטעות workspace של משתמש.

## 6. חיבור Agent לכל משתמש

כל משתמש נכנס לחשבון שלו באתר ולוחץ **חבר Mac חדש**. ה־token שנוצר שייך רק אליו.

ב־Mac שלו:

```bash
./configure-cloud-agent.sh https://YOUR-JOBPILOT-HOST
./start-agent.sh
```

Agent של משתמש א׳ יכול לקבל רק הגשות של משתמש א׳. גם אם מישהו יודע `application_id` של משתמש אחר, שכבת ה־tenant בשרת לא תחזיר אותו.

אפשר לחבר יותר ממחשב אחד לאותו חשבון ולבטל כל מכשיר בנפרד.

## 7. סריקות אוטומטיות לכמה משתמשים

GitHub Actions ממשיך לקרוא פעם בשעה ל־`/api/cron/scan`. השרת עובר על כל המשתמשים המורשים ובודק עבור כל אחד בנפרד:

- מהו המסלול הפעיל שלו
- האם כבר בוצעה הסריקה היומית
- האם כבר רצה עבורו סריקה אחרת

רק המסלול הפעיל של כל משתמש נסרק. CS ו־תעו״נ של אותו משתמש לעולם לא נסרקים יחד.

## 8. אבטחה והפרדת מידע

- לכל טבלת מידע פרטית יש `user_id`.
- שכבת SQLAlchemy מוסיפה סינון tenant אוטומטי גם ל־SELECT וגם ל־UPDATE/DELETE.
- INSERT מקבל את `user_id` מה־session המאומת; כתיבה ללא user scope נחסמת ב־Cloud Mode.
- קורות חיים ו־screenshots נשמרים תחת `users/<user-id>/...` ב־Storage הפרטי.
- Agent token נשמר רק כ־SHA‑256 hash ומשויך למשתמש אחד.
- Publishable key יכול להגיע לדפדפן; Secret key נשאר בשרת בלבד.
- ב־PostgreSQL/Supabase מופעל RLS ומבוטלת גישה ישירה של `anon`/`authenticated` לטבלאות JobPilot, כך שה־publishable key לא יכול לעקוף את ה־API.
- סיסמת Google לא מגיעה ל־JobPilot.

## 9. Local Mode

המצב המקומי נשאר נתמך בדיוק כמו קודם:

```text
JOBPILOT_AUTH_MODE=local
JOBPILOT_STORAGE_MODE=local
```

ב־Local Mode המשתמש הפנימי הוא `local-owner`, ולכן אותו קוד ו־schema ממשיכים לעבוד גם בלי ענן.


## הרשאת Application Agent בתקופת הבטא
סוכן ההגשות שמפעיל Chromium מוגבל כרגע לחשבון שמוגדר ב־`JOBPILOT_APPLICATION_AGENT_OWNER_EMAIL` — כרגע `almogkarif@gmail.com`. שאר המשתמשים ממשיכים לקבל חיפוש, דירוג, מקורות וקישורי הגשה ידניים, אבל אינם יכולים לחבר Agent או להכניס משרה לתור האוטומטי.

מתגי המקורות נשמרים בנפרד לכל משתמש ולכל מסלול מקצועי: כיבוי מקור אצל משתמש אחד אינו מכבה אותו אצל משתמש אחר.
