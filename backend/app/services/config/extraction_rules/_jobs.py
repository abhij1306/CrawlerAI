from __future__ import annotations
# ruff: noqa: F401,F403,F405
# pylint: disable=wildcard-import,unused-wildcard-import

import re

from ._common import *

SELECTOR_RUNTIME_PRIMARY_IFRAME_MAX_PAGE_TEXT = 400
ORACLE_HCM_CX_CONFIG_RE = re.compile(
    r"(?:var\s+|window\.)?CX_CONFIG\s*=\s*(\{.*?\})\s*(?:;|</script>)",
    re.DOTALL,
)
ORACLE_HCM_SITE_PATH_RE = re.compile(
    r"/CandidateExperience/[^/?#]+/sites/([^/?#]+)(?:/|$)",
    re.IGNORECASE,
)
ORACLE_HCM_LANG_PATH_RE = re.compile(
    r"/CandidateExperience/([^/?#]+)/sites/",
    re.IGNORECASE,
)
ORACLE_HCM_JOB_PATH_RE = re.compile(
    r"/CandidateExperience/[^/?#]+/sites/[^/?#]+/job/([^/?#]+)(?:/|$)",
    re.IGNORECASE,
)
ORACLE_HCM_DEFAULT_FACETS = (
    "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;"
    "ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"
)
ORACLE_HCM_EXPAND_FIELDS = (
    "requisitionList.workLocation,requisitionList.otherWorkLocations,"
    "requisitionList.secondaryLocations,flexFieldsFacet.values,"
    "requisitionList.requisitionFlexFields"
)
ORACLE_HCM_LOCATION_LIST_KEYS = (
    "workLocation",
    "otherWorkLocations",
    "secondaryLocations",
)
INDEED_DEFAULT_BASE_ORIGIN = "https://www.indeed.com"

__all__ = sorted(name for name in globals() if name.isupper())
