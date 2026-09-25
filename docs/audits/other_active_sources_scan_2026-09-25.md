# Remaining active-source HTTP audit — 25 September 2026

Coverage: **147 enabled source definitions**, plus one explicitly unverified retained-source probe. These complement the81 public ATS feeds and31 still-disabled expansion sources:259 definition-based sources in total. A historical comparison export records an additional disabled `official_careers:optimove` entry alongside its supported Greenhouse source. This is evidence for a retained legacy row, but its current production state has not been queried.

Browser fallback was deliberately disabled. A failure here does not establish failure of a rendered production collector. No database was queried. Three concurrent sources;90seconds/source.

Initial results:77 returned payloads;70 failed among verified definitions. Two failures (IDE/Mekorot URL identity) were subsequently fixed and live-verified. Several nonempty payloads below are invalid navigation rather than vacancies; they must not be called healthy just because HTTP succeeded.

This table preserves the initial HTTP-only results. Subsequent checks are linked in the [audit overview](source_scan_overview_2026-09-25.md): all 27 browser-dependent collectors were rerun with isolated headless browsers, all 41 remaining static failures were inspected, and six suspicious nonempty feeds received dedicated follow-up. See also [empty-feed follow-up](empty_sources_followup_2026-09-25.md) and [raw evidence](other_active_sources_scan_2026-09-25.json).

| Source | Collected | Israel detected | Interpretation |
| --- | ---: | ---: | --- |
| Google — Hardware Israel (`israel`) | 20 | 20 | Partial snapshot |
| Apple — Hardware Israel (`apple`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Amazon — Annapurna Labs Israel (`amazon`) | unknown | unknown | Full runtime verification needed; browser omitted |
| NVIDIA — Hardware Israel (`nvidia`) | 40 | 40 | Complete snapshot |
| Intel — Hardware & Silicon Israel (`intel`) | 21 | 21 | Complete snapshot |
| Microsoft — Silicon Israel (`microsoft`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Check Point — Operations (`CheckPointSoftwareTechnologies2`) | 101 | 101 | Complete snapshot |
| Palo Alto Networks Israel (`paloalto`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Wix — Operations & Analytics (`wix`) | unknown | unknown | Full runtime verification needed; browser omitted |
| monday.com — Operations & Analytics (`monday`) | 10 | 5 | Partial snapshot |
| Cisco — Silicon & Hardware Israel (`cisco`) | unknown | unknown | Full runtime verification needed; browser omitted |
| IBM Careers Israel (`ibm`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Salesforce Israel — Business Operations (`salesforce`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Meta Careers Israel (`meta`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Qualcomm — Hardware Israel (`qualcomm`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Samsung Research Israel — Hardware (`samsung`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Applied Materials — Electrical & Hardware (`applied-materials`) | 40 | 40 | Complete snapshot |
| Philips Israel — Operations (`philips`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Elbit Systems — Electrical Engineering (`elbit`) | 579 | 545 | Partial snapshot |
| Rafael — Electrical Engineering (`rafael`) | unknown | unknown | Full runtime verification needed; browser omitted |
| IAI — Electrical Engineering (`iai`) | 518 | 513 | Partial snapshot |
| CyberArk — Business Operations (`Cyberark1`) | 0 | 0 | See dedicated empty-feed follow-up |
| ServiceNow — Business & Engineering Israel (`ServiceNow`) | 11 | 11 | Complete snapshot |
| Aqua Security Careers (`aqua`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Sunflower — Business & Operations Israel (`sunflower`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Moon Active — Product & Operations Israel (`moonactive`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Claroty — Revenue & Business Operations Israel (`claroty`) | 24 | 10 | Partial snapshot |
| VAST Data — Hardware Israel (`vastdata`) | 160 | 20 | Partial snapshot |
| Gloat — Product & Business Operations Israel (`gloat`) | 5 | 5 | Partial snapshot |
| Silverfort — Business Operations Israel (`silverfort`) | 35 | 11 | Partial snapshot |
| 4M Analytics Careers Israel (`4manalytics`) | 8 | 4 | Partial snapshot |
| Exodigo — Hardware & Systems Israel (`exodigo`) | 59 | 13 | Partial snapshot |
| Paragon Careers Israel (`paragon`) | 24 | 23 | Partial snapshot |
| Legit Security Careers Israel (`legitsecurity`) | 9 | 5 | Partial snapshot |
| Voyantis Careers Israel (`voyantis`) | 9 | 9 | Partial snapshot |
| Arbe Robotics — Israel (`arbe`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Playtika — IEM Israel (`playtika`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Fiverr — IEM Israel (`fiverr`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| משרד הביטחון — EE Israel (`ministry-of-defense-il`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Tower Semiconductor — EE Israel (`tower-semiconductor`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| ICL — EE Israel (`icl`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Teva — EE Israel (`teva`) | 10 | 10 | Partial snapshot |
| Strauss Group — EE Israel (`strauss`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Osem-Nestle — EE Israel (`osem-nestle`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| החברה המרכזית למשקאות — EE Israel (`cocacola-israel`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Fox Group — IEM Israel (`fox-group`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Shufersal — IEM Israel (`shufersal`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Super-Pharm — IEM Israel (`super-pharm`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Deloitte Israel — IEM Israel (`deloitte-israel`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| EY Israel — IEM Israel (`ey-israel`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| PwC Israel — IEM Israel (`pwc-israel`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| KPMG Israel — IEM Israel (`kpmg-israel`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Ness — EE Israel (`ness-israel`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Matrix — EE Israel (`matrix-israel`) | 100 | 25 | Partial snapshot |
| Malam Team — EE Israel (`malam-team`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| ONE Technologies — EE Israel (`one-technologies`) | 10 | 10 | Partial snapshot |
| Elad Systems — IEM Israel (`elad-systems`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Israel Post — IEM Israel (`israel-post`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| UPS — IEM Israel (`ups-israel`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| DHL — IEM Israel (`dhl-israel`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Israel Railways — EE Israel (`israel-railways`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Ashdod Port — EE Israel (`ashdod-port`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Haifa Port — EE Israel (`haifa-port`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Bank Leumi — IEM Israel (`bank-leumi`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Bank Hapoalim — IEM Israel (`bank-hapoalim`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Israel Discount Bank — IEM Israel (`discount-bank`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Cal — IEM Israel (`cal`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Max — IEM Israel (`max`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Isracard — IEM Israel (`isracard`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Harel — IEM Israel (`harel`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| The Phoenix — IEM Israel (`phoenix`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Migdal — IEM Israel (`migdal`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Clalit — IEM Israel (`clalit`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Maccabi Healthcare — IEM Israel (`maccabi-health`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Sheba Medical Center — EE Israel (`sheba`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Ichilov Medical Center — EE Israel (`ichilov`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Rapyd Careers Israel (`rapyd`) | 32 | 16 | Partial snapshot |
| Tipalti Careers Israel (`tipalti`) | 21 | 6 | Partial snapshot |
| Guesty Careers Israel (`guesty`) | 19 | 3 | Partial snapshot |
| Papaya Global Careers Israel (`papaya-global`) | 53 | 6 | Partial snapshot |
| HiBob Careers Israel (`hibob`) | 79 | 19 | Partial snapshot |
| Fundbox Careers Israel (`fundbox`) | 3 | 0 | Returned jobs have foreign locations in samples; feed-specific result |
| Pentera Careers Israel (`pentera`) | 23 | 12 | Partial snapshot |
| Island Careers Israel (`island`) | 37 | 9 | Partial snapshot |
| Cyera Careers Israel (`cyera`) | 222 | 31 | Partial snapshot |
| Upwind Careers Israel (`upwind`) | 77 | 18 | Partial snapshot |
| Grip Security Careers Israel (`grip-security`) | 2 | 1 | Partial snapshot |
| Reco Careers Israel (`reco`) | 3 | 2 | Partial snapshot |
| Coralogix Careers Israel (`coralogix`) | 46 | 10 | Partial snapshot |
| Atera Careers Israel (`atera`) | 8 | 7 | Partial snapshot |
| Kaltura Careers Israel (`kaltura`) | 25 | 17 | Partial snapshot |
| Natural Intelligence Careers Israel (`natural-intelligence`) | 4 | 4 | Partial snapshot |
| eToro Careers Israel (`etoro`) | 21 | 4 | Partial snapshot |
| Lemonade Careers Israel (`lemonade`) | 39 | 23 | Partial snapshot |
| Earnix Careers Israel (`earnix`) | 13 | 3 | Partial snapshot |
| Nayax Careers Israel (`nayax`) | 24 | 5 | Partial snapshot |
| Global-e Careers Israel (`global-e`) | 32 | 11 | Partial snapshot |
| Priority Software Careers Israel (`priority-software`) | 9 | 9 | Partial snapshot |
| Amdocs Careers Israel (`amdocs`) | 0 | 0 | See dedicated empty-feed follow-up |
| Unity Careers Israel (`unity`) | 9 | 9 | Partial snapshot |
| Personetics Careers Israel (`personetics`) | 12 | 9 | Partial snapshot |
| G-STAT — Data Analyst & BI (`g-stat`) | 37 | 37 | Partial snapshot |
| KLA Israel — Electrical & Systems (`kla-israel`) | 40 | 40 | Complete snapshot |
| Medtronic Israel — Operations (`medtronic`) | 24 | 24 | Complete snapshot |
| Tefen — IEM Israel (`tefen`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Niram Gitan — IEM Israel (`niram-gitan`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Fridenson — IEM Israel (`friedenson`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Netafim Careers Israel (`netafim`) | 20 | 2 | Partial snapshot |
| ZIM Careers Israel (`zim`) | 73 | 9 | Partial snapshot |
| Kornit Digital Careers Israel (`kornit-digital`) | 14 | 12 | Partial snapshot |
| IDE Technologies Careers Israel (`ide-technologies`) | unknown | unknown | Query-ID quality bug fixed; live feed reverified |
| Procter & Gamble Israel Careers Israel (`pg-israel`) | 2 | 2 | Partial snapshot |
| Valens Semiconductor — Hardware Israel (`valens`) | 4 | 4 | Partial snapshot |
| NextSilicon — Hardware Israel (`nextsilicon`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Retym — Semiconductor Israel (`retym`) | 4 | 0 | Role-like links, missing location extraction; not proof of foreign-only jobs |
| Hailo — AI Silicon Israel (`hailo`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Pliops — Storage Silicon Israel (`pliops`) | unknown | unknown | HTTP collection/quality failed; inventory unknown |
| Chain Reaction — Hardware Israel (`chain-reaction`) | unknown | unknown | Full runtime verification needed; browser omitted |
| SCD — SemiConductor Devices (`scd`) | 8 | 0 | Invalid navigation/category/asset payload; parser issue |
| Cadence Design Systems — Israel (`cadence`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Texas Instruments — Israel (`texas-instruments`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Flex — Hardware Israel (`flex-israel`) | 2 | 0 | Invalid navigation/category/asset payload; parser issue |
| Siemens EDA — Israel (`siemens-eda`) | 6 | 0 | Invalid navigation/category/asset payload; parser issue |
| Marvell — Israel (`marvell`) | 7 | 7 | Partial snapshot |
| Broadcom — Israel (`broadcom-israel`) | 2 | 2 | Partial snapshot |
| Synopsys — Israel (`synopsys-israel`) | 10 | 6 | Partial snapshot |
| Arm — Israel (`arm-israel`) | 9 | 6 | Partial snapshot |
| DustPhotonics — Israel (`dustphotonics`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Wiliot — Hardware Israel (`wiliot`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Vayyar Imaging — Israel (`vayyar`) | unknown | unknown | Full runtime verification needed; browser omitted |
| TriEye — Israel (`trieye`) | 1 | 1 | Partial snapshot |
| Speedata — Israel (`speedata`) | 6 | 0 | Role-like links, missing location extraction; not proof of foreign-only jobs |
| proteanTecs — Israel (`proteantecs`) | 16 | 9 | Partial snapshot |
| Innoviz — Israel (`innoviz`) | unknown | unknown | Full runtime verification needed; browser omitted |
| Camtek — Israel (`camtek`) | 29 | 21 | Partial snapshot |
| Nova — Israel (`nova`) | 2 | 0 | Invalid navigation/category/asset payload; parser issue |
| NeuroBlade — Israel (`neuroblade`) | unknown | unknown | Full runtime verification needed; browser omitted |
| HP Careers Israel (`hp`) | 9 | 9 | Partial snapshot |
| Western Digital Careers Israel (`WesternDigital`) | 0 | 0 | See dedicated empty-feed follow-up |
| SolarEdge Careers Israel (`solaredge`) | 111 | 48 | Partial snapshot |
| Stratasys Careers Israel (`stratasys`) | 13 | 13 | Partial snapshot |
| Motorola Solutions Careers Israel (`motorola-solutions`) | 3 | 3 | Partial snapshot |
| GE HealthCare Careers Israel (`ge-healthcare`) | 30 | 30 | Partial snapshot |
| Boston Scientific Careers Israel (`boston-scientific`) | 0 | 0 | See dedicated empty-feed follow-up |
| Johnson & Johnson Israel Careers Israel (`jnj-israel`) | 22 | 22 | Partial snapshot |
| Electra Group Careers Israel (`electra-group`) | 39 | 39 | Partial snapshot |
| Mekorot Careers Israel (`mekorot`) | unknown | unknown | Query-ID quality bug fixed; live feed reverified |
| Optimove Careers Israel (`optimove`) | unknown | unknown | UNVERIFIED extra source probe; not actual inventory evidence |
