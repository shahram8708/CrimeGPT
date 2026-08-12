from app.tasks.ai_tasks import (
    compare_documents_task,
    identify_clauses_task,
    legal_intel_task,
    run_compare_documents,
    run_identify_clauses,
    run_legal_intel,
)
from app.tasks.document_tasks import (
    export_diary_task,
    generate_document_task,
    process_evidence_task,
    run_export_diary,
    run_generate_document,
    run_process_evidence,
)
from app.tasks.mail_tasks import run_send_email, send_email_task
from app.tasks.system_tasks import run_system_ping, system_ping
