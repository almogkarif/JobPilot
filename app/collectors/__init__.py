from .greenhouse import GreenhouseCollector
from .ashby import AshbyCollector
from .lever import LeverCollector
from .google import GoogleCareersCollector
from .workday import WorkdayCollector
from .official import OfficialCareersCollector
from .smartrecruiters import SmartRecruitersCollector

COLLECTORS = {
    "greenhouse": GreenhouseCollector,
    "ashby": AshbyCollector,
    "lever": LeverCollector,
    "google_careers": GoogleCareersCollector,
    "workday": WorkdayCollector,
    "official_careers": OfficialCareersCollector,
    "smartrecruiters": SmartRecruitersCollector,
}
