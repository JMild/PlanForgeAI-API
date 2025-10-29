# scheduler_refactored.py
# -------------------------------------------------------------
# GA + Local Search minimalist scheduler (no operators modeling)
# รวมแพตช์:
#  - กัน None ทุกชั้น (normalize chromosome + decode filter)
#  - แตกก้อนแบบฉลาด: ถ้ามีขั้นตอน Painting ใช้ max_batch (ลดจำนวนก้อนที่คอขวด)
#  - fail_stats: นับเหตุผลที่วางไม่ได้ (debug คอขวด/OT cap/slot)
#  - fallback horizon: ถ้า skipped ยังสูง ลองขยาย horizon +7 / +14 วันอัตโนมัติ
# -------------------------------------------------------------
from __future__ import annotations
import json, os, math, random, datetime as dt
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional
from copy import deepcopy
from collections import defaultdict

# ============================= Utilities =============================

def parse_datetime(s) -> dt.datetime:
    if isinstance(s, dt.datetime):
        return s
    if not s:
        raise ValueError("Empty datetime value")
    fmts = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]
    last_err = None
    for f in fmts:
        try:
            d = dt.datetime.strptime(str(s), f)
            if d.tzinfo:
                d = d.astimezone(dt.timezone.utc).replace(tzinfo=None)
            return d
        except Exception as e:
            last_err = e
            continue
    raise ValueError(f"Cannot parse datetime: {s!r}. Last error: {last_err}")

def timedelta_minutes(m: float) -> dt.timedelta:
    return dt.timedelta(seconds=float(m) * 60.0)

# ============================= Data Loading =============================

def load_data(json_path: str = "./mock_without_operator.json") -> Dict[str, Any]:
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    raise FileNotFoundError(f"Data file not found: {json_path}")

# ============================= Indexers & Context =============================

def index_products(products: List[Dict[str, Any]]):
    return {p['product_id']: p for p in products}

def index_routings(routings: List[Dict[str, Any]]):
    return {r['routing_id']: r for r in routings}

def index_work_centers(work_centers: List[Dict[str, Any]]):
    return {w['work_center_id']: w for w in work_centers}

def index_machines(machines: List[Dict[str, Any]]):
    by_id = {m['machine_id']: m for m in machines}
    by_wc: Dict[str, List[Dict[str, Any]]] = {}
    for m in machines:
        by_wc.setdefault(m['work_center_id'], []).append(m)
    return by_id, by_wc

def index_setup_mats(setup_matrices: List[Dict[str, Any]]):
    return {m['setup_matrix_id']: m for m in setup_matrices} if setup_matrices else {}

def collect_speed_overrides(d: Dict[str, Any]) -> List[Dict[str, Any]]:
    res = []
    if 'speed_overrides' in d and isinstance(d['speed_overrides'], list):
        res.extend(d['speed_overrides'])
    if 'speed' in d and isinstance(d['speed'], list):
        for s in d['speed']:
            kk = s.get('key') or s.get('keys')
            val = s.get('value') or s.get('multiplier')
            if kk is not None and val is not None:
                res.append({"key": kk, "multiplier": val})
    return res

@dataclass(frozen=True)
class Context:
    data: Dict[str, Any]
    setup_mats: Dict[str, Any]
    speed_overrides: List[Dict[str, Any]]
    idx_products: Dict[str, Any]
    idx_routings: Dict[str, Any]
    idx_wc: Dict[str, Any]
    idx_machines_by_id: Dict[str, Any]
    idx_machines_by_wc: Dict[str, List[Dict[str, Any]]]
    settings: Dict[str, Any]

    @staticmethod
    def from_data(data: Dict[str, Any]) -> "Context":
        setup_mats = index_setup_mats(data.get('setup_matrices', []))
        speed_overrides = collect_speed_overrides(data)
        idx_products_ = index_products(data.get('products', []))
        idx_routings_ = index_routings(data.get('routings', []))
        idx_wc_ = index_work_centers(data.get('work_centers', []))
        m_by_id, m_by_wc = index_machines(data.get('machines', []))
        return Context(
            data=data,
            setup_mats=setup_mats,
            speed_overrides=speed_overrides,
            idx_products=idx_products_,
            idx_routings=idx_routings_,
            idx_wc=idx_wc_,
            idx_machines_by_id=m_by_id,
            idx_machines_by_wc=m_by_wc,
            settings=data.get('settings', {}) or {}
        )

# ============================= Helpers: Product routing candidates =============================

def product_routing_candidates(ctx: Context, product_id: str) -> List[Dict[str, Any]]:
    p = ctx.idx_products.get(product_id)
    if not p:
        return []
    rids: List[str] = []
    if 'routing_ids' in p and isinstance(p['routing_ids'], list) and p['routing_ids']:
        rids = [rid for rid in p['routing_ids'] if rid in ctx.idx_routings]
    elif 'routing_id' in p and p['routing_id'] in ctx.idx_routings:
        rids = [p['routing_id']]
    return [ctx.idx_routings[rid] for rid in rids]

# ============================= Batch builder =============================

def _derive_batch_rule_for_product(ctx: Context, product_id: str, qty_total: int) -> Tuple[int, int]:
    p = ctx.idx_products.get(product_id) or {}
    lot_size = p.get('lot_size')
    if isinstance(lot_size, (int, float)) and lot_size > 0:
        ls = int(lot_size)
        return (ls, max(ls, ls * 5))
    cands = product_routing_candidates(ctx, product_id)
    if cands:
        for op in cands[0].get('operations', []):
            if op.get('batchable'):
                b = op.get('batch', {}) or {}
                mn = int(b.get('min_batch_qty', qty_total))
                mx = int(b.get('max_batch_qty', qty_total))
                mx = max(1, mx)
                return (mn, mx)
    return (qty_total, qty_total)

def _has_painting(ctx: Context, product_id: str) -> bool:
    cands = product_routing_candidates(ctx, product_id)
    if not cands:
        return False
    ops = cands[0].get('operations', []) or []
    return any((op.get('name') or '').lower() == 'painting' for op in ops)

def build_batches(ctx: Context, orders: List[Dict[str, Any]]):
    batches = []
    now = dt.datetime.now()

    for order in orders:
        order_due = parse_datetime(order['due_date'])
        order_rel = parse_datetime(order.get('release_date', now.strftime("%Y-%m-%d %H:%M")))
        order_pri = order.get('priority', 1)

        lines = order['lines'] if isinstance(order.get('lines'), list) else [{
            'product_id': order.get('product_id'),
            'quantity': order.get('quantity', 0),
            'priority': order_pri
        }]

        for idx_line, line in enumerate(lines, start=1):
            pid = line['product_id']
            qty_total = int(line['quantity'])
            if pid not in ctx.idx_products:
                continue

            min_batch, max_batch = _derive_batch_rule_for_product(ctx, pid, qty_total)
            prefer_max = _has_painting(ctx, pid)  # ✅ ถ้ามี Painting ให้ใช้ max_batch

            remaining = qty_total
            seq = 0
            while remaining > 0:
                take = min(remaining, (max_batch if prefer_max else min_batch))
                seq += 1
                batches.append({
                    "batch_id": f"B{order['order_id'][-3:]}{idx_line:02d}{seq:02d}",
                    "order_id": order['order_id'],
                    "product_id": pid,
                    "qty": take,
                    "priority": line.get('priority', order_pri),
                    "due_date": order_due,
                    "release_date": order_rel
                })
                remaining -= take
    return batches

# ============================= Time & Cost helpers =============================

def _lookup_matrix_setup_min(ctx: Context, prev_state: str, next_state: str, machine: Dict[str, Any], op: Dict[str, Any]) -> float:
    mat_id = machine.get('setup_matrix_id') or op.get('setup_matrix_id')
    if not mat_id:
        wc_id = op.get('work_center_id')
        wc = ctx.idx_wc.get(wc_id) if wc_id else None
        mat_id = wc.get('setup_matrix_id') if wc else None
    if mat_id and mat_id in ctx.setup_mats:
        mat_obj = ctx.setup_mats[mat_id]
        matrix = mat_obj.get('matrix', {})
        if prev_state in matrix and next_state in matrix[prev_state]:
            return float(matrix[prev_state][next_state])

    if 'setup_time_fixed_min' in op:
        return float(op['setup_time_fixed_min'])
    if 'setup_time_fixed' in op:
        return float(op['setup_time_fixed']) * 60.0

    if machine and 'default_setup_min' in machine:
        try:
            return float(machine['default_setup_min'])
        except Exception:
            pass
    wc = ctx.idx_wc.get(op.get('work_center_id')) if op.get('work_center_id') else None
    if wc and 'default_setup_min' in wc:
        try:
            return float(wc['default_setup_min'])
        except Exception:
            pass
    return 0.0

def _get_proc_time_min(ctx: Context, op: Dict[str, Any], qty: float, *, machine_id: Optional[str]=None, product_id: Optional[str]=None, machine_eff: float=1.0) -> float:
    if 'proc_time_per_unit_min' in op:
        per_unit_min = float(op['proc_time_per_unit_min'])
    elif 'proc_time_per_unit' in op:
        per_unit_min = float(op['proc_time_per_unit']) * 60.0
    else:
        per_unit_min = 0.0

    total_min = per_unit_min * float(qty)

    for so in ctx.speed_overrides:
        key = so.get('key', [])
        mult = so.get('multiplier', 1.0) or 1.0
        if not mult:
            continue
        if len(key) == 3:
            mk, pk, ok = key
            if (machine_id == mk) and (product_id == pk) and (op.get('name') == ok):
                total_min = total_min / mult
        elif len(key) == 2:
            mk, ok = key
            if (machine_id == mk) and (op.get('name') == ok):
                total_min = total_min / mult

    if machine_eff and machine_eff > 0:
        total_min = total_min / float(machine_eff)

    return total_min

# ============================= Interval & Window utils =============================

Interval = Tuple[dt.datetime, dt.datetime]
Window = Tuple[dt.datetime, dt.datetime, str]  # 'REG' | 'OT'

def _merge_intervals(intervals: List[Interval]) -> List[Interval]:
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged

def _subtract_intervals(base: List[Interval], subtracts: List[Interval]) -> List[Interval]:
    if not base:
        return []
    if not subtracts:
        return base[:]
    subtracts = _merge_intervals(subtracts)
    out: List[Interval] = []
    for bs, be in base:
        cur_segments = [(bs, be)]
        for ss, se in subtracts:
            next_segments: List[Interval] = []
            for cs, ce in cur_segments:
                if se <= cs or ss >= ce:
                    next_segments.append((cs, ce))
                else:
                    if ss > cs:
                        next_segments.append((cs, ss))
                    if se < ce:
                        next_segments.append((se, ce))
            cur_segments = next_segments
        out.extend(cur_segments)
    return [seg for seg in out if seg[1] > seg[0]]

# แทนของเดิม
def _time_on_date(date: dt.date, hhmm: str) -> dt.datetime:
    hh, mm = hhmm.split(":")
    hh = int(hh); mm = int(mm or 0)
    if hh == 24 and mm == 0:
        return dt.datetime(year=date.year, month=date.month, day=date.day) + dt.timedelta(days=1)
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"Invalid time: {hhmm}")
    return dt.datetime(year=date.year, month=date.month, day=date.day, hour=hh, minute=mm)

def _split_minutes_by_day(s: dt.datetime, e: dt.datetime) -> Dict[dt.date, float]:
    out: Dict[dt.date, float] = {}
    cur = s
    while cur < e:
        end_day = (cur.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1))
        seg_end = min(e, end_day)
        out.setdefault(cur.date(), 0.0)
        out[cur.date()] += (seg_end - cur).total_seconds() / 60.0
        cur = seg_end
    return out

# ============================= Windows (shifts/holidays/maintenance + OT) =============================

def build_shift_windows(ctx: Context, start_anchor: dt.datetime, days: int = 14) -> Dict[str, List[Window]]:
    data = ctx.data or {}
    cal = (data.get('calendar') or {})

    # --- normalize helpers ---
    def _normalize_breaks(bks):
        out = []
        if not bks:
            return out
        for br in bks:
            if isinstance(br, (list, tuple)) and len(br) == 2:
                out.append({'start': str(br[0]), 'end': str(br[1])})
            elif isinstance(br, dict) and 'start' in br and 'end' in br:
                out.append({'start': str(br['start']), 'end': str(br['end'])})
        return out

    global_breaks = _normalize_breaks(cal.get('breaks') or data.get('breaks'))

    # 1) เตรียม shifts: ใช้ data['shifts'] ถ้ามี; ถ้าไม่มีก็ลอง calendar.shifts
    raw_shifts = data.get('shifts') or []
    if not raw_shifts and isinstance(cal.get('shifts'), list):
        # map เป็นรูปแบบเดิม
        raw_shifts = [
            {
                'shift_id': s.get('shift_id') or s.get('id') or f"cal_{i+1}",
                'start_time': s.get('start') or s.get('start_time'),
                'end_time':   s.get('end')   or s.get('end_time'),
                # รองรับกรณีแนบ breaks ใน shift; รวมกับ global เสมอ
                'breaks': _normalize_breaks(s.get('breaks'))
            }
            for i, s in enumerate(cal['shifts'])
        ]

    shift_by = {s['shift_id']: s for s in raw_shifts}

    # 2) คำนวณช่วง REG ต่อ shift และหัก breaks (shift + global)
    reg_by_shift: Dict[str, List[Interval]] = {}
    for sid, s in shift_by.items():
        windows: List[Interval] = []
        shift_breaks = _normalize_breaks(s.get('breaks')) + global_breaks

        for d in range(days):
            base = (start_anchor.date() + dt.timedelta(days=d))
            st = _time_on_date(base, s['start_time'])
            en = _time_on_date(base, s['end_time'])
            if en <= st:
                en = en + dt.timedelta(days=1)

            day_windows = [(st, en)]

            # subtract ทุก break ของวันนั้น
            for br in (shift_breaks or []):
                brs = _time_on_date(base, br['start'])
                bre = _time_on_date(base, br['end'])
                if bre <= brs:
                    bre = bre + dt.timedelta(days=1)
                day_windows = _subtract_intervals(day_windows, [(brs, bre)])

            windows.extend(day_windows)

        reg_by_shift[sid] = _merge_intervals(windows)

    # 3) holidays (จาก calendar.holidays)
    holis = []
    for h in (cal.get('holidays') or []):
        try:
            d = dt.datetime.strptime(h, "%Y-%m-%d").date()
        except Exception:
            d = parse_datetime(h).date()
        holis.append(
            (dt.datetime(d.year, d.month, d.day),
             dt.datetime(d.year, d.month, d.day) + dt.timedelta(days=1))
        )

    # 4) map windows ต่อเครื่อง (รวมหลาย shift ของเครื่องเดียวกัน)
    machines_by_id = ctx.idx_machines_by_id
    reg_by_machine: Dict[str, List[Interval]] = {}
    for mid, m in machines_by_id.items():
        shift_ids = m.get('shifts', [])
        merged: List[Interval] = []
        for sid in shift_ids:
            merged.extend(reg_by_shift.get(sid, []))

        # ถ้าเครื่องไม่มี shift ให้ default เป็นทั้งช่วงวัน
        if not merged:
            start = start_anchor.replace(hour=0, minute=0, second=0, microsecond=0)
            merged = [(start, start + dt.timedelta(days=days))]

        merged = _merge_intervals(merged)
        merged = _subtract_intervals(merged, holis)

        # 5) maintenance ต่อเครื่อง
        maints: List[Interval] = []
        for mm in (cal.get('machine_maintenances') or []):
            if mm.get('machine_id') == mid:
                ms = parse_datetime(mm['start'])
                me = parse_datetime(mm['end'])
                if me > ms:
                    maints.append((ms, me))
        merged = _subtract_intervals(merged, maints)
        reg_by_machine[mid] = merged

    # 6) OT windows (global) ลบช่วง REG ออกให้เหลือเฉพาะส่วนที่เป็น OT
    raw_ots: List[Interval] = []
    for ow in (cal.get('ot_windows') or []):
        try:
            s = parse_datetime(ow['start'])
            e = parse_datetime(ow['end'])
        except Exception:
            continue
        if e > s:
            raw_ots.append((s, e))
    raw_ots = _merge_intervals(raw_ots)

    windows_by_machine: Dict[str, List[Window]] = {}
    for mid in machines_by_id.keys():
        reg = reg_by_machine.get(mid, [])
        ot_minus_reg: List[Interval] = []
        for (os_, oe_) in raw_ots:
            segs = _subtract_intervals([(os_, oe_)], reg)
            ot_minus_reg.extend(segs)
        ot_minus_reg = _merge_intervals(ot_minus_reg)

        windows: List[Window] = []
        for s_, e_ in reg:
            windows.append((s_, e_, "REG"))
        for s_, e_ in ot_minus_reg:
            windows.append((s_, e_, "OT"))
        windows.sort(key=lambda x: x[0])
        windows_by_machine[mid] = windows

    return windows_by_machine

# ============================= Packing helpers =============================

def _find_slot_contiguous(windows: List[Window], earliest: dt.datetime, need_min: float) -> Optional[Tuple[dt.datetime, dt.datetime]]:
    need = dt.timedelta(minutes=float(need_min))
    for ws, we, _kind in windows:
        s = max(ws, earliest)
        if we - s >= need:
            return (s, s + need)
    return None

def _pack_across_windows(windows: List[Window], earliest: dt.datetime, need_min: float, *,
                         setup_min: float = 0.0,
                         preemption_overhead_min: float = 0.0) -> Optional[Tuple[dt.datetime, dt.datetime, float, int, Dict[dt.date, float]]]:
    remaining = dt.timedelta(minutes=float(need_min))
    setup_td  = dt.timedelta(minutes=float(setup_min))
    ovh_td    = dt.timedelta(minutes=float(preemption_overhead_min))

    started: Optional[dt.datetime] = None
    cur_time = earliest
    total_ovh = dt.timedelta(0)
    num_splits = 0
    ot_minutes_by_day: Dict[dt.date, float] = {}

    for ws, we, kind in windows:
        s = max(ws, cur_time)
        if s >= we:
            continue

        if setup_td > dt.timedelta(0):
            if we - s >= setup_td:
                if started is None:
                    started = s
                s = s + setup_td
                remaining -= setup_td
                setup_td = dt.timedelta(0)
            else:
                continue

        if remaining <= dt.timedelta(0):
            break

        usable = we - s
        if usable <= dt.timedelta(0):
            continue

        use = min(usable, remaining)
        if kind == "OT":
            seg_s = s
            seg_e = s + use
            per_day = _split_minutes_by_day(seg_s, seg_e)
            for dkey, mins in per_day.items():
                ot_minutes_by_day[dkey] = ot_minutes_by_day.get(dkey, 0.0) + mins

        if started is None:
            started = s
        s = s + use
        remaining -= use

        if remaining > dt.timedelta(0):
            total_ovh += ovh_td
            num_splits += 1
            cur_time = we
        else:
            cur_time = s
            break

    if remaining > dt.timedelta(0) or started is None:
        return None
    return (started, cur_time + total_ovh, total_ovh.total_seconds()/60.0, num_splits, ot_minutes_by_day)

# ============================= Decode & Evaluate =============================

def _auto_horizon_days(chrom: List[Dict[str, Any]]) -> int:
    try:
        rel = min(b['release_date'] for b in chrom)
        due = max(b['due_date'] for b in chrom)
        span_days = max(1, (due - rel).days) + 3
        return max(7, min(span_days, 60))
    except Exception:
        return 14

def _schedule_once(ctx: Context, chrom: List[Dict[str, Any]], base_days: int, fail_stats: Dict[str, int]):
    schedule: List[Dict[str, Any]] = []
    skipped = 0

    machines_by_id = ctx.idx_machines_by_id
    machines_by_wc = ctx.idx_machines_by_wc
    wc_by_id = ctx.idx_wc

    earliest_release = min((b['release_date'] for b in chrom), default=dt.datetime.now())
    windows_by_machine = build_shift_windows(ctx, earliest_release, days=base_days)

    # OT cap
    ot_used: Dict[Tuple[str, dt.date], float] = {}
    cal = ctx.data.get("calendar", {}) or {}
    cap_hours = cal.get("ot_cap_hours_per_day", None)
    ot_cap_min: Optional[float] = None
    if cap_hours is not None:
        try:
            ot_cap_min = float(cap_hours) * 60.0
        except Exception:
            ot_cap_min = None

    # machine states
    machine_free: Dict[str, dt.datetime] = {m_id: earliest_release for m_id in machines_by_id.keys()}
    machine_state: Dict[str, str] = {m_id: machines_by_id[m_id].get('initial_state', 'clean') for m_id in machines_by_id.keys()}

    prefs = ctx.data.get("preference_settings", {}) or {}
    allow_preempt = bool(prefs.get("allow_job_preemption", True))

    def try_schedule_with_routing(batch: Dict[str, Any], routing: Dict[str, Any]):
        temp_free = deepcopy(machine_free)
        temp_state = deepcopy(machine_state)
        temp_ot_used = deepcopy(ot_used)
        steps: List[Dict[str, Any]] = []

        cur_start = max(batch['release_date'], earliest_release)

        for op in routing.get('operations', []) or []:
            wc_id = op['work_center_id']
            candidates = list(machines_by_wc.get(wc_id, []))
            if not candidates:
                wc = wc_by_id.get(wc_id)
                if wc:
                    ids = set(wc.get('parallel_machines', []))
                    candidates = [machines_by_id[mid] for mid in ids if mid in machines_by_id]
            if not candidates:
                fail_stats['no_machine_in_wc'] += 1
                return None  # infeasible

            best: Optional[Dict[str, Any]] = None
            saw_no_window = True
            saw_ot_cap = False
            saw_no_contig = False
            saw_pack_fail = False

            for mc in candidates:
                mid = mc['machine_id']
                est = max(cur_start, temp_free[mid])

                prev_state = temp_state.get(mid, mc.get('initial_state', 'clean'))
                next_state = op.get('setup_state_key', 'clean')
                setup_min  = _lookup_matrix_setup_min(ctx, prev_state, next_state, mc, op)
                machine_eff = float(mc.get('efficiency', 1.0) or 1.0)
                proc_min   = _get_proc_time_min(ctx, op, batch['qty'], machine_id=mid, product_id=batch['product_id'], machine_eff=machine_eff)
                need_min   = setup_min + proc_min

                wins = windows_by_machine.get(mid, [])
                wins_to_search: List[Window] = [(max(est, a), b, k) for (a, b, k) in wins if b > est]
                if wins_to_search:
                    saw_no_window = False

                is_preemptable = bool(op.get('preemptable', False)) and allow_preempt
                preempt_ovh    = float(op.get('preemption_overhead_min', 0.0) or 0.0)

                cand: Optional[Dict[str, Any]] = None
                ot_minutes_by_day: Dict[dt.date, float] = {}

                if not is_preemptable:
                    cont = _find_slot_contiguous(wins_to_search, est, need_min)
                    if cont:
                        st, fn = cont
                        ot_ok = True
                        for ws, we, kind in wins_to_search:
                            if kind != "OT":
                                continue
                            seg_s = max(ws, st)
                            seg_e = min(we, fn)
                            if seg_e > seg_s:
                                per_day = _split_minutes_by_day(seg_s, seg_e)
                                for dkey, mins in per_day.items():
                                    ot_minutes_by_day[dkey] = ot_minutes_by_day.get(dkey, 0.0) + mins
                        if ot_cap_min is not None:
                            for dkey, mins in ot_minutes_by_day.items():
                                used = temp_ot_used.get((mid, dkey), 0.0)
                                if used + mins > ot_cap_min + 1e-9:
                                    ot_ok = False
                                    saw_ot_cap = True
                                    break
                        if ot_ok:
                            cand = {
                                'machine': mid, 'start': st, 'finish': fn,
                                'setup_min': setup_min, 'proc_min': proc_min, 'splits': 0,
                                'ot_usage': ot_minutes_by_day
                            }
                    else:
                        saw_no_contig = True
                else:
                    packed = _pack_across_windows(
                        wins_to_search, est, need_min,
                        setup_min=setup_min,
                        preemption_overhead_min=preempt_ovh
                    )
                    if packed:
                        st, fn, ovh_min, splits, ot_minutes_by_day = packed
                        ot_ok = True
                        if ot_cap_min is not None:
                            for dkey, mins in ot_minutes_by_day.items():
                                used = temp_ot_used.get((mid, dkey), 0.0)
                                if used + mins > ot_cap_min + 1e-9:
                                    ot_ok = False
                                    saw_ot_cap = True
                                    break
                        if ot_ok:
                            cand = {
                                'machine': mid, 'start': st, 'finish': fn,
                                'setup_min': setup_min, 'proc_min': proc_min + ovh_min,
                                'splits': int(splits), 'ot_usage': ot_minutes_by_day
                            }
                    else:
                        saw_pack_fail = True

                if cand is not None and ((best is None) or (cand['finish'] < best['finish'])):
                    best = cand

            if best is None:
                if saw_no_window:
                    fail_stats['no_window_after_est'] += 1
                elif saw_ot_cap:
                    fail_stats['ot_cap_hit'] += 1
                elif saw_no_contig:
                    fail_stats['no_contiguous_window'] += 1
                elif saw_pack_fail:
                    fail_stats['cannot_pack_across'] += 1
                else:
                    fail_stats['unknown_fit_fail'] += 1
                return None  # infeasible for this routing

            steps.append({
                'batch_id': batch.get('batch_id', ''),
                'order_id': batch['order_id'],
                'product_id': batch['product_id'],
                'routing_id': routing['routing_id'],
                'operation': op['name'],
                'qty': batch['qty'],
                'machine': best['machine'],
                'start': best['start'],
                'finish': best['finish'],
                'setup_min': best['setup_min'],
                'proc_min': best['proc_min'],
                'splits': best.get('splits', 0)
            })
            for dkey, mins in (best.get('ot_usage') or {}).items():
                temp_ot_used[(best['machine'], dkey)] = temp_ot_used.get((best['machine'], dkey), 0.0) + mins
            temp_free[best['machine']] = best['finish']
            temp_state[best['machine']] = op.get('setup_state_key', 'clean')
            cur_start = best['finish']

        final_finish = steps[-1]['finish'] if steps else cur_start
        return {
            "steps": steps,
            "finish": final_finish,
            "temp_free": temp_free,
            "temp_state": temp_state,
            "temp_ot_used": temp_ot_used
        }

    for batch in chrom:
        cands = product_routing_candidates(ctx, batch['product_id'])
        if not cands:
            fail_stats['no_routing_for_product'] += 1
            skipped += 1
            continue

        best_plan = None
        for routing in cands:
            plan = try_schedule_with_routing(batch, routing)
            if plan is None:
                continue
            if (best_plan is None) or (plan["finish"] < best_plan["finish"]):
                best_plan = plan

        if best_plan is None:
            skipped += 1
            continue

        schedule.extend(best_plan["steps"])
        machine_free = best_plan["temp_free"]
        machine_state = best_plan["temp_state"]
        ot_used = best_plan["temp_ot_used"]

    return {'schedule': schedule, 'skipped': skipped}

def decode(ctx: Context, chrom: List[Dict[str, Any]]):
    # ✅ กันตกชั้นที่ 1: กรอง None / ชนิดที่ไม่ใช่ dict
    orig_len = len(chrom)
    chrom = [b for b in chrom if isinstance(b, dict)]

    # ✅ กันตกชั้นที่ 2: กรอง batch ที่ไม่ครบคีย์สำคัญ
    REQUIRED_KEYS = ("order_id", "product_id", "qty", "release_date", "due_date")
    def _valid(b: Dict[str, Any]) -> bool:
        try:
            return all(k in b for k in REQUIRED_KEYS)
        except Exception:
            return False

    chrom = [b for b in chrom if _valid(b)]
    skipped_pre = orig_len - len(chrom)
    if not chrom:
        return {'schedule': [], 'skipped': skipped_pre, 'fail_stats': {}}

    # horizon พื้นฐาน + fallback ขยายอัตโนมัติ
    base_days = _auto_horizon_days(chrom)

    best_decoded = None
    best_tuple = None  # (skipped, makespan)

    fail_stats_all: Dict[str, int] = defaultdict(int)

    for add_days in (0, 7, 14):  # ✅ ลองขยายกรอบเวลา 0 / +7 / +14 วัน
        fail_stats = defaultdict(int)
        decoded = _schedule_once(ctx, chrom, base_days + add_days, fail_stats)

        # ranking: น้อย skipped กว่า → ดีกว่า, ถ้าเท่ากัน เปรียบ makespan
        skipped = decoded['skipped']
        if decoded['schedule']:
            makespan = max(s['finish'] for s in decoded['schedule'])
        else:
            makespan = dt.datetime.max

        rank = (skipped, makespan)
        if (best_tuple is None) or (rank < best_tuple):
            best_tuple = rank
            best_decoded = decoded
            # เก็บสถิติจากรอบที่ดีที่สุด
            fail_stats_all = fail_stats

        # ถ้าจัดครบแล้ว ไม่ต้องลองเพิ่มวัน
        if skipped == 0:
            break

    # รวม skipped จากการกรองช่วงต้นด้วย
    out = best_decoded or {'schedule': [], 'skipped': 0}
    out['skipped'] = out.get('skipped', 0) + skipped_pre
    out['fail_stats'] = dict(fail_stats_all)
    return out

def evaluate(ctx: Context, decoded: Dict[str, Any]) -> float:
    schedule = decoded['schedule']
    skipped = decoded.get('skipped', 0)

    if not schedule:
        return 1e12 + 1e9 * skipped

    makespan = max(s['finish'] for s in schedule)
    start0 = min(s['start'] for s in schedule)

    last_finish_by_order: Dict[str, dt.datetime] = {}
    for s in schedule:
        last_finish_by_order[s['order_id']] = max(
            last_finish_by_order.get(s['order_id'], s['finish']), s['finish']
        )

    tardiness_min = 0.0
    all_orders = list(ctx.data.get('orders', []))
    due_by_order = {o['order_id']: parse_datetime(o['due_date']) for o in all_orders}
    for oid, fin in last_finish_by_order.items():
        due = due_by_order.get(oid)
        if not due:
            continue
        delay = max((fin - due).total_seconds() / 60.0, 0.0)
        tardiness_min += delay

    w = (ctx.settings or {}).get('objective_weights', {})
    obj = 0.0
    obj += w.get('makespan', 1.0) * ((makespan - start0).total_seconds() / 60.0)
    obj += w.get('tardiness', 10.0) * tardiness_min
    setup_cost = sum(s.get('setup_min', 0.0) for s in schedule)
    obj += w.get('setup_cost', 5.0) * setup_cost
    num_splits_total = sum(int(s.get('splits', 0)) for s in schedule)
    obj += w.get('preemption_cost', 0.0) * float(num_splits_total)
    obj += 1e6 * skipped
    return obj

# ============================= GA + Local Search =============================

def random_chromosome(batches: List[Dict[str, Any]]):
    chrom = deepcopy(batches)
    random.shuffle(chrom)
    return chrom

def _chrom_key_item(b):
    return (b.get('batch_id',''), b['order_id'], b['product_id'], b['qty'],
            b['release_date'].isoformat(), b['due_date'].isoformat())

def _normalize_chromosome(chrom, ref_pool=None):
    out = [x for x in chrom if isinstance(x, dict)]
    if ref_pool is None:
        return out

    used = set(_chrom_key_item(b) for b in out)
    for b in ref_pool:
        k = _chrom_key_item(b)
        if k not in used:
            out.append(b)
            used.add(k)
    return out

def crossover(p1, p2):
    n = len(p1)
    if n < 2:
        return deepcopy(p1)

    a, b = sorted(random.sample(range(n), 2))
    child = [None] * n

    mid_slice = [deepcopy(x) for x in p1[a:b+1]]
    child[a:b+1] = mid_slice
    used = set(_chrom_key_item(x) for x in mid_slice)

    idx = (b + 1) % n
    for item in p2:
        k = _chrom_key_item(item)
        if k in used:
            continue
        while child[idx] is not None:
            idx = (idx + 1) % n
        child[idx] = deepcopy(item)
        used.add(k)

    child = _normalize_chromosome(child, ref_pool=p1)
    return child

def mutate(chrom, rate=0.2):
    c = deepcopy(chrom)
    n = len(c)
    swaps = max(1, int(rate * n))
    for _ in range(swaps):
        i, j = random.randrange(n), random.randrange(n)
        c[i], c[j] = c[j], c[i]
    return c

def local_search(ctx: Context, chrom, iterations=20, tabu_size=6, temp_start=800):
    chrom = _normalize_chromosome(chrom)

    best_chrom = deepcopy(chrom)
    best_obj = evaluate(ctx, decode(ctx, best_chrom))
    tabu: List[Tuple] = []
    temp = temp_start
    alpha = 0.95
    for _ in range(iterations):
        neighbor = mutate(best_chrom, rate=0.3)
        neighbor = _normalize_chromosome(neighbor, ref_pool=chrom)

        sig = tuple((x.get('batch_id',''), x['order_id'], x['product_id'], x['qty']) for x in neighbor)
        if sig in tabu:
            continue
        obj = evaluate(ctx, decode(ctx, neighbor))
        delta = obj - best_obj
        if delta < 0 or random.random() < math.exp(-delta / max(temp, 1e-9)):
            best_chrom = neighbor
            best_obj = obj
            tabu.append(sig)
            if len(tabu) > tabu_size:
                tabu.pop(0)
        temp *= alpha
    return best_chrom

def ga_scheduler(ctx: Context, batches, population=18, generations=12):
    pop = [_normalize_chromosome(random_chromosome(batches), ref_pool=batches) for _ in range(population)]
    best_chrom = pop[0]
    best_obj = evaluate(ctx, decode(ctx, best_chrom))

    for gen in range(generations):
        new_pop = []
        for _ in range(population):
            p1, p2 = random.sample(pop, 2)
            child = crossover(p1, p2)
            child = mutate(child)
            child = _normalize_chromosome(child, ref_pool=batches)
            child = local_search(ctx, child, iterations=20, tabu_size=6)
            new_pop.append(child)

        for chrom in new_pop:
            obj = evaluate(ctx, decode(ctx, chrom))
            if obj < best_obj:
                best_chrom = chrom
                best_obj = obj
        pop = new_pop
        print(f"Generation {gen+1}/{generations}, best_obj={best_obj:.2f}")

    decoded = decode(ctx, best_chrom)
    return decoded

# ============================= Printing helpers =============================

def to_printable_row(s: Dict[str, Any]):
    return {
        "batch_id": s.get('batch_id', ''),
        "order_id": s['order_id'],
        "product_id": s['product_id'],
        "routing_id": s.get('routing_id', ''),
        "operation": s['operation'],
        "qty": s['qty'],
        "machine": s['machine'],
        "start": s['start'].strftime("%Y-%m-%d %H:%M"),
        "finish": s['finish'].strftime("%Y-%m-%d %H:%M"),
        "setup_min": round(s.get('setup_min', 0.0), 2),
        "proc_min": round(s.get('proc_min', 0.0), 2),
        "splits": int(s.get('splits', 0)),
    }

# ============================= Main =============================
if __name__ == "__main__":
    random.seed(42)

    data = load_data("./mock_without_operator.json")
    ctx = Context.from_data(data)

    orders_all = list(data.get('orders', []))
    batches = build_batches(ctx, orders_all)
    if not batches:
        print("No batches generated. Please check orders/products/routings in json")
        raise SystemExit(1)

    decoded = ga_scheduler(ctx, batches, population=18, generations=12)
    final_schedule = decoded['schedule']
    fail_stats = decoded.get('fail_stats', {})
    skipped = decoded.get('skipped', 0)

    print("\n=== FINAL SCHEDULE (console only) ===")
    printable = [to_printable_row(r) for r in final_schedule]
    if printable:
        headers = list(printable[0].keys())
        print(",".join(headers))
        for r in printable:
            print(",".join(str(r[h]) for h in headers))
    else:
        print("(empty)")

    # Group by machine
    by_machine: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in final_schedule:
        dur_min = r.get("setup_min", 0.0) + r.get("proc_min", 0.0)
        by_machine[r["machine"]].append({
            "batch_id": r.get("batch_id",""),
            "order_id": r["order_id"],
            "product_id": r["product_id"],
            "routing_id": r.get("routing_id",""),
            "operation": r["operation"],
            "qty": r["qty"],
            "start": r["start"].strftime("%Y-%m-%d %H:%M"),
            "finish": r["finish"].strftime("%Y-%m-%d %H:%M"),
            "setup_min": round(r.get("setup_min", 0.0), 2),
            "proc_min": round(r.get("proc_min", 0.0), 2),
            "splits": int(r.get("splits", 0)),
            "duration_min": round(dur_min, 2)
        })

    print("\n=== MACHINE SCHEDULES (console only) ===")
    def _p(ts: str):
        return dt.datetime.strptime(ts, "%Y-%m-%d %H:%M")

    for m_id, rows in sorted(by_machine.items()):
        rows.sort(key=lambda x: _p(x["start"]))
        print(f"\n--- Machine: {m_id} ---")
        header = ["batch_id","order_id","product_id","routing_id","operation","qty","start","finish","setup_min","proc_min","splits","duration_min"]
        print(",".join(header))
        for r in rows:
            print(",".join(str(r[h]) for h in header))

    print("\n=== MACHINE UTILIZATION (rough; console only) ===")
    for m_id, rows in sorted(by_machine.items()):
        rows_sorted = sorted(rows, key=lambda x: _p(x["start"]))
        if not rows_sorted:
            continue
        first_start = _p(rows_sorted[0]["start"])
        last_finish = _p(rows_sorted[-1]["finish"])
        horizon_min = max((last_finish - first_start).total_seconds()/60.0, 1e-9)
        busy_min = sum(r["duration_min"] for r in rows_sorted)
        busy_min = min(busy_min, horizon_min)
        util = (busy_min / horizon_min)
        print(f"{m_id}: busy={busy_min:.1f} min, horizon={horizon_min:.1f} min, util={util*100:.1f}%")

    print("\n=== COVERAGE (by batch_id) ===")
    total_batches = len(set(b.get('batch_id','') for b in batches))
    scheduled_batches = len(set(s.get('batch_id','') for s in final_schedule))
    missed = sorted(set(b.get('batch_id','') for b in batches) - set(s.get('batch_id','') for s in final_schedule))
    print(f"scheduled={scheduled_batches}/{total_batches}")
    if missed:
        print("MISSED BATCH_IDs:", ", ".join(missed))

    if fail_stats:
        print("\n=== FAIL STATS (decode reasons) ===")
        for k, v in sorted(fail_stats.items(), key=lambda x: (-x[1], x[0])):
            print(f"{k}: {v}")
