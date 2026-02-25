# Face Recognition Presence Pipeline — Design Doc

**Date:** 2026-02-25
**Status:** Approved for implementation
**Scope:** `ha-aria` — extends `aria/modules/presence.py`, new `aria/faces/` module, new ARIA UI page

---

## Bottom Line

Build a closed-loop face recognition pipeline that bootstraps from 247GB of existing Frigate footage, continuously improves through active learning, and drives ARIA presence detection — so that labeling degrades to an outlier activity within weeks, not a permanent burden.

## Recommendation

Extend ARIA's existing presence module with a DeepFace/FaceNet512 embedding store and adaptive per-person confidence thresholds. 80% of the infrastructure (MQTT subscriber, face event handler, presence fusion, background task scheduler) already exists. The new work is: embedding store, DBSCAN bootstrap clustering, review queue API + UI page, and Frigate writeback.

---

## Context

- **Frigate 0.16.4** running on workstation, face recognition already enabled in config (`face_recognition.enabled: true`, models downloaded: `facedet.onnx`, `facenet.tflite`)
- **1,451 person events** in Frigate DB, all `sub_label = null` (no faces labeled yet)
- **2,896 snapshots** in `clips/` — bootstrap training source
- **Frigate faces dir** `/media/frigate/clips/faces/` — empty, ready for training images
- **ARIA presence module** already handles Frigate MQTT events and `sub_label` face data (partial)
- **Disk:** 247GB consumed by Frigate recordings — prune after bootstrap + labeling complete

---

## Architecture

### Data Flow

```
[Bootstrap — one-time]
Frigate clips/ (2,896 snapshots)
  → DeepFace.represent() — 512-d FaceNet embedding per face
  → DBSCAN clustering (cosine distance, eps=0.4)
  → cluster_N/ folders in ARIA cache
  → ARIA UI review queue — user labels each cluster
  → labeled embeddings → face_embeddings table (ARIA SQLite)
  → best N images per person → /media/frigate/faces/<name>/
  → Frigate reload

[Live pipeline — continuous]
Frigate person event (MQTT)
  → aria/modules/presence.py:_handle_frigate_event()  [EXTEND]
  → fetch face crop from Frigate snapshot API
  → DeepFace.represent() — 512-d embedding
  → compare against face_embeddings store (cosine similarity)
  → confidence >= per-person threshold → auto-label → HA presence update
  → confidence < threshold → insert into review_queue table
  → ARIA UI review queue (sorted by information gain)
  → user labels → embedding added to store
  → auto-label rate rises, queue shrinks over time
  → periodic writeback: new labeled embeddings → Frigate faces dir
```

### Confidence Threshold Strategy

Adaptive per-person, not global. Formula from [1810.11160]:

```python
threshold = max(0.50, 0.85 - (0.005 * labeled_count))
# 5 samples  → 0.825  (new person, cautious)
# 50 samples → 0.60   (well-known, more permissive)
# 70+ samples→ 0.50   (floor — never go lower)
```

This implements the +22% accuracy improvement from data-specific adaptive thresholds.

### Active Learning Queue Priority

Sort by information gain (uncertainty sampling), not chronological:

```python
# Sort review queue: most uncertain first
priority = 1.0 - max(candidate_confidences)
# Low max_confidence = high uncertainty = high value per label
```

Validates approach from arxiv [2511.05574] (Active Continuous Learning with Uncertainty Self-Awareness).

---

## Components

### New: `aria/faces/`

| File | Purpose |
|------|---------|
| `aria/faces/__init__.py` | Module init |
| `aria/faces/store.py` | `FaceEmbeddingStore` — SQLite CRUD for embeddings + review queue |
| `aria/faces/extractor.py` | DeepFace wrapper — `extract_embedding(img_path)`, `extract_from_event(event_id)` |
| `aria/faces/bootstrap.py` | Batch pipeline: scan clips/ → embed → DBSCAN cluster → write clusters.json |
| `aria/faces/pipeline.py` | Live pipeline: event → embed → match → auto-label or queue |

### Modified: `aria/modules/presence.py`

- `_handle_frigate_event()` (lines 481–540): add call to `faces.pipeline.process_event()` when `sub_label` is null or confidence is low
- `_identified_persons` dict: add `embedding_id`, `confidence`, `threshold` fields

### New: `aria/hub/routes_faces.py`

```
GET  /api/faces/queue           — review queue, sorted by priority
POST /api/faces/label           — label a queued face {event_id, person_name}
GET  /api/faces/people          — known people, embedding count, auto-label rate
GET  /api/faces/stats           — queue depth, auto-label rate, accuracy trend
POST /api/faces/bootstrap       — kick off batch extraction job
POST /api/faces/deploy          — write labeled embeddings to Frigate faces dir
GET  /api/faces/clusters        — DBSCAN cluster list + sample images (bootstrap UI)
POST /api/faces/clusters/label  — label a cluster {cluster_id, person_name}
```

### New: ARIA UI — `Faces` page

Location: `aria/dashboard/spa/src/pages/Faces.jsx`
Nav: System section in sidebar (alongside Data Curation, Validation)

**Sections:**
1. **Stats header** — queue depth / auto-label rate (%) / known people count
2. **Bootstrap panel** — run once; shows cluster grid with face thumbnails; name input per cluster
3. **Review queue** — face image + top-3 candidate names with confidence bars; confirm or correct
4. **People roster** — grid of known people, training sample count, per-person confidence trend

### Database Schema

New table in ARIA's SQLite DB (`~/.local/share/aria/hub.db` or equivalent):

```sql
CREATE TABLE face_embeddings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_name TEXT,           -- NULL = unidentified
    embedding   BLOB NOT NULL,  -- 512-d float32 numpy array, ~2KB
    event_id    TEXT,           -- Frigate event ID
    image_path  TEXT,           -- path to source snapshot
    confidence  REAL,           -- match confidence at time of labeling
    source      TEXT NOT NULL,  -- 'bootstrap' | 'live' | 'manual'
    verified    INTEGER DEFAULT 0,  -- 1 = human-confirmed
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE face_review_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL,
    image_path      TEXT NOT NULL,
    embedding       BLOB NOT NULL,
    top_candidates  TEXT,   -- JSON: [{name, confidence}, ...]
    priority        REAL,   -- 1.0 - max_candidate_confidence (higher = more uncertain)
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    reviewed_at     DATETIME
);

CREATE INDEX idx_embeddings_person ON face_embeddings(person_name);
CREATE INDEX idx_queue_priority ON face_review_queue(priority DESC, reviewed_at);
```

---

## Dependencies

```
# Add to pyproject.toml / requirements
deepface>=0.0.93        # FaceNet512 backend — face detection + alignment + embedding
scikit-learn>=1.3       # DBSCAN clustering for bootstrap
numpy>=1.24             # embedding arithmetic
```

No cmake. No dlib build. `pip install deepface` downloads FaceNet512 weights on first use (~600MB, cached in `~/.deepface/`).

---

## Reuse Map (from codebase audit)

| Component | Source | Lines | Action |
|-----------|--------|-------|--------|
| MQTT subscriber | `presence.py` | 418–468 | Copy pattern |
| Face event handler | `presence.py` | 481–540 | Extend — add embedding call |
| Identified persons tracking | `presence.py` | 533–539 | Extend — add embedding_id |
| Background task scheduler | `hub/core.py` | 422–455 | `hub.schedule_task()` directly |
| FastAPI router registration | `hub/api.py` | 122–188 | Copy pattern |
| Module base class | `hub/core.py` | 19–57 | Inherit for FaceRecognitionModule |
| Hub cache API | throughout | — | `hub.set_cache('faces', ...)` |

---

## Implementation Phases

### Phase 1 — Foundation (embedding store + bootstrap)
1. Install deepface, scikit-learn in ARIA venv
2. Create `aria/faces/store.py` — SQLite schema + CRUD
3. Create `aria/faces/extractor.py` — DeepFace wrapper
4. Create `aria/faces/bootstrap.py` — batch clip processing + DBSCAN
5. Bootstrap API endpoints (`/bootstrap`, `/clusters`, `/clusters/label`, `/deploy`)
6. Bootstrap UI panel in Faces.jsx

### Phase 2 — Live pipeline
7. Create `aria/faces/pipeline.py` — live event processing
8. Extend `presence.py:_handle_frigate_event()` — hook into pipeline
9. Review queue API + UI (queue, label endpoints + review panel)
10. Adaptive threshold logic in `store.py`

### Phase 3 — Polish + presence integration
11. Stats + people roster API + UI
12. Periodic Frigate writeback task (`hub.schedule_task`)
13. Presence signal update — recognized face fires HA state change
14. Add `faces` to sidebar nav, wire routes in `app.jsx`

---

## Upgrade Path

Once 50+ labeled embeddings per person:
- Switch DeepFace backend: `DeepFace.represent(model_name='ArcFace')` — one line change
- Re-run bootstrap to regenerate embeddings (store schema unchanged)
- ArcFace: better on diverse faces, hard negatives (e.g. similar-looking siblings)

Long-term: EdgeFace (2023 IJCB winner) if CPU becomes bottleneck — ~3.5MB model, edge-optimized.

---

## Success Metrics

| Metric | Target | Timeline |
|--------|--------|----------|
| Bootstrap cluster accuracy | >80% pure clusters (one person per cluster) | Day 1 |
| Auto-label rate | >70% | Week 1 after bootstrap |
| Auto-label rate | >90% | Week 4 |
| Review queue depth | <5 items/day | Week 4 |
| Presence accuracy | >95% for household members | Week 2 |

**Pivot trigger:** If bootstrap cluster purity <60% (face crops too small/blurry for FaceNet512 to embed reliably), fall back to extracting frames directly from Frigate recordings (not just snapshot thumbnails) using ffmpeg.

---

## Lean Gate

- **Hypothesis:** Face recognition reduces manual presence-marking and improves ARIA's location accuracy for household members
- **MVP:** Bootstrap + live pipeline + review queue. No advanced analytics until auto-label rate >80%
- **First users:** Justin + household (~5 people)
- **Success metric:** Auto-label rate >80% within 2 weeks of bootstrap
- **Pivot trigger:** <60% bootstrap cluster purity → switch to recording frame extraction

---

## References

- [Active Continuous Learning with Uncertainty Self-Awareness — arxiv 2511.05574](https://arxiv.org/abs/2511.05574)
- [Data-Specific Adaptive Threshold for Face Recognition — arxiv 1810.11160](https://arxiv.org/abs/1810.11160)
- [EdgeFace: Efficient Face Recognition for Edge Devices — arxiv 2307.01838](https://arxiv.org/abs/2307.01838)
- [FaceNet512 vs ArcFace comparison (2023)](https://scispace.com/papers/comparison-of-face-recognition-accuracy-of-arcface-facenet-o614ksrw)
- [FewFaceNet: Incremental Face Auth for Edge — ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023W/ACVR/papers/Sufian_FewFaceNet_A_Lightweight_Few-Shot_Learning-Based_Incremental_Face_Authentication_for_Edge_ICCVW_2023_paper.pdf)
