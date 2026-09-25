הדוח העדכני: [shadow-8](comparison-v8.html), [הכרעת 27 המקרים והבדיקות](V8.md).

דוח קודם: [shadow-7](comparison-v7.html), [ביקורת](audit-v7.html), [פרטים ומגבלות](V7.md).

דוח קודם: [shadow-6](comparison-v6.html), [כללים ותוצאות](V6.md).

דוח קודם: [shadow-5](comparison-v5.html), [כללים ותוצאות](V5.md).

דוח קודם: [shadow-4](comparison-v4.html), [מיון המקרים והתוצאות](V4.md).

דוח קודם: [shadow-3](comparison-v3.html), [כללים ותוצאות](V3.md).

# השוואת סיווג משותף — 16 בספטמבר 2026

**עדכון:** [דוח shadow-2](comparison-v2.html) ו[הסבר השינוי במדיניות חשמל](V2.md). הנתונים בהמשך מתעדים את הדוח הראשון.

**מצב: שלב השוואה בלבד. אין החלפת סורק בייצור, שינוי שיוכים, שינוי דירוגים,
כתיבה למסד, מחיקת משרות או הפעלת הגשות. אין טענה לאפס טעויות בעולם האמיתי.**

פתחו את [הדוח האינטראקטיבי](comparison.html) בדפדפן. ניתן לחפש כותרת/חברה,
לסנן לפי מסלול, לבדוק הבדלים מול המסווג הישן, לזהות כיסוי חדש של מקורות
ולפתוח את הראיות להחלטה. הדוח עצמאי ואינו טוען משאבים מהרשת.

## מה נבנה

- תוכנית איחוד לוחות לפי סוג הסורק ומזהה הלוח, ולא לפי שם החברה. לוחות שונים
  של אותה חברה נשארים נפרדים. פרמטרי איסוף סותרים חוסמים מיזוג אוטומטי.
- איסוף משותף של לוח פעם אחת וסיווג כל משרה לכל שלושת המסלולים. משרה יכולה
  להשתייך ליותר ממסלול אחד. הפונקציה מקבלת עד חמישה מקורות לבדיקה מפורשת.
- סיווג מועמד מסביר החלטות `match`, `review`, `outside` ללא אחוז ביטחון מומצא.
  תפקיד בפועל קודם לרשימת תארים אפשריים; דרישת תחום סותרת מונעת שיוך אוטומטי.
  תואר כללי בהנדסה אינו ראיה שהמשרה היא בהנדסת חשמל. העדפות תואר וניסיון
  חלופי אינם זהים לדרישת חובה. טקסט חסר, ארוך מדי או מקצוע לא מזוהה מועבר לבדיקה.
- כיבוי מפורש של מקור במסלול נשמר בניתוב המועמד. מקור שלא הוגדר כלל במסלול
  יכול להציע כיסוי חדש. אין הפעלה מחדש של מקור כבוי או מקור בהשהיית שגיאות.
- השוואה נפרדת בין כללי הסיווג הישנים לבין מגבלת הניתוב הישנה לפי מקור.
  תוצאת הכללים הישנים אינה תווית אמת; שינוי אינו בהכרח שיפור.

## תוצאות מקומיות

נבדקו כל **1,796 הרשומות הפעילות** בשלושת המסלולים במאגר המקומי. לאחר איחוד
עותקים זהים של אותה משרת ATS נותרו **1,612 תיאורים ייחודיים**. תיאורים שונים
של אותו מזהה נשארו ראיות נפרדות; לוחות מסוגים שונים אינם מתמזגים לפי כותרת.

- 594 תיאורים עם שינוי בקבוצת השיוכים האוטומטיים לעומת הכללים הישנים.
- 537 משרות עם צורך בבדיקה לפחות במסלול אחד; חלקן מתאימות בוודאות למסלול אחר.
- 413 רשומות מקור, 281 זהויות לוח שונות. לאחר כיבויים/השהיות, 373 צמדי
  מסלול–לוח מתכנסים ל־256 הפעלות סורק משותפות: 117 הפעלות כפולות שניתן לחסוך.
  זו תוכנית איסוף, לא אישור שכל 256 הלוחות פועלים ולא מספר בקשות HTTP.

| מסלול | שיוך אוטומטי מועמד | לבדיקה | ללא התאמה |
| --- | ---: | ---: | ---: |
| מדעי המחשב | 598 | 507 | 507 |
| הנדסת חשמל | 323 | 239 | 1,050 |
| תעשייה וניהול | 127 | 259 | 1,226 |

זהו הקטלוג שהמערכת הקודמת כבר אספה. הוא אינו כולל את כל המשרות שהיא סיננה
בעבר, ולכן אי אפשר להסיק ממנו שיעור איתור מלא של משרות רלוונטיות בשוק.
הדוח אינו משקף זמינות נוכחית של כל המשרות באתרי המעסיקים.

## בדיקה חיה קטנה, לפני הסינון למסלול

| לוח | משרות שהוחזרו | בישראל | מצב |
| --- | ---: | ---: | --- |
| Melio | 24 | 9 | הצליח |
| AutoDS | 5 | 5 | הצליח |
| Nift | 12 | 3 | הצליח |
| G-STAT | 33 | 33 | הצליח; הלוח מסומן חלקי |
| GE HealthCare | — | — | הסורק החזיר PreserveExistingJobs |

74 רשומות מארבעה לוחות הצליחו, מתוכן 50 בישראל. נמצאו ארבע מועמדות לכיסוי
תוכנה חדש בלוחות המוגדרים רק לתעשייה וניהול: שלוש ב־G-STAT ואחת ב־Nift.
Melio כבר מוגדר גם במדעי המחשב ואינו נספר כתוספת כיסוי. נדרשת סקירת דרישות
המשרות לפני מעבר לניתוב אוטומטי. המקורות החדשים מושווים גם להגדרות הקטלוג
המומלץ כשהם עדיין אינם מותקנים במאגר המקומי.

GE HealthCare רשום כמקור, אך עצם הרישום אינו מעיד על איסוף תקין. הבדיקה שלו
נכשלה ולא נספרה כתוצאה ריקה מוצלחת. לא בוצעה כאן החלפת המתאם שלו.

## בדיקות איכות והגבלות

44 מקרים עם ציפיות ידניות: 30 מקרי קצה/דוגמאות, ו־14 תיאורים מלאים של
משרות אמיתיות מהקטלוג. בכלליים הישנים 35 קבוצות שיוך תאמו לציפיות; היו שמונה
שיוכים עודפים ושיוך צפוי אחד חסר. במועמד 44 קבוצות תאמו, ללא שיוכים עודפים
או חסרים **בסט הזה בלבד**. זהו סט רגרסיה ששימש לפיתוח, לא מדגם אקראי או
מדגם בלתי תלוי. דוגמאות GE בסט הן תרחישים מייצגים, לא משרות GE שאומתו ברשת.

216 בדיקות ממוקדות עברו, ועוד בדיקת Chromium לדוח: פילטרים, חיפוש והגנה מפני
הזרקת HTML מתוך כותרת. נבדקו איסוף יחיד, כיבוי מקורות, שגיאות, תוצאות חלקיות,
חריגה ממגבלות, קריאה בלבד למסד והיעדר שינוי במסלולי הסריקה הפעילים. החבילה
המלאה ובדיקות ייצור לא הורצו במסגרת שינוי זה.

**אין אישור מעבר למנגנון החדש:** צריך לתייג מדגם נוסף שלא שימש לפיתוח,
לבדוק אובדן משרות רלוונטיות וגם שיוכים שגויים בכל מסלול, ולפתור את קבוצות
העמימות. לאחר מכן נדרשת תוכנית מעבר מזהי מקורות/משרות שתשמור על היסטוריית
הגשות, בחירות משתמש ודירוגים, עם אפשרות חזרה לאחור. הדוח מחזיר תמיד
`activation_allowed: false`; אין מתג שמפעיל אותו בייצור.

## שחזור

```sh
.venv/bin/python scripts/compare_track_classification.py \
  --database data/jobpilot.db \
  --output /tmp/track-comparison.json \
  --html-output /tmp/track-comparison.html
```

הפקודה מקבלת קובץ SQLite מקומי בלבד, פותחת אותו בקריאה בלבד, קוראת עד 100
משרות בכל עמוד ועד 5,000 משרות בסך הכול, ומגבילה כל תיאור ל־24,001 תווים.
תיאור מעבר ל־24,000 אינו מתקבל אוטומטית. חריגה מהיקף המשרות מסומנת ככיסוי
חלקי. עד 2,000 מקורות; חריגה נכשלת במפורש. אין קריאת מסמכים או פרופילים.

## השפעת תעבורה

תוספת בייצור: **אפס קריאות Supabase לשעה/יום, אפס שורות ואפס בתים**, משום
שהמנגנון אינו מחובר ל־startup, לסורק הפעיל, לדירוג או ל־polling. ההשוואה
המקומית משתמשת ב־SQLite בלבד; הבדיקה החיה קראה לוחות ציבוריים בלבד. לא
הופעלה סריקת ייצור. גבולות הסורקים הציבוריים עצמם נשארים כפי שהם; מגבלת
1,000 תוצאות בהשוואה נבדקת אחרי האיסוף ואינה מגבלת גודל לתשובת HTTP.

אין להסיק מאפס התעבורה בשלב זה תקציב לפריסה עתידית: קריאות הסורק הישן שאינן
חסומות במספר שורות והעברת מודל השיוכים עדיין דורשות תכנון ובדיקת עומס לפי
`docs/SUPABASE_EGRESS.md` לפני הפעלה. הרגרסיות החדשות בקובץ בדיקות התעבורה
מוודאות קריאה מקומית בלבד, עימוד, חסימת תיאורים שנחתכו והיעדר חיבור לייצור.

## Live employer content audit — 17 September 2026

Open `source-content-audit-2026-09-17.html` in a web browser. The standalone report
has employer links, search, status filters, and one evidence row for each of the
191 `source_content` cases in v8. JSON is in the adjacent file of the same name.
This is a new content audit, not a rerun of track classification on different input.

- 111 exact jobs now have full descriptions verified through the corrected parsers:
  Mobileye 90, Microsoft 7, Island 6, TI 3, Speedata 3, Global-e 2.
- 49 explicitly closed: Mobileye 47, Philips 1, Microsoft 1. Philips still serves
  stale JobPosting data; visible closure takes precedence. Microsoft's closed
  status was verified in Chromium; static collection rejects its non-job shell.
- 2 Matrix records were category pages (17 and 5 actual job cards respectively).
  The new bounded collector follows category pages and identifies individual jobs.
- 29 remain unresolved due to access blocking: Rafael 27, Fiverr 1, Papaya 1.
  A normal browser did not resolve those blocks. They are not marked closed.

Changes are local and have not been committed, pushed, or deployed. No production
rows were updated/deactivated. Existing collectors stay partial, so legacy closed
or category records require a separate explicit reconciliation; absence from a
partial scan must never delete them. The original v8 snapshot/report is unchanged.
Mobileye's current live body was already recoverable by generic parsing in some
cases; its historical missing-content cause is not proven for every record.

Verification:

- 96 focused collector/parser/egress tests passed, none skipped.
- A broader run passed 153 tests and failed two existing assertions in
  `tests/test_iem_source_expansion.py`: the implementation returns
  `iem_required_degree_discipline_mismatch`, while the tests expect older reason
  codes. The matching, career-track and corresponding test files are unchanged
  from Git HEAD. These failures were not weakened or hidden.
- Full repository suite was not run.
- Cached real-page integration recovered all 90 live Mobileye records and rejected
  its 47 closed pages; TI/Speedata/Microsoft/Island hydration was verified against
  fetched exact URLs. Global-e feed matched the two exact ATS UIDs. Matrix cached
  categories were parsed into distinct jobs; a full live Matrix crawl was not run.
- Chromium verified the report: 191 rows, 29 blocked, 27 Rafael after search.
- Independent reviewer checked identity preservation, partial-collection behavior,
  closure handling, and byte caps. A redirect-budget issue found in review was
  fixed and covered by a regression test.
- Resource estimates and deployment constraints are in `../SUPABASE_EGRESS.md`.

## Comparison v9 — recovered local content, same shadow-8 classifier

Open `comparison-v9-content-recovery.html`; `content-recovery-changes.html` shows
before/after tracks and degree colors for each of the 111 recovered descriptions.
`content-recovery-manifest.json` records exact affected local IDs and the SHA-256
of the untouched original snapshot. Only `/tmp/jobpilot-recovered-2026-09-17.sqlite`
was updated. The original v8 database/report and production remain unchanged.

1,800 active local rows / 1,623 unique payloads remain after excluding 49 closed
jobs and two category records. All 111 recovered payloads were replaced using
hash-verified audit descriptions. 100 changed candidate track membership and 87
changed degree colors; these are new-evidence changes, not classifier-rule fixes.
The other 1,512 identical payloads changed neither track nor degree color.
29 blocked records remain explicitly unverified in the source-content review group.
No new Matrix vacancies were introduced: category records were excluded only.

Eight recovered records remain in classification review (four repeated patterns):
- Mobileye 455/456/457: Embedded Linux OS Architect. Full content describes OS
  software architecture, but the classifier misses this family and uses red
  rather than the agreed software-without-explicit-degree yellow treatment.
- Mobileye 462/463/464: Embedded SW integration/automation team leadership.
  A line break inside `B.Sc\n. or higher in Computer Engineering or Computer Science`
  prevents detection of an explicit accepted degree; the role family is also missed.
- Mobileye 549: hardware/robotics testing and validation. The coordinated phrase
  `Mechanical, Electrical, or Mechatronics Engineering` is not recognized as EE.
  The text also mentions a China engineering center; this shadow report does not
  establish geographic eligibility and must not be treated as a ready-to-display job.
- TI 1775: hardware emulation/validation. The coordinated requirement
  `Electrical / communication Engineering` is missed in degree coloring; CS is
  left for review. Hardware team context points to EE rather than general CS.

These findings are deliberately visible rather than manually overriding decisions
in the report. This run changes input only; degree parsing and role recognition
still require regression fixes before activation. The two pre-existing broader
IEM test failures documented above also remain; this task did not alter their code.
No network requests or Supabase reads/writes were needed for this rerun.

## Comparison v10 — shadow-9 classification fixes

`comparison-v10.html` compares the same recovered local input as v9. All eight
classification-review records are resolved; only the 29 blocked source-content
cases remain. 20 payloads changed matched tracks and 24 changed degree colors,
including 16 additional payloads affected by the same academic wording fixes.
Their extracted academic clauses were reviewed. There are no new review cases.

Changes: repair B.Sc/M.Sc punctuation across whitespace before academic fields;
recognize a shared final Engineering noun in Electrical/Computer, Electrical/
communication and Mechanical, Electrical, or Mechatronics degree lists; recognize
Linux OS architecture and embedded SW integration/automation leadership using
both title and body evidence. IT scripting alone is still insufficient. No
company-name or vacancy-ID overrides were added. Generic/related-degree policy
is unchanged. Geography remains a separate filter; job 549's China context is not
an approval to display it to an Israel-only user.

Validation: 251 non-browser classification/comparison tests passed. The browser
report test initially could not launch Chromium inside the sandbox; it passed when
rerun with the required execution permission. Eight new regression cases cover
real recovered descriptions, preferred degrees, unrelated electrical experience,
and IT integration. Full application suite was not run. Prior unrelated IEM
reason-code assertion failures remain documented above. No production imports,
DB writes, network collection, commit, push or deployment were performed.

## Blocked-case recheck and developer lifetime metrics

All 29 exact URLs were fetched again; 27 Rafael responses remain HTTP247 challenge,
Fiverr and Papaya HTTP403. A normal browser check of Rafael9048, Fiverr and Papaya
also remained blocked. No role was proven closed. Evidence is in
`blocked-recheck-2026-09-17.json`; successful access in the user's browser is
compatible with these environment-specific results.

Developer overview now includes global unique observed-job and ever-blocked-job
counts. Identity is source kind + board identifier + external job ID, independent
of track copies and retry count. Recovery never clears historical blocking.
A durable ledger survives job deletion; the UI explicitly warns that deleted jobs
and unrecorded blocks predating tracking cannot be reconstructed. Source-only
blocks without identifiable job IDs are not turned into invented job counts.
Detail access-block metadata is propagated by Official, Workday and SmartRecruiters;
all collectors' successful jobs are recorded by the scanner before track/location
filtering. Existing full descriptions are not replaced by blocked detail shells.

The additive ledger was initialized in local `data/jobpilot.db` using the explicit
local-only `scripts/initialize_collection_history.py` script. The 29 rechecked
URLs were imported by exact URL match; old numerical audit IDs were not trusted.
Only ledger rows were added, not job statuses/descriptions. Counters may also include
other independently recorded blocked jobs and are not hard-coded to this29subset.
Nothing was deployed or pushed. Earlier local dashboard preview work is preserved.

Verification includes duplicate scans, recovery, track copies, different boards,
retained/deleted jobs, exact audit imports, blocked scan preservation, developer
browser cards, admin gating and a single aggregate query with no description read.
The new table is part of the existing Postgres RLS/revoke list. Live PostgreSQL
migration was not executed. New-blocked-job display policy was asked separately;
no unverified description or fabricated qualification is introduced by these metrics.
