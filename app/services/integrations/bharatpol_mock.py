import json
from datetime import datetime, timezone

from app.extensions import db
from app.models import CaseIntegration
from app.models.mixins import utcnow


def push_fir_summary(case, actor):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    ack = f"BHARATPOL-DEMO-{case.station.code if case.station else 'XX'}-{stamp}"
    payload = {
        "cr": case.display_cr,
        "station": case.station.code if case.station else "",
        "demo": True,
    }
    row = CaseIntegration(
        case_id=case.id,
        system="bharatpol",
        ack_number=ack,
        payload_json=json.dumps(payload, ensure_ascii=False),
        created_by_id=actor.id,
        created_at=utcnow(),
    )
    db.session.add(row)
    db.session.commit()
    return {"ack_number": ack, "created_at": row.created_at, "row": row}
