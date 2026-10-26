from __future__ import annotations

import hashlib
import json


def _key(values: dict) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def key_for_payload(payload, idempotency_key: str | None = None) -> str:
    return _key(
        {
            "chat_id": payload.chat_id,
            "hashtag": payload.hashtag,
            "media_type": payload.media_type,
            "search_text": payload.search_text,
            "date_from": payload.date_from,
            "date_to": payload.date_to,
            "output_subfolder": payload.output_subfolder,
            "export_only": payload.export_only,
            "skip_same": payload.skip_same,
            "refresh_export": payload.refresh_export,
            "idempotency_key": idempotency_key or "",
        }
    )


def key_for_job(job) -> str:
    return _key(
        {
            "chat_id": job.chat_id,
            "hashtag": job.hashtag,
            "media_type": job.media_type.value,
            "search_text": job.search_text,
            "date_from": job.date_from,
            "date_to": job.date_to,
            "output_subfolder": job.output_subfolder,
            "export_only": job.export_only,
            "skip_same": job.skip_same,
            "refresh_export": job.refresh_export,
            "idempotency_key": "",
        }
    )
