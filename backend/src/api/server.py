"""Flask REST API server for the dashboard."""

import json
import os
import sys
import csv
import io
import logging
import threading
from pathlib import Path
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, Response, session
from flask_cors import CORS

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.scrapers.usaspending import USASpendingScraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=str(PROJECT_ROOT / "dashboard"))
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")
CORS(app)

DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin")


# --- Helpers ---

def load_opportunities():
    path = DATA_DIR / "opportunities.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def save_opportunities(opps):
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_DIR / "opportunities.json", "w") as f:
        json.dump(opps, f, indent=2, default=str)


def load_archive():
    path = DATA_DIR / "archive.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def save_archive(archive):
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_DIR / "archive.json", "w") as f:
        json.dump(archive, f, indent=2, default=str)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# --- Auth ---

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    if data and data.get("password") == DASHBOARD_PASSWORD:
        session["logged_in"] = True
        return jsonify({"success": True})
    return jsonify({"error": "Invalid password"}), 401


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


# --- Opportunities ---

@app.route("/api/opportunities")
@login_required
def list_opportunities():
    opps = load_opportunities()
    # Filters
    source = request.args.get("source")
    min_score = request.args.get("min_score", type=int)
    status = request.args.get("status")
    search = request.args.get("search", "").lower()
    sort_by = request.args.get("sort", "score")
    sort_dir = request.args.get("dir", "desc")

    if source:
        opps = [o for o in opps if o.get("source") == source]
    if min_score is not None:
        opps = [o for o in opps if o.get("score", 0) >= min_score]
    if status:
        opps = [o for o in opps if o.get("status") == status]
    if search:
        opps = [o for o in opps if search in o.get("title", "").lower() or search in o.get("description", "").lower() or search in o.get("agency", "").lower()]

    reverse = sort_dir == "desc"
    if sort_by == "score":
        opps.sort(key=lambda x: x.get("score", 0), reverse=reverse)
    elif sort_by == "date":
        opps.sort(key=lambda x: x.get("posted_date", ""), reverse=reverse)
    elif sort_by == "deadline":
        opps.sort(key=lambda x: x.get("response_deadline", ""), reverse=reverse)
    elif sort_by == "title":
        opps.sort(key=lambda x: x.get("title", "").lower(), reverse=reverse)

    return jsonify({"opportunities": opps, "total": len(opps)})


@app.route("/api/opportunities/<opp_id>", methods=["PUT"])
@login_required
def update_opportunity(opp_id):
    opps = load_opportunities()
    data = request.get_json()
    for opp in opps:
        if opp["id"] == opp_id:
            if "status" in data:
                opp["status"] = data["status"]
            if "notes" in data:
                opp["notes"] = data["notes"]
            save_opportunities(opps)
            return jsonify({"success": True, "opportunity": opp})
    return jsonify({"error": "Not found"}), 404


@app.route("/api/opportunities/<opp_id>/archive", methods=["POST"])
@login_required
def archive_opportunity(opp_id):
    opps = load_opportunities()
    archive = load_archive()
    for i, opp in enumerate(opps):
        if opp["id"] == opp_id:
            opp["archived_date"] = datetime.utcnow().isoformat()
            archive.append(opp)
            opps.pop(i)
            save_opportunities(opps)
            save_archive(archive)
            return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404


@app.route("/api/archive")
@login_required
def list_archive():
    return jsonify({"archive": load_archive()})


# --- CSV Export ---

@app.route("/api/export/csv")
@login_required
def export_csv():
    opps = load_opportunities()
    output = io.StringIO()
    fields = ["id", "source", "title", "agency", "score", "status", "naics_code", "set_aside", "posted_date", "response_deadline", "url", "ai_recommendation"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for opp in opps:
        writer.writerow(opp)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=opportunities.csv"},
    )


# --- Teaming Leads ---

@app.route("/api/teaming/<naics_code>")
@login_required
def teaming_leads(naics_code):
    agency = request.args.get("agency")
    scraper = USASpendingScraper()
    leads = scraper.find_teaming_leads(naics_code, agency=agency)
    return jsonify({"leads": leads, "naics_code": naics_code})


# --- Stats ---

@app.route("/api/stats")
@login_required
def stats():
    opps = load_opportunities()
    total = len(opps)
    by_source = {}
    by_status = {}
    scores = []
    for o in opps:
        src = o.get("source", "Unknown")
        by_source[src] = by_source.get(src, 0) + 1
        st = o.get("status", "new")
        by_status[st] = by_status.get(st, 0) + 1
        scores.append(o.get("score", 0))

    return jsonify({
        "total": total,
        "by_source": by_source,
        "by_status": by_status,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "high_score_count": sum(1 for s in scores if s >= 70),
    })


# --- Config/Scoring Rules ---

@app.route("/api/config/scoring")
@login_required
def get_scoring_config():
    """Get current scoring rules and keywords."""
    try:
        with open(CONFIG_DIR / "scoring_rules.json") as f:
            scoring = json.load(f)
        with open(CONFIG_DIR / "keywords.json") as f:
            keywords = json.load(f)
        with open(CONFIG_DIR / "settings.json") as f:
            settings = json.load(f)
        return jsonify({
            "scoring_rules": scoring,
            "keywords": keywords,
            "naics_codes": settings.get("naics_codes", []),
            "set_asides": settings.get("set_asides", []),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/config/scoring", methods=["PUT"])
@login_required
def update_scoring_config():
    """Update scoring rules and keywords."""
    data = request.get_json()
    try:
        if "scoring_rules" in data:
            with open(CONFIG_DIR / "scoring_rules.json", "w") as f:
                json.dump(data["scoring_rules"], f, indent=2)

        if "keywords" in data:
            with open(CONFIG_DIR / "keywords.json", "w") as f:
                json.dump(data["keywords"], f, indent=2)

        if "naics_codes" in data or "set_asides" in data:
            with open(CONFIG_DIR / "settings.json") as f:
                settings = json.load(f)
            if "naics_codes" in data:
                settings["naics_codes"] = data["naics_codes"]
            if "set_asides" in data:
                settings["set_asides"] = data["set_asides"]
            with open(CONFIG_DIR / "settings.json", "w") as f:
                json.dump(settings, f, indent=2)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rescore", methods=["POST"])
@login_required
def rescore_opportunities():
    """Re-score all opportunities with current rules."""
    from src.scoring.rule_engine import score_all
    opps = load_opportunities()
    score_all(opps)
    opps.sort(key=lambda x: x.get("score", 0), reverse=True)
    save_opportunities(opps)
    return jsonify({"success": True, "count": len(opps)})


# --- Manual Scan ---

@app.route("/api/scan", methods=["POST"])
@login_required
def trigger_scan():
    def do_scan():
        from src.main import run_scan
        run_scan()

    t = threading.Thread(target=do_scan)
    t.start()
    return jsonify({"success": True, "message": "Scan started in background"})


# --- Dashboard static files ---

@app.route("/")
def serve_login():
    return send_from_directory(app.static_folder, "login.html")


@app.route("/dashboard")
def serve_dashboard():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)


if __name__ == "__main__":
    port = 8080
    try:
        with open(CONFIG_DIR / "settings.json") as f:
            port = json.load(f).get("dashboard_port", 8080)
    except Exception:
        pass
    print(f"Starting dashboard at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
