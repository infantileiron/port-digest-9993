"""应到清单与到发台账的对账。

口径：
- 清单按港站 + 上海计划日出具，版本不可变；换版产生新版本并把旧核对置为失效。
- 台账按计划到发时间的上海自然日归档，跨午夜仍归原计划日。
- 三类差异：缺录（清单有、台账无）、未到发（两边都有但实际为空）、
  计划外（台账有、清单无）。三类均为 0 且总数相等才可放行。
"""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.constants.enums import RECONCILIATION_VERSION, STATIONS
from src.models.entities import (
    Arrival,
    DayLock,
    DistributionGate,
    Manifest,
    Receipt,
    Reconciliation,
    Subscription,
)
from src.utils.time import SH, aware, now_utc


def planned_day(value):
    return aware(value).astimezone(SH).date().isoformat()


def ledger_rows(s, station, day):
    rows = s.query(Arrival).filter(Arrival.station == station).all()
    return sorted(
        [r for r in rows if planned_day(r.planned_at) == day],
        key=lambda r: r.code,
    )


def ledger_checksum(rows):
    data = [
        {
            "code": r.code,
            "station": r.station,
            "planned_at": r.planned_at,
            "actual_at": r.actual_at,
            "note": r.note or "",
            "revision": r.revision or 0,
        }
        for r in rows
    ]
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def manifest_checksum(codes):
    return hashlib.sha256(
        json.dumps(sorted(codes), ensure_ascii=False).encode()
    ).hexdigest()


def latest_manifest(s, station, day):
    return (
        s.query(Manifest)
        .filter_by(station=station, report_day=day)
        .order_by(Manifest.version.desc())
        .first()
    )


def lock_day(s, station, day):
    """日锁把清单换版、台账修订、核对、分发串行化到同一站日。"""
    try:
        with s.begin_nested():
            s.add(DayLock(station=station, report_day=day))
            s.flush()
    except IntegrityError:
        pass
    return (
        s.query(DayLock)
        .filter_by(station=station, report_day=day)
        .with_for_update()
        .one()
    )


def lock_days(s, stations, day):
    for station in sorted(set(stations), key=STATIONS.index):
        lock_day(s, station, day)


def classify(manifest, rows):
    codes = list(manifest.items or [])
    wanted = set(codes)
    by_code = {r.code: r for r in rows}
    missing = [
        {
            "category": "missing",
            "code": code,
            "station": manifest.station,
            "reason": "清单有、台账无（漏录）",
        }
        for code in sorted(wanted)
        if code not in by_code
    ]
    pending = [
        {
            "category": "pending",
            "code": r.code,
            "station": r.station,
            "arrival_id": r.id,
            "planned_at": r.planned_at,
            "actual_at": None,
            "reason": "已录计划、尚无实际到发",
        }
        for r in rows
        if r.code in wanted and r.actual_at is None
    ]
    completed = [r for r in rows if r.code in wanted and r.actual_at is not None]
    unplanned = [
        {
            "category": "unplanned",
            "code": r.code,
            "station": r.station,
            "arrival_id": r.id,
            "planned_at": r.planned_at,
            "actual_at": r.actual_at,
            "reason": "台账有、清单无（计划外）",
        }
        for r in rows
        if r.code not in wanted
    ]
    matched = len(completed) + len(pending)
    return {
        "manifest_total": len(codes),
        "ledger_total": len(rows),
        "matched": matched,
        "completed": len(completed),
        "pending": len(pending),
        "missing": len(missing),
        "unplanned": len(unplanned),
        "balanced": len(missing) == 0
        and len(pending) == 0
        and len(unplanned) == 0
        and len(codes) == len(rows),
        "blocking": sorted(
            missing + pending + unplanned,
            key=lambda x: (x["category"], x["code"]),
        ),
    }


def station_basis(manifest, reconciliation):
    if not manifest:
        return None
    basis = {
        "station": manifest.station,
        "manifest_id": manifest.id,
        "manifest_version": manifest.version,
        "manifest_checksum": manifest.checksum,
        "manifest_total": manifest.item_count,
    }
    if reconciliation:
        basis.update(
            {
                "reconciliation_id": reconciliation.id,
                "status": reconciliation.status,
                "ledger_checksum": reconciliation.ledger_checksum,
                "ledger_total": reconciliation.ledger_total,
                "checked_by": reconciliation.checked_by,
                "checked_at": reconciliation.checked_at,
                "counts": {
                    "manifest_total": reconciliation.manifest_total,
                    "ledger_total": reconciliation.ledger_total,
                    "matched": reconciliation.matched,
                    "completed": reconciliation.completed,
                    "pending": reconciliation.pending,
                    "missing": reconciliation.missing,
                    "unplanned": reconciliation.unplanned,
                },
            }
        )
    return basis


def evaluate_station(s, station, day):
    manifest = latest_manifest(s, station, day)
    if not manifest:
        return {
            "station": station,
            "state": "waiting",
            "ready": False,
            "manifest": None,
            "reconciliation": None,
            "counts": None,
            "blocking": [],
            "reason": "缺少应到清单",
        }
    all_checks = (
        s.query(Reconciliation)
        .filter_by(station=station, report_day=day, manifest_id=manifest.id)
        .order_by(Reconciliation.id.desc())
        .all()
    )
    reconciliation = next(
        (r for r in all_checks if r.invalidated_at is None), None
    )
    invalidated = all_checks[0] if all_checks and reconciliation is None else None
    rows = ledger_rows(s, station, day)
    current = classify(manifest, rows)
    base = {
        "station": station,
        "manifest": station_basis(manifest, reconciliation),
        "reconciliation": reconciliation.id if reconciliation else None,
    }
    if not reconciliation:
        base.update(
            {
                "state": "waiting",
                "ready": False,
                "counts": current,
                "blocking": current["blocking"],
                "reason": (
                    "旧核对失效：" + (invalidated.invalid_reason or "需重新核对")
                    if invalidated
                    else "清单待核对"
                ),
                "invalidated_reconciliation": invalidated.id
                if invalidated
                else None,
            }
        )
        return base
    if reconciliation.manifest_checksum != manifest.checksum:
        base.update(
            {
                "state": "waiting",
                "ready": False,
                "counts": current,
                "blocking": current["blocking"],
                "reason": "清单已换版，旧核对失效",
            }
        )
        return base
    if reconciliation.ledger_checksum != ledger_checksum(rows):
        base.update(
            {
                "state": "waiting",
                "ready": False,
                "counts": current,
                "blocking": current["blocking"],
                "reason": "台账在核对后有修订，旧核对失效",
            }
        )
        return base
    if not reconciliation.balanced:
        details = reconciliation.details or {}
        base.update(
            {
                "state": "blocked",
                "ready": False,
                "counts": current,
                "blocking": details.get("blocking", current["blocking"]),
                "reason": "存在缺录/未到发/计划外差异",
            }
        )
        return base
    if len(current["blocking"]) != 0:
        # 校验和相同但分类结果有差异只可能来自实现漂移，宁可等待也不放行。
        base.update(
            {
                "state": "waiting",
                "ready": False,
                "counts": current,
                "blocking": current["blocking"],
                "reason": "台账与核对快照不一致",
            }
        )
        return base
    base.update(
        {
            "state": "ready",
            "ready": True,
            "counts": current,
            "blocking": [],
            "reason": "清单与台账一致",
        }
    )
    return base


def evaluate_subscription(s, sub, day):
    stations = list(STATIONS) if sub.station == "全部" else [sub.station]
    parts = [evaluate_station(s, station, day) for station in stations]
    receipt = (
        s.query(Receipt)
        .filter_by(subscription_id=sub.id, report_day=day)
        .first()
    )
    blocking = []
    for part in parts:
        for item in part["blocking"]:
            blocking.append(dict(item))
    reasons = []
    for part in parts:
        reason = part["reason"]
        if reason not in reasons:
            reasons.append(reason)
    if receipt:
        state = "sent"
    elif not sub.enabled:
        state = "paused"
    elif all(part["ready"] for part in parts):
        state = "ready"
    elif any(part["state"] == "blocked" for part in parts):
        state = "blocked"
    else:
        state = "waiting"
    return {
        "subscription_id": sub.id,
        "name": sub.name,
        "station": sub.station,
        "report_day": day,
        "recipient": sub.recipient,
        "state": state,
        "ready": state == "ready",
        "reason": "已入箱，保留入箱时核对依据"
        if state == "sent"
        else "全站清单齐备"
        if state == "ready"
        else "订阅已暂停，到点不执行"
        if state == "paused"
        else "；".join(reasons),
        "stations": parts,
        "blocking": blocking,
        "receipt_id": receipt.id if receipt else None,
        "checked_at": now_utc().isoformat(),
    }


def invalidate_station(s, station, day, reason, when=None):
    when = when or now_utc().isoformat()
    for old in (
        s.query(Reconciliation)
        .filter_by(station=station, report_day=day, invalidated_at=None)
        .all()
    ):
        old.invalidated_at = when
        old.invalid_reason = reason
    manifest = latest_manifest(s, station, day)
    if manifest and manifest.status != "superseded":
        manifest.status = "pending"
    for gate in s.query(DistributionGate).filter_by(report_day=day).all():
        sub = s.get(Subscription, gate.subscription_id)
        if not sub or (sub.station != "全部" and sub.station != station):
            continue
        if gate.state in ("ready", "blocked", "waiting"):
            gate.state = "waiting"
            gate.reason = reason
            gate.updated_at = when


def reconcile_manifest(s, manifest_id, actor):
    manifest = s.get(Manifest, manifest_id)
    if not manifest:
        raise HTTPException(404, "应到清单不存在")
    day, station = manifest.report_day, manifest.station
    lock_day(s, station, day)
    latest = latest_manifest(s, station, day)
    if not latest or latest.id != manifest.id:
        raise HTTPException(409, "该清单已被新版本替换，请核对最新版")
    rows = ledger_rows(s, station, day)
    result = classify(manifest, rows)
    when = now_utc().isoformat()
    for old in (
        s.query(Reconciliation)
        .filter_by(station=station, report_day=day, invalidated_at=None)
        .all()
    ):
        old.invalidated_at = when
        old.invalid_reason = "重新核对"
    reconciliation = Reconciliation(
        manifest_id=manifest.id,
        station=station,
        report_day=day,
        manifest_version=manifest.version,
        status="ready" if result["balanced"] else "blocked",
        manifest_checksum=manifest.checksum,
        ledger_checksum=ledger_checksum(rows),
        manifest_total=result["manifest_total"],
        ledger_total=result["ledger_total"],
        matched=result["matched"],
        completed=result["completed"],
        pending=result["pending"],
        missing=result["missing"],
        unplanned=result["unplanned"],
        balanced=result["balanced"],
        details={
            "version": RECONCILIATION_VERSION,
            "blocking": result["blocking"],
        },
        checked_by=actor,
        checked_at=when,
    )
    s.add(reconciliation)
    manifest.status = reconciliation.status
    manifest.reconciled_at = when
    s.flush()
    return manifest, reconciliation, result


def issue_manifest(s, data, actor):
    station = data.station
    day = data.report_day.isoformat()
    codes = data.codes
    lock_day(s, station, day)
    latest = latest_manifest(s, station, day)
    checksum = manifest_checksum(codes)
    if latest and latest.checksum == checksum:
        return latest, False
    version = (latest.version + 1) if latest else 1
    when = now_utc().isoformat()
    for old in (
        s.query(Reconciliation)
        .filter_by(station=station, report_day=day, invalidated_at=None)
        .all()
    ):
        old.invalidated_at = when
        old.invalid_reason = "清单换版"
    for old_manifest in (
        s.query(Manifest).filter_by(station=station, report_day=day).all()
    ):
        old_manifest.status = "superseded"
    manifest = Manifest(
        station=station,
        report_day=day,
        version=version,
        status="pending",
        items=sorted(codes),
        checksum=checksum,
        item_count=len(codes),
        note=data.note,
        created_by=actor,
        created_at=when,
    )
    s.add(manifest)
    s.flush()
    for gate in s.query(DistributionGate).filter_by(report_day=day).all():
        sub = s.get(Subscription, gate.subscription_id)
        if not sub or (sub.station != "全部" and sub.station != station):
            continue
        if gate.state in ("ready", "blocked", "waiting"):
            gate.state = "waiting"
            gate.reason = "清单已换版，需重新核对"
            gate.updated_at = when
    return manifest, True


def basis_for_receipt(parts, checked_at):
    return {
        "version": RECONCILIATION_VERSION,
        "policy": "按站日核对；缺录、未到发、计划外均为0且清单总数=台账总数才放行；分发时校验清单/台账校验和。",
        "checked_at": checked_at,
        "stations": [
            {
                "station": part["station"],
                "manifest_id": (part["manifest"] or {}).get("manifest_id"),
                "manifest_version": (part["manifest"] or {}).get("manifest_version"),
                "manifest_checksum": (part["manifest"] or {}).get(
                    "manifest_checksum"
                ),
                "reconciliation": (part["manifest"] or {}).get(
                    "reconciliation_id"
                ),
                "counts": (part["manifest"] or {}).get("counts"),
            }
            for part in parts
        ],
    }
