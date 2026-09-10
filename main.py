from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
PATIENT_DIR = BASE_DIR / "data"


def load_patients() -> dict[str, dict[str, Any]]:
    patients: dict[str, dict[str, Any]] = {}
    for path in sorted(PATIENT_DIR.glob("CI-*.json")):
        with path.open("r", encoding="utf-8") as f:
            record = json.load(f)
        patients[record["patient_id"]] = record
    return patients


PATIENTS = load_patients()

app = FastAPI(
    title="Clinical Intel Prototype API",
    version="2.0.0",
    description=(
        "Prototype API for Clinical Intel. Uses 75 completely synthetic longitudinal "
        "patient records. No real patient data is included."
    ),
)

origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IntakeAnswer(BaseModel):
    question_id: str
    answer: str = Field(default="", max_length=2000)


class IntakeSubmit(BaseModel):
    patient_id: str
    language: str = "English"
    mode: str = "voice"
    answers: list[IntakeAnswer] = []


def get_patient(patient_id: str) -> dict[str, Any]:
    p = PATIENTS.get(patient_id.upper())
    if not p:
        raise HTTPException(404, f"Patient {patient_id} not found")
    return p


def public_patient(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "patient_id": p["patient_id"],
        "name": p["name"],
        "date_of_birth": p.get("date_of_birth"),
        "age": p.get("age"),
        "gender": p.get("gender"),
        "abha_id": p.get("abha_id"),
        "synthetic": True,
        "consent": p.get("consent", {}),
        "conditions": p.get("conditions", []),
        "allergies": p.get("allergies", []),
        "medication_count": len(p.get("medications", [])),
        "encounter_count": len(p.get("encounters", [])),
        "document_count": len(p.get("documents", [])),
    }


def conflicts_for(p: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    allergies = p.get("allergies", [])
    by_substance: dict[str, list[dict[str, Any]]] = {}
    for a in allergies:
        by_substance.setdefault(a.get("substance", "").lower(), []).append(a)
    for substance, rows in by_substance.items():
        statuses = {r.get("verification_status") for r in rows}
        if "conflicting" in statuses or len({r.get("status") for r in rows}) > 1:
            conflicts.append({
                "id": f"{p['patient_id']}-CONFLICT-{len(conflicts)+1:03d}",
                "kind": "ALLERGY_STATUS_CONFLICT",
                "subject": rows[0].get("substance"),
                "severity": "HIGH",
                "status": "open",
                "description": (
                    f"Conflicting allergy status for {rows[0].get('substance')}: "
                    "records disagree on whether the allergy is active."
                ),
                "evidence": rows,
            })
    return conflicts


def clinical_snapshot(p: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(p.get("clinical_snapshot", {}))
    conflicts = conflicts_for(p)
    alerts = list(snapshot.get("critical_alerts", []))
    if conflicts:
        alerts.append("Conflicting allergy record — clinician verification required")
    return {
        "patient": public_patient(p),
        "generated_at": "prototype",
        "counts": {
            "documents": len(p.get("documents", [])),
            "encounters": len(p.get("encounters", [])),
            "conditions": len(p.get("conditions", [])),
            "medications": len(p.get("medications", [])),
            "open_conflicts": len(conflicts),
        },
        **snapshot,
        "conflicts": conflicts,
        "alerts": alerts,
        "safety_note": "AI output is informational; physician review remains required.",
    }


# -------------------------------------------------------------------------
# Meta
@app.get("/", tags=["meta"])
def root():
    return {
        "service": "Clinical Intel Prototype API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "synthetic_dataset": True,
        "patient_count": len(PATIENTS),
    }


@app.get("/api/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "service": "Clinical Intel Prototype API",
        "synthetic_dataset": True,
        "patients": len(PATIENTS),
        "message": "75 synthetic longitudinal patient records loaded",
    }


# -------------------------------------------------------------------------
# Patients
@app.get("/api/patients", tags=["patients"])
def list_patients(q: str | None = None, limit: int = 75):
    rows = [public_patient(PATIENTS[k]) for k in sorted(PATIENTS)]
    if q:
        needle = q.lower().strip()
        rows = [
            r for r in rows
            if needle in r["patient_id"].lower()
            or needle in r["name"]["display"].lower()
            or needle in (r.get("abha_id") or "").lower()
        ]
    return {"count": len(rows), "patients": rows[: max(1, min(limit, 200))]}


@app.get("/api/patients/{patient_id}", tags=["patients"])
def patient_detail(patient_id: str):
    p = get_patient(patient_id)
    return {
        **public_patient(p),
        "contact": p.get("contact", {}),
        "clinical_snapshot": p.get("clinical_snapshot", {}),
        "conditions": p.get("conditions", []),
        "allergies": p.get("allergies", []),
        "medications": p.get("medications", []),
        "observations": p.get("observations", []),
        "encounters": p.get("encounters", []),
        "documents": p.get("documents", []),
        "timeline": p.get("timeline", []),
    }


@app.get("/api/patients/{patient_id}/snapshot", tags=["clinical"])
def patient_snapshot(patient_id: str):
    return clinical_snapshot(get_patient(patient_id))


@app.get("/api/patients/{patient_id}/timeline", tags=["clinical"])
def patient_timeline(patient_id: str):
    p = get_patient(patient_id)
    events = sorted(p.get("timeline", []), key=lambda x: x.get("date", ""), reverse=True)
    return {"patient_id": p["patient_id"], "event_count": len(events), "events": events}


@app.get("/api/patients/{patient_id}/changes", tags=["clinical"])
def patient_changes(patient_id: str):
    p = get_patient(patient_id)
    return {
        "patient_id": p["patient_id"],
        "changes": p.get("clinical_snapshot", {}).get("recent_changes", []),
    }


@app.get("/api/patients/{patient_id}/medications", tags=["clinical"])
def patient_medications(patient_id: str):
    p = get_patient(patient_id)
    return {"patient_id": p["patient_id"], "medications": p.get("medications", [])}


@app.get("/api/patients/{patient_id}/medication-links", tags=["clinical"])
def medication_links(patient_id: str):
    p = get_patient(patient_id)
    return {
        "patient_id": p["patient_id"],
        "links": [
            {
                "medication": m.get("name"),
                "dose": m.get("dose"),
                "frequency": m.get("frequency"),
                "indication": m.get("indication"),
            }
            for m in p.get("medications", [])
        ],
    }


@app.get("/api/patients/{patient_id}/conflicts", tags=["clinical"])
def patient_conflicts(patient_id: str):
    p = get_patient(patient_id)
    conflicts = conflicts_for(p)
    return {"patient_id": p["patient_id"], "open": conflicts, "history": conflicts}


@app.get("/api/patients/{patient_id}/documents", tags=["documents"])
def patient_documents(patient_id: str):
    p = get_patient(patient_id)
    return {"patient_id": p["patient_id"], "documents": p.get("documents", [])}


@app.get("/api/patients/{patient_id}/facts", tags=["facts"])
def patient_facts(patient_id: str, category: str | None = None):
    p = get_patient(patient_id)
    facts: list[dict[str, Any]] = []
    for c in p.get("conditions", []):
        facts.append({"category": "CONDITION", "name": c.get("name"), "value": c.get("clinical_status"), "date": c.get("onset_date")})
    for a in p.get("allergies", []):
        facts.append({"category": "ALLERGY", "name": a.get("substance"), "value": a.get("reaction"), "date": a.get("recorded_date"), "verification": a.get("verification_status")})
    for m in p.get("medications", []):
        facts.append({"category": "MEDICATION", "name": m.get("name"), "value": m.get("dose"), "unit": m.get("frequency"), "date": m.get("start_date")})
    for o in p.get("observations", []):
        facts.append({"category": "LAB_RESULT", "name": o.get("name"), "value": o.get("value"), "unit": o.get("unit"), "date": o.get("date")})
    if category:
        wanted = {x.strip().upper() for x in category.split(",")}
        facts = [f for f in facts if f["category"] in wanted]
    return {"patient_id": p["patient_id"], "facts": facts}


# -------------------------------------------------------------------------
# AI case-taking / patient intake prototype
HISTORY_QUESTIONS = [
    {"id": "language", "section": "intake", "question": "Which language would you prefer for your consultation?", "type": "choice", "options": ["English", "Hindi", "Marathi", "Other"]},
    {"id": "chief_complaint", "section": "chief_complaint", "question": "What brings you to the hospital today?", "type": "voice_or_text"},
    {"id": "onset", "section": "hpi", "question": "When did this problem start?", "type": "voice_or_text"},
    {"id": "severity", "section": "hpi", "question": "How severe is the problem right now?", "type": "choice", "options": ["Mild", "Moderate", "Severe"]},
    {"id": "associated_symptoms", "section": "ros", "question": "Are you experiencing any other symptoms?", "type": "voice_or_text"},
    {"id": "past_history", "section": "past_history", "question": "Do you have any existing medical conditions or previous surgeries?", "type": "voice_or_text"},
    {"id": "medications", "section": "drug_history", "question": "What medicines are you currently taking?", "type": "voice_or_text"},
    {"id": "allergies", "section": "allergy_history", "question": "Do you have any known drug or food allergies?", "type": "voice_or_text"},
    {"id": "family_history", "section": "family_history", "question": "Is there any important medical history in your family?", "type": "voice_or_text"},
    {"id": "personal_history", "section": "personal_history", "question": "Tell us about relevant diet, lifestyle, smoking, alcohol, or other personal history.", "type": "voice_or_text"},
]


@app.get("/api/intake/questions", tags=["intake"])
def intake_questions(language: str = "English", mode: str = "voice"):
    return {
        "language": language,
        "mode": mode,
        "supports": ["voice", "touch"],
        "adaptive_questioning": True,
        "questions": HISTORY_QUESTIONS,
        "ayush_mode": {
            "available": True,
            "fields": ["Prakriti", "Vikriti", "Sara", "Samhanana", "Satmya", "Sattva", "Ahara Shakti", "Vyayama Shakti", "Vaya", "Ahara-Vihara"],
        },
    }


@app.post("/api/intake/submit", tags=["intake"])
def intake_submit(body: IntakeSubmit):
    p = get_patient(body.patient_id)
    answer_map = {a.question_id: a.answer.strip() for a in body.answers if a.answer.strip()}
    chief = answer_map.get("chief_complaint", "Not provided")
    red_flags = detect_red_flags(" ".join(answer_map.values()))
    summary = {
        "patient_id": p["patient_id"],
        "language": body.language,
        "mode": body.mode,
        "chief_complaint": chief,
        "history_of_present_illness": {
            "onset": answer_map.get("onset"),
            "severity": answer_map.get("severity"),
            "associated_symptoms": answer_map.get("associated_symptoms"),
        },
        "past_medical_surgical_history": answer_map.get("past_history"),
        "drug_history": answer_map.get("medications"),
        "allergy_history": answer_map.get("allergies"),
        "family_history": answer_map.get("family_history"),
        "personal_history": answer_map.get("personal_history"),
        "red_flags": red_flags,
        "existing_longitudinal_record_available": True,
        "doctor_action": "Review, edit and confirm before saving.",
    }
    return {
        "status": "success",
        "intake_summary": summary,
        "existing_patient_snapshot": clinical_snapshot(p),
        "next_step": "consultation",
    }


def detect_red_flags(text: str) -> list[dict[str, str]]:
    t = text.lower()
    patterns = [
        (r"chest pain.*(breath|breathlessness|dyspnea|difficulty breathing)|(?:breath|breathlessness|dyspnea).*chest pain", "Possible acute cardiopulmonary red flag", "HIGH"),
        (r"(face|arm).*weak|weak.*(face|arm).*speech|slurred speech", "Possible stroke red flag", "CRITICAL"),
        (r"severe bleeding|uncontrolled bleeding|vomiting blood|blood in vomit", "Potential major bleeding red flag", "CRITICAL"),
        (r"fainting|loss of consciousness|unconscious", "Altered consciousness / syncope red flag", "HIGH"),
    ]
    results = []
    for pattern, message, severity in patterns:
        if re.search(pattern, t):
            results.append({"severity": severity, "message": message, "action": "Notify triage staff immediately."})
    return results


@app.post("/api/patients/{patient_id}/documents/register", tags=["documents"])
def register_demo_document(patient_id: str, filename: str):
    p = get_patient(patient_id)
    return {
        "status": "registered",
        "patient_id": p["patient_id"],
        "filename": filename,
        "mode": "prototype",
        "message": "For the demo, use the supplied synthetic document metadata. Live OCR can be connected later.",
    }


@app.get("/api/patients/{patient_id}/search", tags=["search"])
def patient_search(patient_id: str, q: str):
    p = get_patient(patient_id)
    needle = q.lower().strip()
    results: list[dict[str, Any]] = []
    for item in p.get("timeline", []):
        text = " ".join(str(item.get(k, "")) for k in ["title", "details", "source_hospital", "type"]).lower()
        if needle in text:
            results.append({"type": "timeline", "item": item})
    for item in p.get("documents", []):
        text = " ".join(str(item.get(k, "")) for k in item.keys()).lower()
        if needle in text:
            results.append({"type": "document", "item": item})
    return {"patient_id": p["patient_id"], "query": q, "results": results[:20]}


# Compatibility endpoints used by the original Clinical Intel starter UI.
@app.get("/api/synthesize", tags=["compatibility"])
def synthesize_default():
    return clinical_snapshot(PATIENTS["CI-0001"])


@app.get("/api/patients/{patient_id}/synthesize", tags=["compatibility"])
def synthesize_patient(patient_id: str):
    return clinical_snapshot(get_patient(patient_id))
