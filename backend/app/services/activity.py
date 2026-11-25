from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..logging_setup import redact_secrets
from ..models import ActivityEvent

log = logging.getLogger("clipes.activity")


def record(
    db: Session,
    kind: str,
    message: str,
    *,
    level: str = "info",
    ref_type: str | None = None,
    ref_id: int | None = None,
    commit: bool = True,
) -> None:
    """Registra uma atividade (exibida no dashboard) e espelha no log da aplicação."""
    message = redact_secrets(message)
    db.add(ActivityEvent(kind=kind, message=message, level=level, ref_type=ref_type, ref_id=ref_id))
    getattr(log, "error" if level == "error" else "warning" if level == "warning" else "info")(
        "[%s] %s", kind, message
    )
    if commit:
        db.commit()
