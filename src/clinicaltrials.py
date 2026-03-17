"""
ClinicalTrials.gov monitor.
Tracks new and updated neonatal RCTs.
Checks for newly posted results of important ongoing trials.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"

# Core neonatal search terms
NEONATAL_SEARCH = (
    "AREA[Condition](neonatal OR preterm OR premature infant OR VLBW OR ELBW "
    "OR bronchopulmonary dysplasia OR necrotizing enterocolitis OR retinopathy of prematurity "
    "OR intraventricular hemorrhage OR neonatal sepsis OR HIE OR hypoxic ischemic) "
    "AND AREA[StudyType]INTERVENTIONAL "
    "AND AREA[Phase](PHASE3 OR PHASE4)"
)


class ClinicalTrialsMonitor:
    """Monitor ClinicalTrials.gov for important neonatal trials."""

    def __init__(self, cache_path: str = "data/ct_cache.json"):
        self.cache_path = Path(cache_path)
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            with open(self.cache_path) as f:
                return json.load(f)
        return {"known_trials": {}, "last_check": None}

    def save_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def check_new_results(self) -> list[dict]:
        """
        Check for neonatal trials that recently posted results.
        This is the most valuable signal: a large RCT posting results
        means a major publication is imminent.
        """
        alerts = []

        try:
            params = {
                "query.term": NEONATAL_SEARCH,
                "filter.advanced": "AREA[ResultsFirstPostDate]RANGE[LAST 30 DAYS, MAX]",
                "fields": "NCTId,BriefTitle,Condition,EnrollmentCount,Phase,ResultsFirstPostDate,OverallStatus,LeadSponsorName",
                "pageSize": 20,
                "format": "json",
            }

            resp = requests.get(CTGOV_API, params=params, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"ClinicalTrials.gov API returned {resp.status_code}")
                return []

            data = resp.json()
            studies = data.get("studies", [])

            for study in studies:
                proto = study.get("protocolSection", {})
                ident = proto.get("identificationModule", {})
                nct_id = ident.get("nctId", "")

                # Skip if already alerted
                if nct_id in self.cache.get("known_trials", {}):
                    if self.cache["known_trials"][nct_id].get("results_alerted"):
                        continue

                design = proto.get("designModule", {})
                status_module = proto.get("statusModule", {})
                sponsor = proto.get("sponsorCollaboratorsModule", {})

                enrollment = design.get("enrollmentInfo", {}).get("count", "?")
                phase_list = design.get("phases", [])
                phase = ", ".join(phase_list) if phase_list else "?"

                conditions = proto.get("conditionsModule", {}).get("conditions", [])
                lead_sponsor = sponsor.get("leadSponsor", {}).get("name", "?")

                alert = {
                    "type": "results_posted",
                    "nct_id": nct_id,
                    "title": ident.get("briefTitle", ""),
                    "conditions": conditions,
                    "enrollment": enrollment,
                    "phase": phase,
                    "sponsor": lead_sponsor,
                    "results_date": status_module.get("resultsFirstPostDateStruct", {}).get("date", ""),
                    "url": f"https://clinicaltrials.gov/study/{nct_id}",
                }

                alerts.append(alert)

                # Mark as alerted
                self.cache.setdefault("known_trials", {})[nct_id] = {
                    "title": alert["title"],
                    "results_alerted": True,
                    "alerted_date": datetime.now(timezone.utc).isoformat(),
                }

            logger.info(f"ClinicalTrials.gov: {len(alerts)} new results posted")
            return alerts

        except Exception as e:
            logger.error(f"ClinicalTrials.gov check failed: {e}")
            return []

    def check_new_large_trials(self) -> list[dict]:
        """
        Check for newly registered large neonatal Phase 3/4 trials.
        Large enrollment (>200) likely to be practice-changing when completed.
        """
        alerts = []

        try:
            params = {
                "query.term": NEONATAL_SEARCH,
                "filter.advanced": "AREA[StudyFirstPostDate]RANGE[LAST 30 DAYS, MAX]",
                "fields": "NCTId,BriefTitle,Condition,EnrollmentCount,Phase,StudyFirstPostDate,OverallStatus,LeadSponsorName,StartDate",
                "pageSize": 20,
                "format": "json",
            }

            resp = requests.get(CTGOV_API, params=params, timeout=30)
            if resp.status_code != 200:
                return []

            data = resp.json()
            studies = data.get("studies", [])

            for study in studies:
                proto = study.get("protocolSection", {})
                ident = proto.get("identificationModule", {})
                nct_id = ident.get("nctId", "")

                if nct_id in self.cache.get("known_trials", {}):
                    continue

                design = proto.get("designModule", {})
                enrollment = design.get("enrollmentInfo", {}).get("count", 0)

                # Only alert for large trials (>200 participants)
                if isinstance(enrollment, int) and enrollment < 200:
                    continue

                conditions = proto.get("conditionsModule", {}).get("conditions", [])
                phase_list = design.get("phases", [])
                sponsor = proto.get("sponsorCollaboratorsModule", {})

                alert = {
                    "type": "new_large_trial",
                    "nct_id": nct_id,
                    "title": ident.get("briefTitle", ""),
                    "conditions": conditions,
                    "enrollment": enrollment,
                    "phase": ", ".join(phase_list) if phase_list else "?",
                    "sponsor": sponsor.get("leadSponsor", {}).get("name", "?"),
                    "url": f"https://clinicaltrials.gov/study/{nct_id}",
                }
                alerts.append(alert)

                self.cache.setdefault("known_trials", {})[nct_id] = {
                    "title": alert["title"],
                    "results_alerted": False,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                }

            logger.info(f"ClinicalTrials.gov: {len(alerts)} new large trials registered")
            return alerts

        except Exception as e:
            logger.error(f"ClinicalTrials.gov new trials check failed: {e}")
            return []

    def format_alerts_for_digest(self, alerts: list[dict]) -> str:
        """Format ClinicalTrials.gov alerts as text for inclusion in digest."""
        if not alerts:
            return ""

        lines = []

        results_alerts = [a for a in alerts if a["type"] == "results_posted"]
        new_trials = [a for a in alerts if a["type"] == "new_large_trial"]

        if results_alerts:
            lines.append("🔬 ClinicalTrials.gov: Results newly posted")
            for a in results_alerts:
                lines.append(
                    f"  • {a['title']} (n={a['enrollment']}, {a['phase']})\n"
                    f"    {a['url']}\n"
                    f"    Sponsor: {a['sponsor']}"
                )

        if new_trials:
            lines.append("\n📋 ClinicalTrials.gov: New large trials registered")
            for a in new_trials:
                lines.append(
                    f"  • {a['title']} (n={a['enrollment']}, {a['phase']})\n"
                    f"    {a['url']}"
                )

        return "\n".join(lines)
