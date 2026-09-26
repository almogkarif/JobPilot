"""Oracle's official CX site and explicit Israel country facet.

The public careers.oracle.com page declares the API host/site. Its locationsFacet
names 300000000106941 'Israel'. Keyword=Israel misses most of those vacancies.
"""
from .verint import collect_oracle_cx

API = 'https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/'
SITE = 'CX_45001'
ISRAEL_FACET = '300000000106941'
PUBLIC_JOB_BASE = 'https://careers.oracle.com/en/sites/jobsearch/job/'


async def collect_oracle_employer(company='Oracle'):
    return await collect_oracle_cx(API, SITE, PUBLIC_JOB_BASE, company, country_facet=ISRAEL_FACET)
