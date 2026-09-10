# Clinical Intel — SIH 2026 Prototype Backend

This backend is a lightweight, deployment-friendly FastAPI prototype for the Clinical Intel frontend.

## What is included
- 75 completely synthetic longitudinal patient records (CI-0001 to CI-0075)
- Patient search/list/detail
- 10-second clinical snapshot
- Timeline
- What Changed?
- Medications
- Alerts and conflict detection
- Source document metadata
- Patient-facing voice/touch intake question API
- Intake submission → structured history + red-flag detection
- AYUSH mode field definitions
- CORS support for Base44 frontend
- No real patient data

## Run

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Health check
`GET /api/health`

The health response should report 75 patients.

## Main endpoints

- `GET /api/patients`
- `GET /api/patients/{patient_id}`
- `GET /api/patients/{patient_id}/snapshot`
- `GET /api/patients/{patient_id}/timeline`
- `GET /api/patients/{patient_id}/changes`
- `GET /api/patients/{patient_id}/medications`
- `GET /api/patients/{patient_id}/conflicts`
- `GET /api/patients/{patient_id}/documents`
- `GET /api/patients/{patient_id}/facts`
- `GET /api/intake/questions`
- `POST /api/intake/submit`
- `GET /api/patients/{patient_id}/search?q=...`

## Important prototype note
The 75 patient records are synthetic. The intake API and red-flag detector are deterministic prototype logic and are not a clinical diagnostic system. The physician remains the final decision-maker.

The supplied dataset contains document *references/metadata*, not a PDF for every synthetic document. The existing full OCR backend can be integrated later if live document OCR is required.
