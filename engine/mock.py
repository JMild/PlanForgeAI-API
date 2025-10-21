# scheduler_refactored.py
# -------------------------------------------------------------
# Robust GA + Local Search (SA/Tabu) minimalist scheduler
# - Supports single-line & multi-line orders
# - Time normalize: *_min (minutes) or hour values (auto-convert)
# - Candidate machines from machines + work_centers.parallel_machines
# - Handles best=None (no feasible slot) by skipping & penalizing in objective
# - Shift windows with holidays & maintenance subtraction
# - Operator requirements (setup/run), machine efficiency, speed overrides
# - Clear separation via Context + interval utilities
# -------------------------------------------------------------
from __future__ import annotations
import json, os, math, random, datetime as dt
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional
from copy import deepcopy

# ============================= Utilities =============================

def parse_datetime(s) -> dt.datetime:
    """Parse many common formats. Raise if impossible to avoid silent bugs."""
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
            return d
        except Exception as e:
            last_err = e
            continue
    raise ValueError(f"Cannot parse datetime: {s!r}. Last error: {last_err}")


def timedelta_minutes(m: float) -> dt.timedelta:
    return dt.timedelta(seconds=float(m) * 60.0)


# ============================= Data Loading =============================

def load_data(json_path: str = "/mnt/data/mock.json") -> Dict[str, Any]:
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Minimal fallback sample
    sample = {
        "orders": [
            {"order_id": "ORD001", "product_id": "P001", "quantity": 50, "due_date": "2025-10-22T17:00:00", "priority": 1}
        ],
        "orders_multiline": [
            {"order_id":"ORD002","due_date":"2025-10-23T17:00:00",
             "lines":[{"product_id":"P001","quantity":40},{"product_id":"P002","quantity":30}]}
        ],
        "products": [
            {"product_id":"P001","name":"Widget A","routing_id":"R001","bom_id":"B001"},
            {"product_id":"P002","name":"Widget B","routing_id":"R002","bom_id":"B002"}
        ],
        "routings": [
            {"routing_id":"R001","operations":[
                {"op_no":1,"name":"Cut","work_center_id":"WC_CUT","proc_time_per_unit":0.15,"setup_time_fixed":10,
                 "setup_state_key":"MAT_A","batchable":True,"batch":{"min_batch_qty":20,"max_batch_qty":100},
                 "setup_requires_operator": True},
                {"op_no":2,"name":"Paint","work_center_id":"WC_PAINT","proc_time_per_unit":0.25,"setup_time_fixed":15,
                 "setup_state_key":"color_red","batchable":True,"batch":{"min_batch_qty":10,"max_batch_qty":100}}
            ]},
            {"routing_id":"R002","operations":[
                {"op_no":1,"name":"Cut B","work_center_id":"WC_CUT","proc_time_per_unit":0.20,"setup_time_fixed":8,
                 "setup_state_key":"MAT_B","batchable":True,"batch":{"min_batch_qty":10,"max_batch_qty":80}}
            ]}
        ],
        "work_centers":[
            {"work_center_id":"WC_CUT","name":"Cutting","parallel_machines":["M_CUT_1","M_CUT_2"], "setup_matrix_id": "SETUP_MATRIX_CUT"},
            {"work_center_id":"WC_PAINT","name":"Painting","parallel_machines":["M_PAINT_1"], "setup_matrix_id": "SETUP_MATRIX_PAINT"}
        ],
        "machines": [
            {"machine_id":"M_CUT_1","work_center_id":"WC_CUT","initial_state":"clean", "efficiency": 0.95},
            {"machine_id":"M_CUT_2","work_center_id":"WC_CUT","initial_state":"clean"},
            {"machine_id":"M_PAINT_1","work_center_id":"WC_PAINT","initial_state":"clean", "requires_operator_for_run": True}
        ],
        "operators":[
            {"operator_id":"OP01","name":"Somchai","skills":["cut","paint"],"assignable_to":["WC_CUT","WC_PAINT"]}
        ],
        "setup_matrices":[
            {"setup_matrix_id":"SETUP_MATRIX_CUT","matrix":{
                "clean":{"MAT_A":8,"MAT_B":10},
                "MAT_A":{"MAT_A":5,"MAT_B":12},
                "MAT_B":{"MAT_A":10,"MAT_B":6}
            }},
            {"setup_matrix_id":"SETUP_MATRIX_PAINT","matrix":{
                "clean":{"color_red":10,"color_blue":10},
                "color_red":{"color_red":4,"color_blue":30},
                "color_blue":{"color_red":28,"color_blue":5}
            }}
        ],
        "calendar": {
            "holidays": ["2025-10-23"],
            "machine_maintenances": [
                {"machine_id":"M_CUT_1", "start":"2025-10-14 12:00", "end":"2025-10-14 16:00"}
            ]
        },
        "settings":{"objective_weights":{"makespan":1.0,"tardiness":10.0,"setup_cost":5.0}}
    }
    return sample


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


# ============================= Batch builder =============================

def normalize_orders_for_batching(data: Dict[str, Any]):
    base = list(data.get('orders', []))
    multi = list(data.get('orders_multiline', []))
    return base + multi


def build_batches(ctx: Context, orders: List[Dict[str, Any]]):
    prod_by_id = ctx.idx_products
    routing_by_id = ctx.idx_routings

    batches = []
    now = dt.datetime.now()

    for order in orders:
        order_due = parse_datetime(order['due_date'])
        order_rel = parse_datetime(order.get('release_date', now.strftime("%Y-%m-%d %H:%M")))
        order_pri = order.get('priority', 1)

        if 'lines' in order and isinstance(order['lines'], list):
            lines = order['lines']
        else:
            lines = [{
                'product_id': order.get('product_id'),
                'quantity': order.get('quantity', 0),
                'priority': order_pri
            }]

        for line in lines:
            pid = line['product_id']
            qty_total = int(line['quantity'])
            prod = prod_by_id.get(pid)
            if not prod:
                continue
            routing = routing_by_id.get(prod['routing_id'])
            if not routing:
                continue

            # first batchable op as rule (if any)
            batch_rule = {}
            for op in routing.get('operations', []):
                if op.get('batchable'):
                    batch_rule = op.get('batch', {})
                    break

            min_batch = int(batch_rule.get('min_batch_qty', qty_total))
            max_batch = max(1, int(batch_rule.get('max_batch_qty', qty_total)))
            remaining = qty_total

            while remaining > 0:
                take = min(remaining, max_batch)
                # if last chunk smaller than min_batch, merge with previous if exists
                if remaining <= max_batch and take < min_batch and batches and batches[-1]['order_id'] == order['order_id'] and batches[-1]['product_id'] == pid:
                    batches[-1]['qty'] += take
                else:
                    batches.append({
                        "order_id": order['order_id'],
                        "product_id": pid,
                        "routing_id": prod['routing_id'],
                        "qty": take,
                        "priority": line.get('priority', order_pri),
                        "due_date": order_due,
                        "release_date": order_rel
                    })
                remaining -= take
    return batches


# ============================= Time & Cost helpers =============================

def _get_fixed_setup_min(op: Dict[str, Any]) -> float:
    if 'setup_time_fixed_min' in op:
        return float(op['setup_time_fixed_min'])
    if 'setup_time_fixed' in op:
        return float(op['setup_time_fixed']) * 60.0
    return 0.0


def _lookup_matrix_setup_min(ctx: Context, prev_state: str, next_state: str, machine: Dict[str, Any], op: Dict[str, Any]) -> float:
    mat_id = machine.get('setup_matrix_id') or op.get('setup_matrix_id')
    if not mat_id:
        # fallback by work center
        wc_id = op.get('work_center_id')
        wc = ctx.idx_wc.get(wc_id) if wc_id else None
        mat_id = wc.get('setup_matrix_id') if wc else None
    if mat_id and mat_id in ctx.setup_mats:
        mat_obj = ctx.setup_mats[mat_id]
        matrix = mat_obj.get('matrix', {})
        if prev_state in matrix and next_state in matrix[prev_state]:
            return float(matrix[prev_state][next_state])
    return _get_fixed_setup_min(op)


def _get_proc_time_min(ctx: Context, op: Dict[str, Any], qty: float, *, machine_id: Optional[str]=None, product_id: Optional[str]=None, machine_eff: float=1.0) -> float:
    # accept proc_time_per_unit_min or proc_time_per_unit (hours)
    if 'proc_time_per_unit_min' in op:
        per_unit_min = float(op['proc_time_per_unit_min'])
    elif 'proc_time_per_unit' in op:
        per_unit_min = float(op['proc_time_per_unit']) * 60.0
    else:
        per_unit_min = 0.0

    total_min = per_unit_min * float(qty)

    # speed overrides
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

    # efficiency (e.g., 0.9 → slower → more minutes)
    if machine_eff and machine_eff > 0:
        total_min = total_min / float(machine_eff)

    return total_min


# ============================= Interval utils =============================

Interval = Tuple[dt.datetime, dt.datetime]

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
    """Subtract 'subtracts' from 'base' (both lists of [s,e])."""
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
                if se <= cs or ss >= ce:  # no overlap
                    next_segments.append((cs, ce))
                else:
                    # overlap
                    if ss > cs:
                        next_segments.append((cs, ss))
                    if se < ce:
                        next_segments.append((se, ce))
            cur_segments = next_segments
        out.extend(cur_segments)
    return [seg for seg in out if seg[1] > seg[0]]


def _intersect_two(a: List[Interval], b: List[Interval]) -> List[Interval]:
    i, j = 0, 0
    res: List[Interval] = []
    a = sorted(a)
    b = sorted(b)
    while i < len(a) and j < len(b):
        s = max(a[i][0], b[j][0])
        e = min(a[i][1], b[j][1])
        if s < e:
            res.append((s, e))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return res


# ============================= Windows (shifts/holidays/maintenance) =============================

def _time_on_date(date: dt.date, hhmm: str) -> dt.datetime:
    hh, mm = map(int, hhmm.split(":"))
    return dt.datetime(year=date.year, month=date.month, day=date.day, hour=hh, minute=mm)


def build_shift_windows(ctx: Context, start_anchor: dt.datetime, days: int = 7):
    """Return: dict(machine_id->windows), dict(operator_id->windows). Remove holidays and maintenance."""
    data = ctx.data
    # shifts indexed
    shift_by = {s['shift_id']: s for s in data.get('shifts', [])}

    # prebuild shift windows by id
    windows_by_shift: Dict[str, List[Interval]] = {}
    for sid, s in shift_by.items():
        windows: List[Interval] = []
        for d in range(days):
            base = (start_anchor.date() + dt.timedelta(days=d))
            st = _time_on_date(base, s['start_time'])
            en = _time_on_date(base, s['end_time'])
            if en <= st:  # cross-midnight
                en = en + dt.timedelta(days=1)
            windows.append((st, en))
        windows_by_shift[sid] = windows

    # Holidays subtraction for machines & operators
    holis = []
    for h in (data.get('calendar', {}) or {}).get('holidays', []) or []:
        try:
            d = dt.datetime.strptime(h, "%Y-%m-%d").date()
        except Exception:
            d = parse_datetime(h).date()
        holis.append((dt.datetime(d.year, d.month, d.day), dt.datetime(d.year, d.month, d.day) + dt.timedelta(days=1)))

    # Machines windows
    machines_by_id = ctx.idx_machines_by_id
    windows_by_machine: Dict[str, List[Interval]] = {}
    for mid, m in machines_by_id.items():
        shift_ids = m.get('shifts', [])
        merged: List[Interval] = []
        for sid in shift_ids:
            merged.extend(windows_by_shift.get(sid, []))
        if not merged:  # 24/7 default
            start = start_anchor.replace(hour=0, minute=0, second=0, microsecond=0)
            merged = [(start, start + dt.timedelta(days=days))]
        merged = _merge_intervals(merged)
        # subtract holidays
        merged = _subtract_intervals(merged, holis)
        # subtract maintenance
        maints: List[Interval] = []
        for mm in (data.get('calendar', {}) or {}).get('machine_maintenances', []) or []:
            if mm.get('machine_id') == mid:
                ms = parse_datetime(mm['start'])
                me = parse_datetime(mm['end'])
                maints.append((ms, me))
        merged = _subtract_intervals(merged, maints)
        windows_by_machine[mid] = merged

    # Operator windows (based on their shifts), then subtract holidays
    windows_by_operator: Dict[str, List[Interval]] = {}
    for op in data.get('operators', []) or []:
        merged: List[Interval] = []
        for sid in op.get('shifts', []) or []:
            merged.extend(windows_by_shift.get(sid, []))
        merged = _merge_intervals(merged)
        merged = _subtract_intervals(merged, holis)
        windows_by_operator[op['operator_id']] = merged

    return windows_by_machine, windows_by_operator


def _find_slot_in_windows(windows: List[Interval], earliest: dt.datetime, need_min: float, require_full_coverage: bool = False) -> Optional[Interval]:
    """Find first slot (s,e) within windows after earliest, with duration need_min minutes contiguous.
       If require_full_coverage=True, slot must lie wholly inside one window.
    """
    need = dt.timedelta(minutes=need_min)
    for ws, we in windows:
        s = max(ws, earliest)
        if require_full_coverage:
            if we - s >= need:
                return (s, s + need)
        else:
            # Same behavior (contiguous within a window). Multi-window stitching not implemented.
            if we - s >= need:
                return (s, s + need)
    return None


# ============================= Decode & Evaluate =============================

def decode(ctx: Context, chrom: List[Dict[str, Any]]):
    schedule: List[Dict[str, Any]] = []
    skipped = 0

    machines_by_id = ctx.idx_machines_by_id
    machines_by_wc = ctx.idx_machines_by_wc
    wc_by_id = ctx.idx_wc
    routing_by_id = ctx.idx_routings

    earliest_release = min((b['release_date'] for b in chrom), default=dt.datetime.now())

    machine_windows, operator_windows = build_shift_windows(ctx, earliest_release, days=14)

    machine_free: Dict[str, dt.datetime] = {m_id: earliest_release for m_id in machines_by_id.keys()}
    machine_state: Dict[str, str] = {m_id: machines_by_id[m_id].get('initial_state', 'clean') for m_id in machines_by_id.keys()}
    operator_free: Dict[str, dt.datetime] = {op['operator_id']: earliest_release for op in ctx.data.get('operators', [])}

    for batch in chrom:
        routing = routing_by_id.get(batch['routing_id'])
        if not routing:
            skipped += 1
            continue

        cur_start = max(batch['release_date'], earliest_release)

        for op in routing.get('operations', []):
            wc_id = op['work_center_id']
            candidates = list(machines_by_wc.get(wc_id, []))
            if not candidates:
                wc = wc_by_id.get(wc_id)
                if wc:
                    ids = set(wc.get('parallel_machines', []))
                    candidates = [machines_by_id[mid] for mid in ids if mid in machines_by_id]
            if not candidates:
                skipped += 1
                break

            best: Optional[Dict[str, Any]] = None
            for mc in candidates:
                mid = mc['machine_id']
                est = max(cur_start, machine_free[mid])

                # operator requirement
                need_op_setup = bool(op.get('setup_requires_operator', False))
                need_op_run = bool(op.get('run_requires_operator', False) or mc.get('requires_operator_for_run', False))
                assigned_op = None
                op_wins: List[Interval] = []

                if (need_op_setup or need_op_run) and ctx.data.get('operators'):
                    # qualified by op name OR work center
                    cap_ops = [o for o in ctx.data['operators'] if op['name'].lower() in [s.lower() for s in (o.get('skills', []) or [])]]
                    if not cap_ops:
                        cap_ops = [o for o in ctx.data['operators'] if wc_id in (o.get('assignable_to', []) or [])]
                    if cap_ops:
                        who = min(cap_ops, key=lambda x: operator_free[x['operator_id']])
                        assigned_op = who['operator_id']
                        est = max(est, operator_free[assigned_op])
                        op_wins = operator_windows.get(assigned_op, [])

                prev_state = machine_state.get(mid, mc.get('initial_state', 'clean'))
                next_state = op.get('setup_state_key', 'clean')
                setup_min = _lookup_matrix_setup_min(ctx, prev_state, next_state, mc, op)
                machine_eff = float(mc.get('efficiency', 1.0) or 1.0)
                proc_min  = _get_proc_time_min(ctx, op, batch['qty'], machine_id=mid, product_id=batch['product_id'], machine_eff=machine_eff)
                need_min  = setup_min + proc_min

                m_wins = machine_windows.get(mid, [(est, est + dt.timedelta(days=365))])

                # intersect machine ⨉ operator windows if needed
                wins_to_search: List[Interval] = []
                if op_wins and (need_op_setup or need_op_run):
                    for mw_s, mw_e in m_wins:
                        earliest = max(est, mw_s)
                        for ow_s, ow_e in op_wins:
                            start_candidate = max(earliest, ow_s)
                            end_candidate   = min(mw_e, ow_e)
                            if start_candidate < end_candidate:
                                wins_to_search.append((start_candidate, end_candidate))
                else:
                    wins_to_search = [(max(est, a), b) for (a, b) in m_wins]

                slot = _find_slot_in_windows(wins_to_search, est, need_min, require_full_coverage=need_op_run)
                if not slot:
                    continue

                st, fn = slot
                cand = {
                    'machine': mid,
                    'start': st,
                    'finish': fn,
                    'operator': assigned_op,
                    'setup_min': setup_min,
                    'proc_min': proc_min
                }
                if (best is None) or (fn < best['finish']):
                    best = cand

            if best is None:
                skipped += 1
                break

            schedule.append({
                'order_id': batch['order_id'],
                'product_id': batch['product_id'],
                'routing_id': batch['routing_id'],
                'operation': op['name'],
                'qty': batch['qty'],
                'machine': best['machine'],
                'start': best['start'],
                'finish': best['finish'],
                'operator': best['operator'],
                'setup_min': best['setup_min'],
                'proc_min': best['proc_min']
            })

            machine_free[best['machine']] = best['finish']
            machine_state[best['machine']] = op.get('setup_state_key', 'clean')
            if best['operator']:
                operator_free[best['operator']] = best['finish']
            cur_start = best['finish']

    return {'schedule': schedule, 'skipped': skipped}


def evaluate(ctx: Context, decoded: Dict[str, Any]) -> float:
    schedule = decoded['schedule']
    skipped = decoded.get('skipped', 0)

    if not schedule:
        return 1e12 + 1e9 * skipped

    makespan = max(s['finish'] for s in schedule)
    start0 = min(s['start'] for s in schedule)

    # tardiness by order (use last finish per order)
    last_finish_by_order: Dict[str, dt.datetime] = {}
    for s in schedule:
        last_finish_by_order[s['order_id']] = max(last_finish_by_order.get(s['order_id'], s['finish']), s['finish'])

    tardiness_min = 0.0
    all_orders = list(ctx.data.get('orders', [])) + list(ctx.data.get('orders_multiline', []))
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

    # heavy penalty on skipped ops
    obj += 1e6 * skipped
    return obj


# ============================= GA + Local Search =============================

def random_chromosome(batches: List[Dict[str, Any]]):
    chrom = deepcopy(batches)
    random.shuffle(chrom)
    return chrom


def crossover(p1, p2):
    if len(p1) < 2 or len(p2) < 2:
        return deepcopy(p1)
    n = len(p1)
    a, b = sorted(random.sample(range(n), 2))
    child = [None]*n
    child[a:b+1] = deepcopy(p1[a:b+1])

    def key(b):
        return (b['order_id'], b['product_id'], b['qty'], b['routing_id'], b['release_date'].isoformat(), b['due_date'].isoformat())

    used = set(key(x) for x in child[a:b+1] if x is not None)
    idx = (b+1) % n
    for item in p2:
        k = key(item)
        if k in used:
            continue
        while child[idx] is not None:
            idx = (idx + 1) % n
        child[idx] = deepcopy(item)
    return child


def mutate(chrom, rate=0.2):
    c = deepcopy(chrom)
    n = len(c)
    swaps = max(1, int(rate * n))
    for _ in range(swaps):
        i, j = random.randrange(n), random.randrange(n)
        c[i], c[j] = c[j], c[i]
    return c


def local_search(ctx: Context, chrom, iterations=50, tabu_size=10, temp_start=1000):
    best_chrom = deepcopy(chrom)
    best_obj = evaluate(ctx, decode(ctx, best_chrom))
    tabu: List[Tuple] = []
    temp = temp_start
    alpha = 0.95
    for _ in range(iterations):
        neighbor = mutate(best_chrom, rate=0.3)
        sig = tuple((x['order_id'], x['product_id'], x['qty']) for x in neighbor)
        if sig in tabu:
            continue
        obj = evaluate(ctx, decode(ctx, neighbor))
        delta = obj - best_obj
        if delta < 0 or random.random() < math.exp(-delta / temp):
            best_chrom = neighbor
            best_obj = obj
            tabu.append(sig)
            if len(tabu) > tabu_size:
                tabu.pop(0)
        temp *= alpha
    return best_chrom


def ga_scheduler(ctx: Context, batches, population=30, generations=20):
    pop = [random_chromosome(batches) for _ in range(population)]
    best_chrom = pop[0]
    best_obj = evaluate(ctx, decode(ctx, best_chrom))
    for gen in range(generations):
        new_pop = []
        for _ in range(population):
            p1, p2 = random.sample(pop, 2)
            child = crossover(p1, p2)
            child = mutate(child)
            child = local_search(ctx, child, iterations=20, tabu_size=5)
            new_pop.append(child)
        for chrom in new_pop:
            obj = evaluate(ctx, decode(ctx, chrom))
            if obj < best_obj:
                best_chrom = chrom
                best_obj = obj
        pop = new_pop
        print(f"Generation {gen+1}/{generations}, best_obj={best_obj:.2f}")
    decoded = decode(ctx, best_chrom)
    return decoded['schedule']


# ============================= Printing helpers =============================

def to_printable_row(s: Dict[str, Any]):
    return {
        "order_id": s['order_id'],
        "product_id": s['product_id'],
        "operation": s['operation'],
        "qty": s['qty'],
        "machine": s['machine'],
        "start": s['start'].strftime("%Y-%m-%d %H:%M"),
        "finish": s['finish'].strftime("%Y-%m-%d %H:%M"),
        "setup_min": round(s.get('setup_min', 0.0), 2),
        "proc_min": round(s.get('proc_min', 0.0), 2),
    }


# ============================= Main =============================
if __name__ == "__main__":
    random.seed(42)

    data = load_data("/mnt/data/mock.json")
    ctx = Context.from_data(data)

    orders_all = normalize_orders_for_batching(data)
    batches = build_batches(ctx, orders_all)
    if not batches:
        print("No batches generated. Please check orders/products/routings in mock.json")
        raise SystemExit(1)

    final_schedule = ga_scheduler(ctx, batches, population=20, generations=10)

    print("\n=== FINAL SCHEDULE (console only) ===")
    printable = [to_printable_row(r) for r in final_schedule]
    if printable:
        headers = list(printable[0].keys())
        print(",".join(headers))
        for r in printable:
            print(",".join(str(r[h]) for h in headers))
    else:
        print("(empty)")

    from collections import defaultdict
    by_machine: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in final_schedule:
        dur_min = r.get("setup_min", 0.0) + r.get("proc_min", 0.0)
        by_machine[r["machine"]].append({
            "order_id": r["order_id"],
            "product_id": r["product_id"],
            "operation": r["operation"],
            "qty": r["qty"],
            "start": r["start"].strftime("%Y-%m-%d %H:%M"),
            "finish": r["finish"].strftime("%Y-%m-%d %H:%M"),
            "setup_min": round(r.get("setup_min", 0.0), 2),
            "proc_min": round(r.get("proc_min", 0.0), 2),
            "duration_min": round(dur_min, 2)
        })

    print("\n=== MACHINE SCHEDULES (console only) ===")
    def _p(ts: str):
        return dt.datetime.strptime(ts, "%Y-%m-%d %H:%M")

    for m_id, rows in sorted(by_machine.items()):
        rows.sort(key=lambda x: _p(x["start"]))
        print(f"\n--- Machine: {m_id} ---")
        header = ["order_id","product_id","operation","qty","start","finish","setup_min","proc_min","duration_min"]
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
        horizon_min = (last_finish - first_start).total_seconds()/60.0
        busy_min = sum(r["duration_min"] for r in rows_sorted)
        util = (busy_min / horizon_min) if horizon_min > 0 else 0.0
        print(f"{m_id}: busy={busy_min:.1f} min, horizon={horizon_min:.1f} min, util={util*100:.1f}%")
