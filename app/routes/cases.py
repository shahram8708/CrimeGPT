from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db, limiter
from app.forms.case_forms import (
    ArrestBlockForm,
    CaseEditForm,
    CaseWizardForm,
    ItemForm,
    MedicalForm,
    PartyForm,
    SectionManualForm,
    SectionRemoveForm,
    parse_local_dt,
    to_local_input,
)
from app.models import Case, CaseArrest, CaseItem, CaseMedical, CaseParty, CaseSection, PoliceStation, User
from app.models.case import CASE_CATEGORIES, CATEGORY_LABELS
from app.models.mixins import utcnow
from app.services.audit_service import write_audit
from app.services.authz import (
    can_access_case_list,
    can_confirm_sections,
    can_create_case,
    can_delete_case,
    can_edit_case_facts,
    can_lock_case,
    can_run_legal_intel,
    gemini_ready,
    require_case,
)
from app.services.case_service import (
    completeness,
    cr_taken,
    document_readiness,
    field_diff,
    get_by_uuid,
    list_paginated,
    next_actions,
    progress_chain,
    rebuild_fts,
    search_fts,
    station_io_choices,
    station_legal_choices,
    station_user_choices,
    timestamps_match,
)
from app.services.i18n import translate

cases_bp = Blueprint("cases", __name__)


def _int0(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _load_case(uuid_value, perm="view"):
    case = Case.query.filter_by(uuid=uuid_value).first()
    return require_case(current_user, case, perm)


def _station_choices():
    rows = PoliceStation.query.filter_by(is_active=True).order_by(PoliceStation.name).all()
    return [(s.id, f"{s.name} ({s.code})") for s in rows]


def _io_choices(station_id):
    return [(0, "-")] + [(u.id, u.full_name) for u in station_io_choices(station_id)]


def _legal_choices(station_id):
    return [(0, "-")] + [(u.id, u.full_name) for u in station_legal_choices(station_id)]


def _audit(action, case, extra=None):
    write_audit(
        action,
        object_type="case",
        object_id=case.uuid,
        actor=current_user,
        station_id=case.station_id,
        case_id=case.id,
        meta=extra,
    )


def _party_choices(case, extra_blank=True):
    rows = [(0, "-")] if extra_blank else []
    rows.extend((p.id, f"{p.full_name} ({p.role})") for p in case.live_parties())
    return rows


@cases_bp.route("/cases")
@login_required
def case_list():
    if not can_access_case_list(current_user):
        abort(403)
    filters = {
        "q": request.args.get("q") or "",
        "status": request.args.get("status") or "",
        "year": request.args.get("year") or "",
        "category": request.args.get("category") or "",
    }
    items, total, page, pages = list_paginated(
        current_user, filters, page=request.args.get("page") or 1
    )
    cards = [{"case": c, "completeness": completeness(c)} for c in items]
    return render_template(
        "cases/list.html",
        cases=cards,
        filters=filters,
        page_title=translate("nav.cases"),
        can_new=can_create_case(current_user),
        page=page,
        pages=pages,
        total=total,
        categories=CATEGORY_LABELS,
    )


@cases_bp.route("/cases/search")
@login_required
def case_search():
    if not can_access_case_list(current_user):
        abort(403)
    q = (request.args.get("q") or "").strip()
    results = search_fts(current_user, q) if len(q) >= 2 else None
    return render_template("cases/search.html", q=q, results=results)


@cases_bp.route("/cases/new", methods=["GET", "POST"])
@login_required
def case_new():
    if not can_create_case(current_user):
        abort(403)
    form = CaseWizardForm()
    needs_station = current_user.role in ("admin", "super_admin")
    form.station_id.choices = _station_choices() if needs_station else [(current_user.station_id or 0, "")]
    station_id = current_user.station_id
    if needs_station:
        station_id = form.station_id.data or (form.station_id.choices[0][0] if form.station_id.choices else 0)
    form.assigned_io_id.choices = _io_choices(station_id)
    form.assigned_io_id.coerce = _int0
    if request.method == "GET":
        form.year.data = datetime.now().year
        form.category.data = "hurt"
        if current_user.role == "io":
            form.assigned_io_id.data = current_user.id
        lang = "en"
        if current_user.preferences:
            lang = current_user.preferences.document_language or current_user.preferences.ui_language or "en"
        form.narrative_language.data = lang
        form.step.data = "1"
    step = _int0(request.form.get("step") or form.step.data or 1) or 1
    _render_kw = dict(
        needs_station=needs_station,
        offline=bool(current_user.preferences and current_user.preferences.offline_drafts),
    )
    if request.method == "POST":
        action = request.form.get("action") or form.action.data or "next"
        if action == "back":
            return render_template("cases/new.html", form=form, step=max(step - 1, 1), **_render_kw)
        if action == "skip_complainant":
            flash(translate("flash.complainant_skipped"), "warning")
            form.step.data = "3"
            return render_template("cases/new.html", form=form, step=3, **_render_kw)
        if action == "next" and step < 3:
            if step == 1:
                errors = False
                if not (form.incident_at.data or (request.form.get("incident_at") or "").strip()):
                    form.incident_at.errors = list(form.incident_at.errors) + [
                        "Enter the incident date and time."
                    ]
                    errors = True
                if not (form.place_of_occurrence.data or "").strip():
                    form.place_of_occurrence.errors = list(form.place_of_occurrence.errors) + [
                        "Enter the place of occurrence."
                    ]
                    errors = True
                if errors:
                    return render_template("cases/new.html", form=form, step=step, **_render_kw)
            if step == 2 and form.complainant_started() and not (form.complainant_name.data or "").strip():
                form.complainant_name.errors = list(form.complainant_name.errors) + [
                    "Enter the complainant's name or skip for now."
                ]
                return render_template("cases/new.html", form=form, step=2, **_render_kw)
            return render_template("cases/new.html", form=form, step=step + 1, **_render_kw)
        if form.validate_on_submit():
            if step == 2 and form.complainant_started() and not (form.complainant_name.data or "").strip():
                form.complainant_name.errors = list(form.complainant_name.errors) + [
                    "Enter the complainant's name or skip for now."
                ]
                return render_template("cases/new.html", form=form, step=2, **_render_kw)
            case = _save_wizard(form, complete=(action == "create"))
            if case is None:
                return render_template("cases/new.html", form=form, step=step, **_render_kw)
            if action == "save_draft":
                flash(translate("flash.draft_saved"), "success")
                form.case_uuid.data = case.uuid
                return render_template("cases/new.html", form=form, step=step, **_render_kw)
            flash(translate("flash.case_created"), "success")
            return redirect(url_for("cases.overview", uuid=case.uuid))
    return render_template("cases/new.html", form=form, step=step, **_render_kw)


def _save_wizard(form, complete=False):
    needs_station = current_user.role in ("admin", "super_admin")
    station_id = form.station_id.data if needs_station else current_user.station_id
    if not station_id:
        form.station_id.errors = list(form.station_id.errors) + ["Choose a station."]
        return None
    incident = parse_local_dt(form.incident_at.data)
    if incident is None:
        form.incident_at.errors = list(form.incident_at.errors) + ["Enter a valid incident time."]
        return None
    year = form.year.data or incident.year
    cr = (form.cr_number.data or "").strip() or None
    existing = None
    if form.case_uuid.data:
        existing = get_by_uuid(current_user, form.case_uuid.data)
        if existing:
            require_case(current_user, existing, "edit")
    if cr_taken(station_id, year, cr, exclude_id=existing.id if existing else None):
        form.cr_number.errors = list(form.cr_number.errors) + [
            "This CR number already exists for the station and year."
        ]
        return None
    io_id = form.assigned_io_id.data or None
    if io_id == 0:
        io_id = None
    if existing:
        case = existing
    else:
        case = Case(
            station_id=station_id,
            created_by_id=current_user.id,
            status="draft",
            incident_at=incident,
            place_of_occurrence=form.place_of_occurrence.data.strip(),
            year=year,
            category=form.category.data or "other",
        )
        db.session.add(case)
    case.year = year
    case.cr_number = cr
    case.gd_number = (form.gd_number.data or "").strip() or None
    case.incident_at = incident
    case.place_of_occurrence = form.place_of_occurrence.data.strip()
    case.category = form.category.data or "other"
    case.assigned_io_id = io_id
    case.narrative = form.narrative.data
    case.narrative_language = form.narrative_language.data or "en"
    if complete:
        case.status = "draft"
    db.session.commit()
    if form.complainant_name.data and form.complainant_name.data.strip():
        already = [p for p in case.live_parties("complainant")]
        if already:
            party = already[0]
        else:
            party = CaseParty(case_id=case.id, role="complainant")
            db.session.add(party)
        party.full_name = form.complainant_name.data.strip()
        party.guardian_name = (form.guardian_name.data or "").strip() or None
        party.relation = (form.relation.data or "").strip() or None
        party.age = form.age.data
        party.gender = form.gender.data or None
        party.address = (form.address.data or "").strip() or None
        party.phone = form.phone.data or None
        party.id_type = form.id_type.data or None
        party.id_number = (form.id_number.data or "").strip() or None
        db.session.commit()
        _audit("case.party_added" if not already else "case.party_updated", case, {"role": "complainant"})
    if not existing:
        _audit("case.created", case, {"draft": not complete})
    else:
        _audit("case.updated", case, {"wizard": True})
    rebuild_fts(case)
    return case


@cases_bp.route("/cases/<uuid>")
@login_required
def overview(uuid):
    case = _load_case(uuid, "view")
    from app.models.evidence import CaseDiaryEntry

    oldest = True
    if current_user.preferences:
        oldest = bool(current_user.preferences.diary_oldest_first)
    dq = case.diary_entries.order_by(
        CaseDiaryEntry.occurred_at.asc() if oldest else CaseDiaryEntry.occurred_at.desc()
    )
    from app.forms.admin_forms import EmptyAdminForm
    from app.models import CaseIntegration
    from app.services.entitlement_service import cctns_allowed

    last_ack = (
        CaseIntegration.query.filter_by(case_id=case.id, system="cctns")
        .order_by(CaseIntegration.created_at.desc())
        .first()
    )
    return render_template(
        "cases/overview.html",
        case=case,
        completeness=completeness(case),
        actions=next_actions(case),
        chain=progress_chain(case),
        docs=document_readiness(case),
        diary_lines=dq.limit(3).all(),
        can_edit=can_edit_case_facts(current_user, case) and not case.is_locked,
        can_lock=can_lock_case(current_user, case),
        can_delete=can_delete_case(current_user, case),
        can_cctns=cctns_allowed(current_user, case),
        last_ack=last_ack,
        cctns_form=EmptyAdminForm(),
    )


@cases_bp.route("/cases/<uuid>/integrations/cctns", methods=["POST"])
@login_required
def cctns_export(uuid):
    from app.forms.admin_forms import EmptyAdminForm
    from app.services.entitlement_service import cctns_allowed
    from app.services.integrations.cctns_mock import push_fir_summary

    case = _load_case(uuid, "view")
    if not cctns_allowed(current_user, case):
        abort(403)
    if not EmptyAdminForm().validate_on_submit():
        abort(400)
    result = push_fir_summary(case, current_user)
    _audit("case.cctns_demo", case, {"ack": result["ack_number"]})
    flash(translate("flash.cctns_demo", ack=result["ack_number"]), "info")
    return redirect(url_for("cases.overview", uuid=case.uuid))


@cases_bp.route("/cases/<uuid>/edit", methods=["GET", "POST"])
@login_required
def case_edit(uuid):
    case = get_by_uuid(current_user, uuid)
    if case is None:
        abort(404)
    if case.is_locked:
        if request.method == "POST":
            abort(403)
        return render_template("cases/edit.html", case=case, form=None, locked=True, diffs=None)
    require_case(current_user, case, "edit")
    form = CaseEditForm()
    form.assigned_io_id.choices = _io_choices(case.station_id)
    form.assigned_legal_id.choices = _legal_choices(case.station_id)
    form.assigned_io_id.coerce = _int0
    form.assigned_legal_id.coerce = _int0
    allowed_status = ["draft", "open"]
    if current_user.role in ("sho", "admin", "super_admin"):
        allowed_status = list(CASE_CATEGORIES) and ["draft", "open", "in_court", "closed", "archived"]
    form.status.choices = [(s, s.replace("_", " ")) for s in allowed_status]
    if request.method == "GET":
        form.year.data = case.year
        form.cr_number.data = case.cr_number
        form.gd_number.data = case.gd_number
        local = to_local_input(case.incident_at)
        form.incident_at.data = datetime.strptime(local, "%Y-%m-%dT%H:%M") if local else None
        form.place_of_occurrence.data = case.place_of_occurrence
        form.category.data = case.category
        form.assigned_io_id.data = case.assigned_io_id or 0
        form.assigned_legal_id.data = case.assigned_legal_id or 0
        form.narrative.data = case.narrative
        form.narrative_language.data = case.narrative_language or "en"
        form.status.data = case.status
        form.updated_at.data = case.updated_at.isoformat() if case.updated_at else ""
    if form.validate_on_submit():
        if not timestamps_match(case.updated_at, form.updated_at.data):
            incoming = {
                "cr_number": form.cr_number.data or "",
                "gd_number": form.gd_number.data or "",
                "place_of_occurrence": form.place_of_occurrence.data or "",
                "category": form.category.data or "",
                "narrative": form.narrative.data or "",
                "status": form.status.data or "",
                "year": str(form.year.data or ""),
            }
            return render_template(
                "cases/edit.html",
                case=case,
                form=form,
                locked=False,
                diffs=field_diff(case, incoming),
            )
        cr = (form.cr_number.data or "").strip() or None
        if cr_taken(case.station_id, form.year.data, cr, exclude_id=case.id):
            form.cr_number.errors = list(form.cr_number.errors) + [
                "This CR number already exists for the station and year."
            ]
        else:
            if form.status.data not in allowed_status:
                abort(403)
            case.year = form.year.data
            case.cr_number = cr
            case.gd_number = (form.gd_number.data or "").strip() or None
            case.incident_at = parse_local_dt(form.incident_at.data)
            case.place_of_occurrence = form.place_of_occurrence.data.strip()
            case.category = form.category.data
            case.assigned_io_id = form.assigned_io_id.data or None
            if case.assigned_io_id == 0:
                case.assigned_io_id = None
            if current_user.role in ("sho", "admin", "super_admin"):
                lid = form.assigned_legal_id.data or None
                case.assigned_legal_id = None if lid == 0 else lid
            case.narrative = form.narrative.data
            case.narrative_language = form.narrative_language.data
            case.status = form.status.data
            db.session.commit()
            _audit("case.updated", case, {"fields": ["identity", "narrative"]})
            rebuild_fts(case)
            flash(translate("flash.pool_saved"), "success")
            return redirect(url_for("cases.overview", uuid=case.uuid))
    return render_template("cases/edit.html", case=case, form=form, locked=False, diffs=None)


@cases_bp.route("/cases/<uuid>/lock", methods=["POST"])
@login_required
def case_lock(uuid):
    case = _load_case(uuid, "lock")
    case.is_locked = True
    case.locked_by_id = current_user.id
    case.locked_at = utcnow()
    db.session.commit()
    _audit("case.locked", case)
    flash(translate("flash.case_locked"), "info")
    return redirect(url_for("cases.overview", uuid=case.uuid))


@cases_bp.route("/cases/<uuid>/unlock", methods=["POST"])
@login_required
def case_unlock(uuid):
    case = _load_case(uuid, "lock")
    case.is_locked = False
    case.locked_by_id = None
    case.locked_at = None
    db.session.commit()
    _audit("case.unlocked", case)
    flash(translate("flash.case_unlocked"), "info")
    return redirect(url_for("cases.overview", uuid=case.uuid))


@cases_bp.route("/cases/<uuid>/delete", methods=["POST"])
@login_required
def case_delete(uuid):
    case = _load_case(uuid, "delete")
    case.deleted_at = utcnow()
    db.session.commit()
    _audit("case.deleted", case)
    flash(translate("flash.case_deleted"), "info")
    return redirect(url_for("cases.case_list"))


@cases_bp.route("/cases/<uuid>/parties")
@login_required
def parties(uuid):
    case = _load_case(uuid, "view")
    role = request.args.get("role") or ""
    rows = case.live_parties(role) if role else case.live_parties()
    return render_template("cases/parties.html", case=case, parties=rows, role=role)


@cases_bp.route("/cases/<uuid>/parties/new", methods=["GET", "POST"])
@login_required
def party_new(uuid):
    case = _load_case(uuid, "edit")
    form = PartyForm()
    if form.validate_on_submit():
        party = CaseParty(case_id=case.id)
        _apply_party(party, form)
        db.session.add(party)
        db.session.commit()
        _audit("case.party_added", case, {"role": party.role})
        rebuild_fts(case)
        flash(translate("flash.pool_saved"), "success")
        return redirect(url_for("cases.parties", uuid=case.uuid))
    return render_template("cases/party_form.html", case=case, form=form, party=None)


@cases_bp.route("/cases/<uuid>/parties/<pid>/edit", methods=["GET", "POST"])
@login_required
def party_edit(uuid, pid):
    case = _load_case(uuid, "edit")
    party = CaseParty.query.filter_by(uuid=pid, case_id=case.id, deleted_at=None).first()
    if party is None:
        abort(404)
    form = PartyForm(obj=party)
    if form.validate_on_submit():
        _apply_party(party, form)
        db.session.commit()
        _audit("case.party_updated", case, {"role": party.role})
        rebuild_fts(case)
        flash(translate("flash.pool_saved"), "success")
        return redirect(url_for("cases.parties", uuid=case.uuid))
    return render_template("cases/party_form.html", case=case, form=form, party=party)


@cases_bp.route("/cases/<uuid>/parties/<pid>/delete", methods=["POST"])
@login_required
def party_delete(uuid, pid):
    case = _load_case(uuid, "edit")
    party = CaseParty.query.filter_by(uuid=pid, case_id=case.id, deleted_at=None).first()
    if party is None:
        abort(404)
    party.deleted_at = utcnow()
    db.session.commit()
    _audit("case.party_deleted", case, {"role": party.role})
    rebuild_fts(case)
    flash(translate("flash.pool_saved"), "success")
    return redirect(url_for("cases.parties", uuid=case.uuid))


def _apply_party(party, form):
    party.role = form.role.data
    party.full_name = form.full_name.data.strip()
    party.guardian_name = (form.guardian_name.data or "").strip() or None
    party.relation = (form.relation.data or "").strip() or None
    party.age = form.age.data
    party.gender = form.gender.data or None
    party.address = (form.address.data or "").strip() or None
    party.phone = form.phone.data or None
    party.id_type = form.id_type.data or None
    party.id_number = (form.id_number.data or "").strip() or None
    party.alias = (form.alias.data or "").strip() or None
    party.is_juvenile = bool(form.is_juvenile.data)
    party.notes = (form.notes.data or "").strip() or None


@cases_bp.route("/cases/<uuid>/items")
@login_required
def items(uuid):
    case = _load_case(uuid, "view")
    return render_template("cases/items.html", case=case, items=case.live_items())


@cases_bp.route("/cases/<uuid>/items/new", methods=["GET", "POST"])
@login_required
def item_new(uuid):
    case = _load_case(uuid, "edit")
    form = ItemForm()
    form.seized_from_party_id.choices = _party_choices(case)
    form.seized_from_party_id.coerce = _int0
    if form.validate_on_submit():
        item = CaseItem(case_id=case.id)
        _apply_item(item, form)
        db.session.add(item)
        db.session.commit()
        _audit("case.item_added", case)
        rebuild_fts(case)
        flash(translate("flash.pool_saved"), "success")
        return redirect(url_for("cases.items", uuid=case.uuid))
    return render_template("cases/item_form.html", case=case, form=form, item=None)


@cases_bp.route("/cases/<uuid>/items/<iid>/edit", methods=["GET", "POST"])
@login_required
def item_edit(uuid, iid):
    case = _load_case(uuid, "edit")
    item = CaseItem.query.filter_by(uuid=iid, case_id=case.id, deleted_at=None).first()
    if item is None:
        abort(404)
    form = ItemForm(obj=item)
    form.seized_from_party_id.choices = _party_choices(case)
    form.seized_from_party_id.coerce = _int0
    if request.method == "GET":
        form.seized_from_party_id.data = item.seized_from_party_id or 0
        form.estimated_value.data = str(item.estimated_value) if item.estimated_value is not None else ""
        if item.seized_at:
            form.seized_at.data = parse_local_dt(to_local_input(item.seized_at))
    if form.validate_on_submit():
        _apply_item(item, form)
        db.session.commit()
        _audit("case.item_updated", case)
        rebuild_fts(case)
        flash(translate("flash.pool_saved"), "success")
        return redirect(url_for("cases.items", uuid=case.uuid))
    return render_template("cases/item_form.html", case=case, form=form, item=item)


@cases_bp.route("/cases/<uuid>/items/<iid>/delete", methods=["POST"])
@login_required
def item_delete(uuid, iid):
    case = _load_case(uuid, "edit")
    item = CaseItem.query.filter_by(uuid=iid, case_id=case.id, deleted_at=None).first()
    if item is None:
        abort(404)
    item.deleted_at = utcnow()
    db.session.commit()
    _audit("case.item_deleted", case)
    rebuild_fts(case)
    flash(translate("flash.pool_saved"), "success")
    return redirect(url_for("cases.items", uuid=case.uuid))


def _apply_item(item, form):
    item.description = form.description.data.strip()
    item.quantity = (form.quantity.data or "").strip() or None
    item.unit = (form.unit.data or "").strip() or None
    raw = (form.estimated_value.data or "").strip()
    if raw:
        try:
            item.estimated_value = Decimal(raw)
        except InvalidOperation:
            item.estimated_value = None
    else:
        item.estimated_value = None
    item.serial_or_marking = (form.serial_or_marking.data or "").strip() or None
    sid = form.seized_from_party_id.data or 0
    item.seized_from_party_id = None if sid == 0 else sid
    item.place = (form.place.data or "").strip() or None
    item.seized_at = parse_local_dt(form.seized_at.data) if form.seized_at.data else None
    item.exhibit_no = (form.exhibit_no.data or "").strip() or None
    item.notes = (form.notes.data or "").strip() or None


@cases_bp.route("/cases/<uuid>/arrests", methods=["GET", "POST"])
@login_required
def arrests(uuid):
    if request.method == "POST":
        case = _load_case(uuid, "edit")
        accused_id = _int0(request.form.get("accused_id"))
        accused = CaseParty.query.filter_by(id=accused_id, case_id=case.id, deleted_at=None).first()
        if accused is None or accused.role != "accused":
            abort(404)
        arrest = CaseArrest.query.filter_by(
            case_id=case.id, accused_id=accused.id, deleted_at=None
        ).first()
        if arrest is None:
            arrest = CaseArrest(case_id=case.id, accused_id=accused.id, arrest_at=utcnow(), place="")
            db.session.add(arrest)
        at = parse_local_dt(request.form.get("arrest_at"))
        if at:
            arrest.arrest_at = at
        arrest.place = (request.form.get("place") or "").strip()
        arrest.rights_informed = request.form.get("rights_informed") == "y"
        arrest.grounds_brief = (request.form.get("grounds_brief") or "").strip() or None
        arrest.produced_before = (request.form.get("produced_before") or "").strip() or None
        arrest.relative_informed = request.form.get("relative_informed") == "y"
        arrest.relative_name = (request.form.get("relative_name") or "").strip() or None
        incident = case.incident_at
        if incident and incident.tzinfo is None:
            incident = incident.replace(tzinfo=timezone.utc)
        warn = at and incident and at < incident
        db.session.commit()
        _audit("case.arrest_updated", case, {"accused_id": accused.id})
        if warn:
            flash(translate("flash.arrest_before_incident"), "warning")
        else:
            flash(translate("flash.pool_saved"), "success")
        return redirect(url_for("cases.arrests", uuid=case.uuid))
    case = _load_case(uuid, "view")
    accused = case.live_parties("accused")
    existing = {a.accused_id: a for a in case.live_arrests()}
    return render_template(
        "cases/arrests.html",
        case=case,
        accused=accused,
        arrests=existing,
        can_edit=can_edit_case_facts(current_user, case) and not case.is_locked,
        to_local=to_local_input,
    )


@cases_bp.route("/cases/<uuid>/medical", methods=["GET", "POST"])
@login_required
def medical(uuid):
    if request.method == "POST":
        case = _load_case(uuid, "edit")
        form = MedicalForm()
        injured = [(0, "-")] + [
            (p.id, p.full_name) for p in case.live_parties() if p.role in ("complainant", "injured")
        ]
        form.injured_party_id.choices = injured
        form.escorting_officer_id.choices = [(0, "-")] + [
            (u.id, u.full_name) for u in station_user_choices(case.station_id)
        ]
        form.injured_party_id.coerce = _int0
        form.escorting_officer_id.coerce = _int0
        if form.validate_on_submit():
            row = case.medical or CaseMedical(case_id=case.id)
            if case.medical is None:
                db.session.add(row)
            row.injured_party_id = form.injured_party_id.data or None
            if row.injured_party_id == 0:
                row.injured_party_id = None
            row.hospital_name = (form.hospital_name.data or "").strip() or None
            row.department = (form.department.data or "").strip() or None
            row.mlc_no = (form.mlc_no.data or "").strip() or None
            row.history_reported = (form.history_reported.data or "").strip() or None
            row.requested_exam = (form.requested_exam.data or "").strip() or None
            eid = form.escorting_officer_id.data or 0
            row.escorting_officer_id = None if eid == 0 else eid
            db.session.commit()
            _audit("case.medical_updated", case)
            flash(translate("flash.pool_saved"), "success")
            return redirect(url_for("cases.medical", uuid=case.uuid))
        return render_template("cases/medical.html", case=case, form=form, can_edit=True)
    case = _load_case(uuid, "view")
    form = MedicalForm(obj=case.medical) if case.medical else MedicalForm()
    form.injured_party_id.choices = [(0, "-")] + [
        (p.id, p.full_name) for p in case.live_parties() if p.role in ("complainant", "injured")
    ]
    form.escorting_officer_id.choices = [(0, "-")] + [
        (u.id, u.full_name) for u in station_user_choices(case.station_id)
    ]
    if case.medical:
        form.injured_party_id.data = case.medical.injured_party_id or 0
        form.escorting_officer_id.data = case.medical.escorting_officer_id or 0
    return render_template(
        "cases/medical.html",
        case=case,
        form=form,
        can_edit=can_edit_case_facts(current_user, case) and not case.is_locked,
    )


@cases_bp.route("/cases/<uuid>/sections")
@login_required
def sections(uuid):
    case = _load_case(uuid, "view")
    add_form = SectionManualForm()
    remove_form = SectionRemoveForm()
    rows = case.sections.order_by(CaseSection.created_at.desc()).all()
    from app.forms.tool_forms import SuggestIntelForm
    from app.services.intel_service import last_run_for_case, parsed_result, quota_reached

    suggest_form = SuggestIntelForm()
    suggest_form.use_search.data = True
    last = last_run_for_case(case)
    return render_template(
        "cases/sections.html",
        case=case,
        sections=rows,
        add_form=add_form,
        remove_form=remove_form,
        suggest_form=suggest_form,
        last_run=last,
        last_data=parsed_result(last) if last else None,
        can_edit=can_edit_case_facts(current_user, case) and not case.is_locked,
        can_confirm=can_confirm_sections(current_user, case) and not case.is_locked,
        can_intel=can_run_legal_intel(current_user, require_key=False),
        gemini_ok=gemini_ready(),
        quota=quota_reached(current_user, case),
        narrative_ready=len((case.narrative or "").strip()) >= 50,
        show_modal=not (current_user.preferences and current_user.preferences.hide_intel_modal),
    )


@cases_bp.route("/cases/<uuid>/sections/suggest", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def section_suggest(uuid):
    from app.forms.tool_forms import SuggestIntelForm
    from app.services.intel_service import enqueue_legal_intel

    case = _load_case(uuid, "view")
    if not can_run_legal_intel(current_user, require_key=False):
        abort(403)
    if not current_user.disclaimer_accepted_at:
        flash(translate("flash.need_disclaimer"), "danger")
        return redirect(url_for("cases.sections", uuid=case.uuid))
    if not gemini_ready():
        flash(translate("intel.missing_key"), "danger")
        return redirect(url_for("cases.sections", uuid=case.uuid))
    if len((case.narrative or "").strip()) < 50:
        flash(translate("intel.narrative_short"), "warning")
        return redirect(url_for("cases.case_edit", uuid=case.uuid))
    form = SuggestIntelForm()
    if not form.validate_on_submit():
        flash(translate("form.fix"), "danger")
        return redirect(url_for("cases.sections", uuid=case.uuid))
    if form.hide_again.data in ("y", "1", "true", "on") and current_user.preferences:
        current_user.preferences.hide_intel_modal = True
        db.session.commit()
    try:
        job, _ = enqueue_legal_intel(
            current_user,
            case.narrative,
            language=case.narrative_language or "en",
            focus=form.focus.data,
            use_search=bool(form.use_search.data),
            case=case,
        )
    except RuntimeError as exc:
        flash(translate("intel.quota") if str(exc) == "quota" else translate("intel.missing_key"), "warning")
        return redirect(url_for("cases.sections", uuid=case.uuid))
    return redirect(url_for("jobs.progress", job_uuid=job.uuid))


@cases_bp.route("/cases/<uuid>/sections/apply", methods=["POST"])
@login_required
def section_apply(uuid):
    from app.models.ai import LegalSuggestion
    from app.services.intel_service import apply_selected, can_view_suggestion

    case = _load_case(uuid, "view")
    if current_user.role == "writer":
        abort(403)
    sid = request.form.get("suggestion_id")
    sugg = LegalSuggestion.query.filter_by(uuid=sid, case_id=case.id).first() if sid else None
    if sugg is None or not can_view_suggestion(current_user, sugg):
        abort(404)
    try:
        applied, already = apply_selected(current_user, sugg, request.form.getlist("selected"))
    except PermissionError:
        abort(403)
    except RuntimeError:
        abort(403)
    if applied:
        flash(translate("flash.intel_applied", n=applied), "success")
    if already:
        flash(translate("flash.section_dup"), "warning")
    return redirect(url_for("cases.sections", uuid=case.uuid))


@cases_bp.route("/cases/<uuid>/sections/manual", methods=["POST"])
@login_required
def section_manual(uuid):
    case = _load_case(uuid, "edit")
    form = SectionManualForm()
    if not form.validate_on_submit():
        flash(translate("form.fix"), "danger")
        return redirect(url_for("cases.sections", uuid=case.uuid))
    code = form.code.data.strip()
    family = form.statute_family.data
    confirm = can_confirm_sections(current_user, case)
    if confirm:
        dup = CaseSection.query.filter_by(
            case_id=case.id, statute_family=family, code=code, status="confirmed"
        ).first()
        if dup:
            flash(translate("flash.section_dup"), "warning")
            return redirect(url_for("cases.sections", uuid=case.uuid))
    row = CaseSection(
        case_id=case.id,
        statute_family=family,
        code=code,
        title=(form.title.data or "").strip() or None,
        rationale=(form.rationale.data or "").strip() or None,
        source="legal" if current_user.role == "legal" else "officer",
        status="confirmed" if confirm else "suggested",
    )
    if confirm:
        row.confirmed_by_id = current_user.id
        row.confirmed_at = utcnow()
    db.session.add(row)
    db.session.commit()
    _audit(
        "section.added",
        case,
        {"code": code, "override": current_user.role == "super_admin"},
    )
    if confirm:
        flash(translate("flash.section_confirmed"), "success")
    else:
        flash(translate("flash.section_needs_io"), "info")
    return redirect(url_for("cases.sections", uuid=case.uuid))


@cases_bp.route("/cases/<uuid>/sections/<sid>/confirm", methods=["POST"])
@login_required
def section_confirm(uuid, sid):
    case = _load_case(uuid, "confirm")
    row = CaseSection.query.filter_by(uuid=sid, case_id=case.id).first()
    if row is None:
        abort(404)
    dup = CaseSection.query.filter(
        CaseSection.case_id == case.id,
        CaseSection.statute_family == row.statute_family,
        CaseSection.code == row.code,
        CaseSection.status == "confirmed",
        CaseSection.id != row.id,
    ).first()
    if dup:
        flash(translate("flash.section_dup"), "warning")
        return redirect(url_for("cases.sections", uuid=case.uuid))
    row.status = "confirmed"
    row.confirmed_by_id = current_user.id
    row.confirmed_at = utcnow()
    db.session.commit()
    _audit(
        "section.confirmed",
        case,
        {"code": row.code, "override": current_user.role == "super_admin"},
    )
    flash(translate("flash.section_confirmed"), "success")
    return redirect(url_for("cases.sections", uuid=case.uuid))


@cases_bp.route("/cases/<uuid>/sections/<sid>/remove", methods=["POST"])
@login_required
def section_remove(uuid, sid):
    case = _load_case(uuid, "confirm")
    row = CaseSection.query.filter_by(uuid=sid, case_id=case.id).first()
    if row is None:
        abort(404)
    form = SectionRemoveForm()
    if not form.validate_on_submit():
        flash(translate("flash.section_reason"), "danger")
        return redirect(url_for("cases.sections", uuid=case.uuid))
    db.session.delete(row)
    db.session.commit()
    _audit("section.removed", case, {"code": row.code, "reason": True})
    flash(translate("flash.section_removed"), "info")
    return redirect(url_for("cases.sections", uuid=case.uuid))
