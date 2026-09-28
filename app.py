import os
import traceback

from flask import Flask, request, jsonify, render_template

from pipeline import db, model, search
from pipeline.stages import STAGE_ORDER, validate_advance, validate_reject, InvalidTransition

app = Flask(__name__)
db.init_db()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


@app.errorhandler(Exception)
def handle_any_error(e):
    # Without this, an unhandled exception returns Flask's default HTML
    # error page, the frontend's fetch() can't parse it as JSON, and the
    # user just sees a generic "Something went wrong." This logs the full
    # traceback to the terminal running `python3 app.py` AND returns the
    # real reason as JSON so the browser can show it too.
    app.logger.error("Unhandled error on %s %s:\n%s", request.method, request.path, traceback.format_exc())
    return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@app.route("/")
def index():
    return render_template("index.html", stages=STAGE_ORDER)


@app.route("/api/candidates", methods=["GET"])
def list_candidates():
    views = model.load_all_candidates()
    groups = model.group_by_stage(views)
    out = {stage: [v.to_dict() for v in sorted(cands, key=lambda c: c.stage_since)]
           for stage, cands in groups.items()}
    return jsonify(out)


@app.route("/api/candidates", methods=["POST"])
def add_candidate():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "A candidate name is required."}), 400
    candidate_id = db.create_candidate(name)
    view = model.load_candidate(candidate_id)
    return jsonify(view.to_dict(include_history=True)), 201


@app.route("/api/candidates/<int:candidate_id>", methods=["GET"])
def get_candidate(candidate_id):
    view = model.load_candidate(candidate_id)
    if not view:
        return jsonify({"error": "No such candidate."}), 404
    return jsonify(view.to_dict(include_history=True))


@app.route("/api/candidates/<int:candidate_id>/advance", methods=["POST"])
def advance_candidate(candidate_id):
    view = model.load_candidate(candidate_id)
    if not view:
        return jsonify({"error": "No such candidate."}), 404
    try:
        dest = validate_advance(view.current_stage)
    except InvalidTransition as e:
        return jsonify({"error": str(e)}), 409
    db.record_event(candidate_id, "advanced", view.current_stage, dest)
    updated = model.load_candidate(candidate_id)
    return jsonify(updated.to_dict(include_history=True))


@app.route("/api/candidates/<int:candidate_id>/reject", methods=["POST"])
def reject_candidate(candidate_id):
    view = model.load_candidate(candidate_id)
    if not view:
        return jsonify({"error": "No such candidate."}), 404
    try:
        dest = validate_reject(view.current_stage)
    except InvalidTransition as e:
        return jsonify({"error": str(e)}), 409
    data = request.get_json(silent=True) or {}
    note = (data.get("note") or "").strip() or None
    db.record_event(candidate_id, "rejected", view.current_stage, dest, note=note)
    updated = model.load_candidate(candidate_id)
    return jsonify(updated.to_dict(include_history=True))


@app.route("/api/ai-status", methods=["GET"])
def ai_status():
    return jsonify({"available": bool(ANTHROPIC_API_KEY)})


@app.route("/api/search", methods=["GET"])
def search_candidates():
    q = request.args.get("q", "")
    use_ai = request.args.get("ai") == "1" and bool(ANTHROPIC_API_KEY)
    all_candidates = model.load_all_candidates()
    result = search.smart_search(all_candidates, q, use_ai=use_ai, api_key=ANTHROPIC_API_KEY)
    return jsonify({
        "understood": result.understood,
        "explanation": result.explanation,
        "notes": result.notes,
        "errors": result.errors,
        "used_ai": result.used_ai,
        "results": [
            {**c.to_dict(), "match_score": round(score, 3) if score is not None else None}
            for c, score in result.candidates
        ],
    })


if __name__ == "__main__":
    # Set debug=True while developing if you want auto-reload + tracebacks.
    app.run(debug=False, host="0.0.0.0", port=5000)
