import requests


def fetch_remotive_jobs(keywords: list[str]) -> list[dict]:
    jobs = []
    for kw in keywords[:2]:
        try:
            resp = requests.get(
                "https://remotive.com/api/remote-jobs",
                params={"search": kw, "limit": 8},
                headers={"User-Agent": "JobTrackerAI/1.0"},
                timeout=10,
            )
            if resp.ok:
                for j in resp.json().get("jobs", []):
                    jobs.append({
                        "title": j.get("title"),
                        "company": j.get("company_name"),
                        "location": j.get("candidate_required_location", "Remote"),
                        "salary": j.get("salary", ""),
                        "url": j.get("url"),
                        "tags": j.get("tags", [])[:6],
                        "posted": (j.get("publication_date") or "")[:10],
                        "logo": j.get("company_logo", ""),
                    })
        except Exception:
            pass

    seen, unique = set(), []
    for j in jobs:
        key = f"{j['title']}|{j['company']}"
        if key not in seen:
            seen.add(key)
            unique.append(j)
    return unique[:18]
