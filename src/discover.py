"""ATS token discovery: turn a raw company list into verified companies.yaml entries.

Reads data/companies_master.csv (company, sector, priority, source), generates
likely board-token slugs for each company, probes the three ATS public APIs
that need no auth (Greenhouse, Lever, Ashby), and writes every confirmed hit to
data/discovered_companies.yaml in the exact format config/companies.yaml uses.

Run it LOCALLY (GitHub Actions runners work too, but a first full run over
~1,200 companies makes a few thousand small HTTP requests — ~30-60 min at the
default polite delay). Progress is checkpointed to data/discovery_state.json
after every company, so Ctrl-C and re-run resumes where it left off.

    python -m src.discover                     # probe everything not yet probed
    python -m src.discover --priority A        # only Priority A companies
    python -m src.discover --limit 50          # first 50 unprobed (quick test)
    python -m src.discover --company "Skydio"  # one company, verbose
    python -m src.discover --retry-misses      # re-probe past misses too
    python -m src.discover --write-config      # merge hits INTO config/companies.yaml

Workday is not probed: its tenant + wd_num + site triple can't be reliably
guessed, and wrong guesses often return misleading 2xx responses. For big
companies that come up empty here, check their careers URL — if it looks like
https://<tenant>.wd<N>.myworkdayjobs.com/<site>, add it to the workday: section
of config/companies.yaml by hand. Companies with fully custom career sites
(no public ATS at all) reach you via the community lists in github_lists.yaml.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
import yaml

log = logging.getLogger("discover")

ROOT = Path(__file__).resolve().parent.parent
MASTER_CSV = ROOT / "data" / "companies_master.csv"
STATE_FILE = ROOT / "data" / "discovery_state.json"
OUT_YAML = ROOT / "data" / "discovered_companies.yaml"
CONFIG_YAML = ROOT / "config" / "companies.yaml"

GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
LEVER = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

DELAY = 0.25          # polite delay between requests (seconds)
TIMEOUT = 12
UA = "hw-intern-emailer-discovery/1.0 (personal internship alerter)"

# Corporate suffixes dropped when building slug candidates.
_SUFFIXES = (
    "incorporated", "corporation", "technologies", "technology", "holdings",
    "holding", "industries", "solutions", "systems", "company", "group",
    "corp", "inc", "llc", "ltd", "co", "usa", "america", "gmbh", "ag",
)


def _ascii(name: str) -> str:
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()


def slug_candidates(name: str) -> list[str]:
    """Likely board tokens for a company name, most-likely first."""
    base = _ascii(name)
    base = re.sub(r"\(.*?\)", " ", base)           # drop parentheticals
    base = re.sub(r"[&+]", " and ", base)
    words = [w for w in re.findall(r"[a-z0-9]+", base.lower()) if w]
    if not words:
        return []

    core = list(words)
    while len(core) > 1 and core[-1] in _SUFFIXES:
        core = core[:-1]

    cands: list[str] = []

    def add(s: str):
        if s and len(s) >= 2 and s not in cands:
            cands.append(s)

    add("".join(core))            # bostondynamics
    add("-".join(core))           # boston-dynamics
    add("".join(words))           # full name incl. suffix
    add("-".join(words))
    if len(core) > 1 and len(core[0]) >= 5:
        add(core[0])              # distinctive first word alone (aerotech-style)
    # common pattern: name + 'robotics'/'inc' variants already covered by words
    return cands[:6]


def probe(session: requests.Session, ats: str, url: str) -> tuple[bool, int]:
    """Return (is_valid_board, job_count)."""
    try:
        r = session.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    except requests.RequestException:
        return False, 0
    if r.status_code != 200:
        return False, 0
    try:
        data = r.json()
    except ValueError:
        return False, 0
    if ats == "greenhouse":
        jobs = data.get("jobs") if isinstance(data, dict) else None
        return isinstance(jobs, list), len(jobs or [])
    if ats == "lever":
        return isinstance(data, list), len(data if isinstance(data, list) else [])
    if ats == "ashby":
        jobs = data.get("jobs") if isinstance(data, dict) else None
        return isinstance(jobs, list), len(jobs or [])
    return False, 0


def discover_company(session: requests.Session, name: str) -> dict:
    """Try every slug candidate on every ATS; first confirmed hit wins."""
    for slug in slug_candidates(name):
        for ats, tmpl in (("greenhouse", GREENHOUSE), ("lever", LEVER), ("ashby", ASHBY)):
            ok, n = probe(session, ats, tmpl.format(slug=slug))
            time.sleep(DELAY)
            if ok:
                log.info("HIT  %-38s -> %s:%s (%d postings)", name, ats, slug, n)
                return {"status": "hit", "ats": ats, "token": slug, "jobs_seen": n}
    log.info("miss %s", name)
    return {"status": "miss"}


def load_master(priority: str | None) -> list[dict]:
    if not MASTER_CSV.exists():
        sys.exit(f"missing {MASTER_CSV} — the master company list")
    rows = list(csv.DictReader(open(MASTER_CSV, encoding="utf-8")))
    if priority:
        rows = [r for r in rows if (r.get("priority") or "").upper() == priority.upper()]
    return rows


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True))


def write_outputs(state: dict, master: list[dict], into_config: bool) -> None:
    """Write hits to data/discovered_companies.yaml (and optionally merge into config)."""
    prio = {r["company"]: r.get("priority", "") for r in master}
    out: dict[str, list] = {"greenhouse": [], "lever": [], "ashby": []}
    for name, res in sorted(state.items()):
        if res.get("status") == "hit":
            out[res["ats"]].append({"company": name, "token": res["token"]})

    header = (
        "# Auto-generated by `python -m src.discover` — verified ATS boards only.\n"
        "# Review, then merge into config/companies.yaml (or rerun with --write-config).\n"
    )
    body = yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=100)
    OUT_YAML.write_text(header + body)
    n = sum(len(v) for v in out.values())
    log.info("wrote %d verified entries -> %s", n, OUT_YAML)

    if into_config:
        cfg = yaml.safe_load(CONFIG_YAML.read_text()) or {}
        added = 0
        for ats in ("greenhouse", "lever", "ashby"):
            existing = {e.get("token") for e in (cfg.get(ats) or [])}
            for e in out[ats]:
                if e["token"] not in existing:
                    cfg.setdefault(ats, []).append(e)
                    added += 1
        CONFIG_YAML.write_text(
            "# NOTE: comments were stripped by --write-config; see git history for the\n"
            "# annotated version. Workday entries must still be added by hand.\n"
            + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=100)
        )
        log.info("merged %d new entries into %s", added, CONFIG_YAML)
    _ = prio  # (kept for future: priority-tagged output)


def main() -> int:
    ap = argparse.ArgumentParser(description="Discover ATS board tokens for companies_master.csv")
    ap.add_argument("--priority", help="only companies with this priority (A/B/C)")
    ap.add_argument("--limit", type=int, default=0, help="probe at most N unprobed companies")
    ap.add_argument("--company", help="probe a single company name (ignores state)")
    ap.add_argument("--retry-misses", action="store_true", help="re-probe companies that previously missed")
    ap.add_argument("--write-config", action="store_true", help="merge verified hits into config/companies.yaml")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    session = requests.Session()

    if args.company:
        res = discover_company(session, args.company)
        print(json.dumps(res, indent=2))
        return 0

    master = load_master(args.priority)
    state = load_state()

    todo = []
    for r in master:
        name = r["company"]
        prev = state.get(name)
        if prev is None or (args.retry_misses and prev.get("status") == "miss"):
            todo.append(name)
    if args.limit:
        todo = todo[: args.limit]

    log.info("%d companies to probe (%d already in state)", len(todo), len(state))
    try:
        for i, name in enumerate(todo, 1):
            state[name] = discover_company(session, name)
            save_state(state)
            if i % 25 == 0:
                hits = sum(1 for v in state.values() if v.get("status") == "hit")
                log.info("progress: %d/%d probed this run · %d total hits", i, len(todo), hits)
    except KeyboardInterrupt:
        log.warning("interrupted — progress saved, re-run to resume")

    write_outputs(state, load_master(None), args.write_config)
    hits = sum(1 for v in state.values() if v.get("status") == "hit")
    log.info("done: %d hits / %d probed", hits, len(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
