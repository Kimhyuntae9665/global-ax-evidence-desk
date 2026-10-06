"""Validation, auditable correction, version-bound review and source retrieval."""

import csv
import hashlib
import io
import json
import re
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

PERIOD = "2026-09"
UNITS = {"kWh": Decimal("1"), "MWh": Decimal("1000")}


class DeskError(ValueError):
    def __init__(self, message, code="bad_request", status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def decimal_text(value):
    return format(value, "f")


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def validate(records):
    """Every member of an unresolved duplicate group is invalid, never summed."""
    counts = Counter((r["site"].strip().casefold(), r["period"], r["energy"].strip().casefold())
                     for r in records if not r.get("excluded"))
    validated = []
    for original in records:
        r = dict(original)
        r["issues"] = []
        r["normalized_kwh"] = None
        if r.get("excluded"):
            r["status"] = "excluded"
            validated.append(r)
            continue

        def issue(code, message):
            r["issues"].append({"code": code, "message": message})

        raw = r.get("value")
        number = None
        if raw is None or str(raw).strip() == "":
            issue("missing_value", "Missing value is unknown; check the source document.")
        else:
            try:
                number = Decimal(str(raw))
                if not number.is_finite():
                    raise InvalidOperation
                if number.is_zero():
                    number = Decimal(0)
                if number.as_tuple().exponent < -9:
                    issue("unsupported_precision", "At most nine decimal places are supported.")
                if number.copy_abs() > Decimal("1000000000000"):
                    issue("out_of_range", "Value exceeds this demonstration's supported range.")
                if number < 0:
                    issue("negative_value", "Energy use cannot be negative.")
            except InvalidOperation:
                issue("invalid_number", "Value must be a finite decimal number.")
        if r.get("unit") not in UNITS:
            issue("unsupported_unit", "Only kWh and MWh are supported.")
        if r.get("period") != PERIOD:
            issue("stale_period", "Reporting period must be 2026-09.")
        key = (r["site"].strip().casefold(), r["period"], r["energy"].strip().casefold())
        if counts[key] > 1:
            issue("duplicate_submission", "Duplicate site, period and energy; reconcile or exclude with a reason.")
        if not r.get("source_doc"):
            issue("missing_source", "A source document reference is required.")
        r["status"] = "invalid" if r["issues"] else "valid"
        if not r["issues"]:
            r["normalized_kwh"] = decimal_text(number * UNITS[r["unit"]])
        validated.append(r)
    return validated


class Desk:
    def __init__(self, db_path, data_dir):
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, body TEXT NOT NULL);"
                             "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);"
                             "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, body TEXT NOT NULL);")
            if db.execute("SELECT count(*) FROM records").fetchone()[0] == 0:
                self._seed(db)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _seed(self, db):
        for r in json.loads((self.data_dir / "records.json").read_text(encoding="utf-8")):
            r.update(excluded=False, exclusion_reason="", version=1)
            db.execute("INSERT INTO records VALUES (?, ?)", (r["id"], canonical(r)))

    def _records(self, db):
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM records ORDER BY id")]

    def documents(self):
        return json.loads((self.data_dir / "sop.json").read_text(encoding="utf-8"))

    def _state(self, db):
        raw = self._records(db)
        docs = self.documents()
        current_docs = [d for d in docs if d["status"] == "current"]
        digests = {"data": digest(raw), "corpus": digest(current_docs)}
        records = validate(raw)
        review_row = db.execute("SELECT body FROM metadata WHERE key='review'").fetchone()
        review = json.loads(review_row[0]) if review_row else {
            "reviewer": "", "note": "", "reviewed_at": None,
            "data_digest": None, "corpus_digest": None}
        review["status"] = ("unreviewed" if not review_row else "current"
                            if review["data_digest"] == digests["data"] and
                            review["corpus_digest"] == digests["corpus"] else "stale")
        valid = [r for r in records if r["status"] == "valid"]
        summary = {"valid_count": len(valid),
                   "invalid_count": sum(r["status"] == "invalid" for r in records),
                   "excluded_count": sum(r["status"] == "excluded" for r in records),
                   "unresolved_count": sum(len(r["issues"]) for r in records),
                   "normalized_kwh": decimal_text(sum((Decimal(r["normalized_kwh"]) for r in valid), Decimal(0)))}
        audit = []
        for row in db.execute("SELECT id, body FROM audit ORDER BY id DESC LIMIT 100"):
            event = json.loads(row[1])
            event["id"] = row[0]
            audit.append(event)
        return {"period": PERIOD, "synthetic": True, "records": records,
                "documents": docs, "summary": summary, "digests": digests,
                "review": review, "audit": audit, "retrieval_mode": "retrieval-only"}

    def state(self):
        with self.connect() as db:
            return self._state(db)

    def _audit(self, db, action, record_id, before, after):
        db.execute("INSERT INTO audit (body) VALUES (?)", (canonical({
            "at": timestamp(), "action": action, "record_id": record_id,
            "before": before, "after": after}),))

    def repair(self, payload):
        allowed = {"id", "value", "unit", "period", "excluded", "reason"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise DeskError("Unknown repair fields.")
        if not isinstance(payload.get("id"), str):
            raise DeskError("A record id is required.")
        if not set(payload) - {"id"}:
            raise DeskError("Provide a correction.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM records WHERE id=?", (payload["id"],)).fetchone()
            if not row:
                raise DeskError("Record not found.", "not_found", 404)
            before = json.loads(row[0])
            after = dict(before)
            if "value" in payload:
                value = payload["value"]
                if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
                    raise DeskError("Value must be a number, decimal string or null.")
                if value is not None and len(str(value)) > 80:
                    raise DeskError("Value is too long.")
                after["value"] = str(value).strip() if value is not None else None
            for field in ("unit", "period"):
                if field in payload:
                    if not isinstance(payload[field], str) or len(payload[field]) > 30:
                        raise DeskError(f"Invalid {field}.")
                    after[field] = payload[field].strip()
            if "excluded" in payload:
                if not isinstance(payload["excluded"], bool):
                    raise DeskError("Excluded must be true or false.")
                after["excluded"] = payload["excluded"]
                if not after["excluded"]:
                    after["exclusion_reason"] = ""
            if "reason" in payload:
                if not isinstance(payload["reason"], str) or len(payload["reason"]) > 500:
                    raise DeskError("Reason must be text of at most 500 characters.")
                after["exclusion_reason"] = payload["reason"].strip()
            if after["excluded"] and not after["exclusion_reason"]:
                raise DeskError("Excluding a record requires a reason.", "reason_required")
            after["version"] += 1
            db.execute("UPDATE records SET body=? WHERE id=?", (canonical(after), after["id"]))
            self._audit(db, "repair", after["id"], before, after)
            return self._state(db)

    def review(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"reviewer", "note", "digests"}:
            raise DeskError("Unknown review fields.")
        observed = payload.get("digests")
        if (not isinstance(observed, dict) or set(observed) != {"data", "corpus"} or
                any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                    for value in observed.values())):
            raise DeskError("Review requires the displayed data and corpus SHA-256 digests.", "invalid_snapshot")
        reviewer, note = payload.get("reviewer", ""), payload.get("note", "")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 100:
            raise DeskError("Reviewer name is required (maximum 100 characters).")
        if not isinstance(note, str) or not note.strip() or len(note) > 2000:
            raise DeskError("A review note is required (maximum 2000 characters).")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._state(db)
            if observed != state["digests"]:
                raise DeskError("Data or current SOP changed since the displayed snapshot. Refresh and review again.",
                                "stale_snapshot", 409)
            if state["summary"]["unresolved_count"]:
                raise DeskError("Resolve validation issues before review.", "validation_blocked", 409)
            review = {"reviewer": reviewer.strip(), "note": note.strip(), "reviewed_at": timestamp(),
                      "data_digest": state["digests"]["data"], "corpus_digest": state["digests"]["corpus"]}
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('review', ?)", (canonical(review),))
            self._audit(db, "human_review_demo", None, state["review"], review)
            return self._state(db)

    def export(self):
        state = self.state()
        if state["summary"]["unresolved_count"]:
            raise DeskError("Resolve all validation issues before export.", "validation_blocked", 409)
        if state["review"]["status"] != "current":
            raise DeskError("Current data and SOP corpus require human review.", "review_required", 409)
        output = io.StringIO(newline="")
        fields = ["id", "site", "country", "period", "energy", "value", "unit", "normalized_kwh", "source_doc"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(r for r in state["records"] if r["status"] == "valid")
        return output.getvalue()

    def reset(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            before = self._records(db)
            db.execute("DELETE FROM records")
            self._seed(db)
            db.execute("DELETE FROM metadata WHERE key='review'")
            self._audit(db, "reset_demo", None, before, self._records(db))
            return self._state(db)

    def ask(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"question", "language", "generate"}:
            raise DeskError("Unknown question fields.")
        if "generate" in payload and not isinstance(payload["generate"], bool):
            raise DeskError("Generate must be true or false.")
        question = payload.get("question", "")
        language = payload.get("language", "en")
        if not isinstance(question, str) or not question.strip() or len(question) > 2000:
            raise DeskError("Question must contain 1 to 2000 characters.")
        if language not in {"en", "ko", "vi"}:
            raise DeskError("Language must be en, ko or vi.")
        stopwords = {"a", "an", "the", "is", "are", "what", "how", "do", "i", "to", "for", "of", "can", "we", "and", "in", "with", "this", "it", "my"}
        terms = set(re.findall(r"[^\W_]+", question.casefold(), re.UNICODE)) - stopwords
        scored = []
        for doc in self.documents():
            if doc["status"] != "current" or doc["language"] != language:
                continue
            for paragraph in doc["text"].split("\n\n")[1:]:
                words = set(re.findall(r"[^\W_]+", paragraph.casefold(), re.UNICODE))
                # Korean particles are handled as lexical prefix overlap, not semantic inference.
                hits = {term for term in terms if term in words or (language == "ko" and len(term) >= 2 and
                         any(word.startswith(term) or term.startswith(word) for word in words if len(word) >= 2))}
                if hits:
                    scored.append((len(hits), doc, paragraph))
        scored.sort(key=lambda item: (-item[0], item[1]["id"], item[2]))
        citations = [{"doc_id": doc["id"], "title": doc["title"], "revision": doc["revision"],
                      "language": doc["language"], "quote": quote, "source_digest": digest(doc)}
                     for _, doc, quote in scored[:2]]
        abstained = not citations
        no_evidence = {"en": "The current synthetic SOP does not contain sufficient matching evidence. Human clarification is required.",
                       "ko": "현행 가상 절차에서 충분한 근거를 찾지 못했습니다. 담당자의 확인이 필요합니다.",
                       "vi": "Quy trình giả lập hiện hành không có đủ bằng chứng phù hợp. Cần người phụ trách làm rõ."}
        result = {"mode": "retrieval-only", "abstained": abstained,
                "answer": no_evidence[language] if abstained else "\n\n".join(c["quote"] for c in citations),
                "citations": citations, "retrieval": {"terms": sorted(terms), "method": "lexical-overlap", "candidate_count": len(scored)},
                "notice": "Deterministic source excerpts; no language model was used. Synthetic SOP guidance requires human interpretation."}
        if payload.get("generate") and not abstained:
            try:
                from .generation import augment
                return augment(result, question, language)
            except Exception:
                result.update(mode="generation-unavailable", generated=False,
                              generation_error="Optional local model unavailable; source excerpts remain available.")
        return result
