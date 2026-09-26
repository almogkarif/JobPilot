# JobPilot — ניתוח דוח v3 ותיקון v4

26 בספטמבר 2026 | בסיס: `jobpilot-source-audit-v3-20260926-fixed.zip`

## מה מאומת ומה לא

הראיה לאיסוף חי היא **ההרצה שלך**, `source-health-live-v3.json`, שסיימה ב־`2026-09-26T18:57:46.722766+00:00`. נבדקו 16 מקורות: 8 החזירו נתונים באיסוף חלקי, ו־8 נכשלו או לא אומתו. שמונת האיסופים החלקיים החזירו יחד 190 רשומות שזוהו כישראליות לפני דירוג. זו ספירה מצטברת של תשובות המקורות, לא ספירת משרות חדשות במסד או התאמות אישיות.

ב־Fiverr, Philips ו־Salesforce התקבלו בהתאמה 16, 12 ו־9 רשומות ישראליות, לעומת כשל בהרצת v2. שלושת החיבורים החזירו יחד 37 רשומות ישראליות. לא נטען שאלה 37 משרות חדשות במערכת.

כל שמונת המקורות החיוביים נותרו `snapshot_complete=false`. `quality_ok=true` ו־`complete_descriptions` הן בדיקות יוריסטיות, לא בדיקה ידנית של כל תיאור ולא הוכחה שנאסף כל האתר. המקורות הכבויים אינם מופעלים על ידי כלי הבדיקה.

**v4 הוא תיקון ממוקד לאלעד ולגיבוי Retym, לצד שיפור באבחון. הוא אינו שחזור של שמונת המקורות הכושלים. אין בקובץ זה תוצאות איסוף חי אחרי v4.** סביבת הרצת הקוד לא הצליחה לפתור שמות DNS של אתרי המעסיקים; בדיקת אתרים בכלי הגלישה אינה שקולה להפעלת הקורא בפייתון.

## כל 16 התוצאות

| מקור | v2: רשומות בישראל | v3: רשומות בישראל | v3: סך רשומות | חסומות ב־v3 | מצב הטיפול |
|---|---:|---:|---:|---:|---|
| Analog Devices Careers Israel | לא אומת | לא אומת | לא אומת | לא אומת | עדיין לא אומת |
| Arbe Robotics — Israel | 7 | 7 | 7 | 0 | בקרת רגרסיה |
| Cal — CS Israel | לא אומת | לא אומת | לא אומת | לא אומת | עדיין לא אומת |
| Elad Systems — CS Israel | לא אומת | לא אומת | לא אומת | לא אומת | תיקון בקוד; אימות חי נדרש |
| Fiverr — CS Israel | לא אומת | 16 | 21 | 0 | החיבור החזיר משרות בהרצת המשתמש |
| Flex — Hardware Israel | 10 | 10 | 10 | 0 | בקרת רגרסיה |
| Jabil Careers Israel | לא אומת | לא אומת | לא אומת | לא אומת | עדיין לא אומת |
| Matrix — CS Israel | 100 | 100 | 100 | 0 | בקרת רגרסיה |
| Migdal — CS Israel | לא אומת | לא אומת | לא אומת | לא אומת | עדיין לא אומת |
| Philips Careers Israel | לא אומת | 12 | 12 | 0 | החיבור החזיר משרות בהרצת המשתמש |
| Retym — Semiconductor Israel | 15 | 9 | 28 | 7 | תיקון גיבוי בקוד; אימות חי נדרש |
| Salesforce Careers Israel | לא אומת | 9 | 9 | 0 | החיבור החזיר משרות בהרצת המשתמש |
| SCD — SemiConductor Devices | 0 | לא אומת | לא אומת | לא אומת | זיהויי ניווט שגויים נעצרו; מקור לא שוחזר |
| Siemens EDA — Israel | 0 | לא אומת | לא אומת | לא אומת | זיהויי ניווט שגויים נעצרו; מקור לא שוחזר |
| StarkWare Careers Israel | לא אומת | לא אומת | לא אומת | לא אומת | עדיין לא אומת |
| Sunflower Careers Israel | 27 | 27 | 27 | 0 | בקרת רגרסיה |

## ממצאים פרטניים

### Analog Devices Careers Israel — `analog-devices`

לא שונה הסינון. נוספו סך תוצאות ה־API, המסנן שנבחר וסיבות דחיית הפרטים. התוצאה הריקה לאחר סינון אינה מוכיחה שאין משרות.

הראיה בדוח: `sources[identifier=analog-devices]`, מצב `error_or_unverified`.

הודעת v3: `PreserveExistingJobs: Analog Devices bounded Workday search exposed no verified Israel details; this does not establish that no Israel vacancies exist`

### Arbe Robotics — Israel — `arbe`

7 משרות ישראליות עם שמות תפקיד ותיאורים שסומנו מלאים. ללא שינוי במסלול האיסוף.

הראיה בדוח: `sources[identifier=arbe]`, מצב `partial`.

### Cal — CS Israel — `cal`

העמוד הרשמי מציג תפקידים בתוך דף הרשימה. לא נבנה קורא ספקולטיבי ולא הומצאו מזהים או קישורי הגשה. האבחון שומר מבנה ציבורי מסונן.

הראיה בדוח: `sources[identifier=cal]`, מצב `error_or_unverified`.

הודעת v3: `PreserveExistingJobs: Cal did not expose a reliable job payload; candidate_rows=0, rejected={'detail': 0, 'schema': 0, 'identity': 0, 'navigation': 0}; preserving the last successful snapshot`

### Elad Systems — CS Israel — `elad-systems`

נוספה תמיכה בנקודתיים/סימני כיווניות/תוויות מפוצלות במספר משרה, בתבנית legacy עם H1 שיווקי נוסף ובמיקום משרה מפורש. מספר המשרה, המיקום והדרישות עדיין חייבים להתאים. נוספו סיבות דחייה.

הראיה בדוח: `sources[identifier=elad-systems]`, מצב `error_or_unverified`.

הודעת v3: `PreserveExistingJobs: Elad exposed no identity-bound complete details; preserving previous jobs`

### Fiverr — CS Israel — `fiverr`

21 רשומות, 16 ישראליות; 21 תיאורים שסומנו מלאים. לא שונתה ברירת המחדל של המקור.

הראיה בדוח: `sources[identifier=fiverr]`, מצב `partial`.

### Flex — Hardware Israel — `flex-israel`

10 משרות ישראליות ותיאורים שסומנו מלאים. נותר איסוף חלקי.

הראיה בדוח: `sources[identifier=flex-israel]`, מצב `partial`.

### Jabil Careers Israel — `jabil-israel`

נוספו אבחוני שלבי Workday; לא הוסרו בדיקות המיקום ולא נקבע שאין משרות בישראל.

הראיה בדוח: `sources[identifier=jabil-israel]`, מצב `error_or_unverified`.

הודעת v3: `PreserveExistingJobs: Jabil bounded Workday search exposed no verified Israel details; this does not establish that no Israel vacancies exist`

### Matrix — CS Israel — `matrix-israel`

100 רשומות ישראליות ותיאורים שסומנו מלאים. זו תוצאת הקורא המוגבל, לא מספר המשרות הכולל באתר.

הראיה בדוח: `sources[identifier=matrix-israel]`, מצב `partial`.

### Migdal — CS Israel — `migdal`

הכתובת הנוכחית נפתחה אך רשומה אחת נדחתה מחוסר נתוני משרה מובנים. נוספו קטעי מבנה ציבוריים; לא הוכרז על שחזור.

הראיה בדוח: `sources[identifier=migdal]`, מצב `error_or_unverified`.

הודעת v3: `PreserveExistingJobs: Migdal did not expose a reliable job payload; candidate_rows=1, rejected={'detail': 0, 'schema': 1, 'identity': 0, 'navigation': 0}; preserving the last successful snapshot`

### Philips Careers Israel — `philips`

12 משרות ישראליות ו־12 תיאורים שסומנו מלאים. בדיקת האיכות אינה מבטיחה שלמות איסוף.

הראיה בדוח: `sources[identifier=philips]`, מצב `partial`.

### Retym — Semiconductor Israel — `retym`

ב־v3 הוחזרו 28 רשומות, 9 ישראליות, ו־7 נחסמו. אין בדוח מזהים של שבע החסומות. נוסף גיבוי Comeet רק למזהים שנותרו ברשימה הרשמית ונכשלו בהורדת פרטים. אינו מחליף משרות תקינות ואינו מחזיר 404/410/סגורות; המזהים והקישורים המקוריים נשמרים.

הראיה בדוח: `sources[identifier=retym]`, מצב `partial`.

### Salesforce Careers Israel — `salesforce`

9 משרות ישראליות ו־9 תיאורים שסומנו מלאים; אין אישור לאיסוף מלא של האתר.

הראיה בדוח: `sources[identifier=salesforce]`, מצב `partial`.

### SCD — SemiConductor Devices — `scd`

ב־v3 נדחו 10 מועמדים. האתר מציג תיאורי תפקידים בתוך הרשימה; עדיין נדרש קורא שמתייחס לתפקידים עצמם ולא למחלקות/עמודים.

הראיה בדוח: `sources[identifier=scd]`, מצב `error_or_unverified`.

הודעת v3: `PreserveExistingJobs: SCD - SemiConductor Devices did not expose a reliable job payload; candidate_rows=10, rejected={'detail': 10, 'schema': 0, 'identity': 0, 'navigation': 0}; preserving the last successful snapshot`

### Siemens EDA — Israel — `siemens-eda`

ב־v3 נדחו 6 מועמדים. פורטל Siemens Software הוא יעד לבדיקה, אבל אין כאן מימוש מאומת שלו; אין לייבא אוטומטית כל תפקיד Siemens תחת EDA.

הראיה בדוח: `sources[identifier=siemens-eda]`, מצב `error_or_unverified`.

הודעת v3: `PreserveExistingJobs: Siemens EDA did not expose a reliable job payload; candidate_rows=6, rejected={'detail': 6, 'schema': 0, 'identity': 0, 'navigation': 0}; preserving the last successful snapshot`

### StarkWare Careers Israel — `starkware`

הודעת v3 איחדה ריק/פגום/מעל 200. כעת מצבים אלה מובחנים. תפקידים תחת Ecosystem Positions אינם נחשבים אוטומטית לתפקידים של StarkWare עצמה.

הראיה בדוח: `sources[identifier=starkware]`, מצב `error_or_unverified`.

הודעת v3: `PreserveExistingJobs: Public ATS feed empty, invalid, or above 200 rows`

### Sunflower Careers Israel — `sunflower`

27 משרות ישראליות ותיאורים שסומנו מלאים; ללא שינוי במסלול האיסוף.

הראיה בדוח: `sources[identifier=sunflower]`, מצב `partial`.

## גבולות התיקונים

### Elad

קורא v3 דרש H1 אחד ותוויות צרות. בדפי קריירה רשמיים נמצאו גם תבנית ישנה עם `join us` ו־H1 נפרד לתפקיד, `מספר משרה`, שדה `מיקום משרה` וגבול `הגש מועמדות`. התיקון מקבל את הווריאציות האלה וכן נקודתיים ומבנה טקסט מפוצל בתוויות. הוא אינו מסיק מיקום מכתובת החברה בפוטר, ואינו מקבל מספר משרה סותר או שני שמות תפקיד שונים.

הדוח של המשתמש לא כלל את ה־HTML שנכשל, ולכן לא ניתן לקבוע שווריאציה מסוימת היא הסיבה היחידה לכשל ההרצה. האבחון החדש שומר סיבת דחייה וקטעי מבנה מסוננים כדי לאמת זאת.

### Retym

זוהה לוח ATS ייעודי `https://www.comeet.com/jobs/retym/C6.003` על סמך דף משרה ציבורי מזוהה. קוד הגיבוי משתמש בקריאת JSON מובנה שכבר קיימת בפרויקט, עם מגבלת 4 MB ו־200 רשומות ובלי להריץ JavaScript. זמינות הנתונים המובנים בלוח זה עדיין דורשת אימות חי.

הגיבוי פועל רק כאשר חסר תיאור מאומת למזהה שעדיין הופיע ברשימת Retym ונשאר לאחר סינון מפורש של דפים סגורים/404/410. הוא לא מוסיף את כל לוח Comeet, לא דורס רשומה מוצלחת ולא משנה מזהה או קישור מקור/הגשה. כאשר הגיבוי נכשל, הרשומות הטובות נשמרות והחסומות ממשיכות להיות מדווחות. לא שונתה הפעלת המקור בקטלוג.

### שיפור האבחון

`--v4` בודק את אותם 16 מקורות ושומר אבחון מסונן בתוך אותו JSON. ב־Workday נשמרים היקף התשובה, המסננים, מספר הרשומות בכל עמוד וסיבות לדחייה. ב־Comeet תשובה ריקה, סכימה לא מזוהה וחריגה מהמגבלה מקבלות הסבר נפרד; גם `custom_fields` פגום אינו מפיל את כל הקריאה באופן לא מבוקר.

נשמרים עד 48 אירועים ועד 4 מסמכים מסוכמים לכל מקור — לכל היותר רשימה אחת ושלושה דפי פרט. קטע HTML מוגבל ל־6,000 תווים; נשמרים גם מקטעים קצרים ליד תוויות מספר משרה. דפי הפרט של הקורא הכללי נבחרים מכשלים בפרסור/זהות ולא מהצלחות בלבד. הנתונים הם מהעמודים הציבוריים: אין cookies, כותרות HTTP, ערכי מועמד בטופס, תוכן JavaScript, query credentials או עמודים מלאים. מספרי משרה ציבוריים בשדות ייעודיים מותרים.

מחוץ לבדיקת אבחון מפורשת לא נאגר מידע זה. הדוח נשמר באופן אטומי לאחר כל מקור כפי שהיה ב־v3. נוספה החרגה של `/source-health-live*.json` ב־`.gitignore`, כדי שדוחות מקומיים חדשים לא ייכנסו בטעות ל־commit או ל־ZIP המקור. קבצים שכבר מנוהלים ב־Git אינם מוסרים אוטומטית.

## מקורות רשת שנבדקו

אלה כתובות לראיות מבנה/זהות, לא הבטחה שמספר המשרות או הדפים המאונדקסים עדכני לרגע זה. חלק מניסיונות הפתיחה החוזרים החזירו Cache miss; אין כאן הקלטת HTML חיה מלאה.

- Elad, דוגמאות תבניות: `https://careers.eladsoft.com/jobs/1007388/`, `https://careers.eladsoft.com/jobs/1007788/`, `https://careers.eladsoft.com/jobs/1007278/`.
- Retym, דף משרה מזוהה ב־ATS: `https://www.comeet.com/jobs/retym/C6.003/system-integration--validation-engineer/2F.073`.
- Retym, רשימה רשמית: `https://retym.com/careers-2/`.
- Cal, תפקידים בתוך העמוד: `https://www.cal-online.co.il/about/jobs/`.
- SCD, תפקידים בתוך העמוד: `https://www.scd-infrared.com/find-a-job/`.
- Siemens Software, פורטל חלופי לבדיקה: `https://jobs.sw.siemens.com/`.
- Migdal: `https://my.migdal.co.il/about/jobs`.
- StarkWare, עמוד המפריד Ecosystem Positions: `https://starkware.co/careers/`.

## בדיקות והיקף

תוצאות הבדיקות המדויקות מופיעות בקובץ `jobpilot-source-audit-v4-20260926-verification.json` המצורף בנפרד. בדיקות המקורות משתמשות בנתונים סינתטיים וב־HTTP מדומה; אין לראות בהן אימות חי. הוחרגו אותן בדיקות דפדפן ושני שמות בדיקות PostgreSQL שהוחרגו ב־v3. לוגי הריצה מציגים גם את הדילוגים.

לא שונו דירוג המשרות, איחוד שלושת המסלולים, הגדרות הפעלת מקורות, תלויות Python, מיגרציות או מנגנון הגשת מועמדויות. לא בוצעו commit/push בפרויקט של המשתמש, שינוי בשרת או במסד הנתונים שלו. הפאטצ׳ נועד לגרסה שלאחר החלת v3 בלבד.
