"""
Populate the pipeline with sample candidates spread across stages, with a
couple of events backdated so the "stuck in X for N days" and "moved to X
since <date>" searches have something interesting to find.

Run with: python3 seed.py
(Safe to re-run -- it wipes and rebuilds the database.)
"""
import datetime as dt
from pipeline import db

db.reset_db()


def backdate(candidate_id, to_stage, days_ago):
    conn = db.get_conn()
    ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()
    conn.execute(
        "UPDATE events SET at = ? WHERE candidate_id = ? AND to_stage = ? "
        "AND id = (SELECT MAX(id) FROM events WHERE candidate_id = ? AND to_stage = ?)",
        (ts, candidate_id, to_stage, candidate_id, to_stage),
    )
    conn.commit()
    conn.close()


# Priya Sharma -- currently in Interview, moved there a few days ago.
priya = db.create_candidate("Priya Sharma")
db.record_event(priya, "advanced", "Applied", "Screening")
db.record_event(priya, "advanced", "Screening", "Interview")
backdate(priya, "Interview", 2)

# Rahul Verma -- stuck in Screening for over a week.
rahul = db.create_candidate("Rahul Verma")
db.record_event(rahul, "advanced", "Applied", "Screening")
backdate(rahul, "Screening", 9)

# Anjali Gupta -- reached Offer, then rejected.
anjali = db.create_candidate("Anjali Gupta")
db.record_event(anjali, "advanced", "Applied", "Screening")
db.record_event(anjali, "advanced", "Screening", "Interview")
db.record_event(anjali, "advanced", "Interview", "Offer")
db.record_event(anjali, "rejected", "Offer", "Rejected", note="Went with another offer.")

# Vikram Singh -- hired.
vikram = db.create_candidate("Vikram Singh")
db.record_event(vikram, "advanced", "Applied", "Screening")
db.record_event(vikram, "advanced", "Screening", "Interview")
db.record_event(vikram, "advanced", "Interview", "Offer")
db.record_event(vikram, "advanced", "Offer", "Hired")

# Meera Iyer -- fresh applicant, just applied today.
db.create_candidate("Meera Iyer")

# Karan Malhotra -- rejected early, straight out of Screening.
karan = db.create_candidate("Karan Malhotra")
db.record_event(karan, "advanced", "Applied", "Screening")
db.record_event(karan, "rejected", "Screening", "Rejected", note="Not enough experience.")

# Divya Nair -- in Offer stage right now.
divya = db.create_candidate("Divya Nair")
db.record_event(divya, "advanced", "Applied", "Screening")
db.record_event(divya, "advanced", "Screening", "Interview")
db.record_event(divya, "advanced", "Interview", "Offer")
backdate(divya, "Offer", 1)

print("Seeded 7 candidates across the pipeline.")
