#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Production Planner – GA-only (BOM + Multi-line Orders) – DB/API friendly

Run:
  python engine_bom_ready_db.py --input mock_db.json --day0 2025-09-22 --prefix demo_db

สิ่งที่รองรับ:
- อินพุต JSON ได้ทั้งรูปแบบ "แบน" หรือที่ห่อเป็น { full, engine_v1 } (จะเลือก engine_v1 ก่อน)
- due_date (ISO 8601) และ/หรือ due_min (working minutes legacy)
- calendar.weekday_blocks เป็น "HH:MM" หรือจำนวนนาทีได้
- calendar.breaks จะถูก "หัก" ออกจากช่วงกะจริง
- Remap ดัชนีวัน: ถ้า JSON ใช้ 0=Sunday จะ map เป็น Python weekday() 0=Monday ให้เอง
"""

import math, json, random, argparse
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, Any
from collections import defaultdict, namedtuple
from datetime import date, datetime, timedelta

# =========================
# Models
# =========================
@dataclass
class ProcessDef:
    name: str
    base_duration_min: int
    compatible_machines: List[str]

@dataclass
class ProductDef:
    name: str
    process_plan: List[str]
    bom: List[Dict[str, Any]]

@dataclass
class OrderSingle:
    order_id: str
    product: str
    qty: int
    due_min: Optional[int] = None
    due_date: Optional[str] = None

@dataclass
class OrderMulti:
    order_id: str
    lines: List[Dict[str, Any]]
    due_min: Optional[int] = None
    due_date: Optional[str] = None

@dataclass
class MachineDef:
    name: str

@dataclass
class Task:
    task_id: int
    order_id: str
    product: str
    process: str
    duration_min: int
    compatible_machines: List[str]
    idx_in_flow: int
    tag: str

@dataclass
class ScheduleItem:
    task_id: int
    order_id: str
    product: str
    process: str
    machine: str
    start_min: int
    end_min: int
    setup_min: int
    late_min: int

# =========================
# Calendar helpers
# =========================
MINUTES_PER_DAY = 24*60

@dataclass
class ShiftBlock:
    start_min: int
    end_min: int

@dataclass
class CalendarConfig:
    weekday_blocks: Dict[int, List[ShiftBlock]]
    holidays: List[str]
    treat_weekend_as_off: bool = True

    @staticmethod
    def default():
        blocks = {i: [ShiftBlock(480,720), ShiftBlock(780,1020)] for i in range(5)}  # Mon-Fri
        blocks[5]=[]; blocks[6]=[]
        return CalendarConfig(weekday_blocks=blocks, holidays=[])

def parse_hhmm_to_min(s: str) -> int:
    hh, mm = s.split(":")
    return int(hh)*60 + int(mm)

def working_blocks_for_day(day0: date, idx: int, cal: CalendarConfig) -> List[ShiftBlock]:
    wd = (day0 + timedelta(days=idx)).weekday()  # Python: Monday=0
    if cal.treat_weekend_as_off and wd in (5,6):
        return []
    dstr = (day0 + timedelta(days=idx)).isoformat()
    if dstr in set(cal.holidays):
        return []
    return cal.weekday_blocks.get(wd, [])

def align_to_working(day0: date, t: int, cal: CalendarConfig) -> int:
    while True:
        day_idx = t // MINUTES_PER_DAY
        minute_in_day = t % MINUTES_PER_DAY
        blocks = working_blocks_for_day(day0, day_idx, cal)
        moved = False
        for b in blocks:
            if minute_in_day < b.start_min:
                t = day_idx*MINUTES_PER_DAY + b.start_min
                moved = True; break
            if b.start_min <= minute_in_day < b.end_min:
                return t
        if moved:
            return t
        t = (day_idx+1)*MINUTES_PER_DAY

def add_working_minutes(day0: date, start: int, dur: int, cal: CalendarConfig) -> int:
    t = align_to_working(day0, start, cal)
    r = dur
    while r > 0:
        day_idx = t // MINUTES_PER_DAY
        minute_in_day = t % MINUTES_PER_DAY
        blocks = working_blocks_for_day(day0, day_idx, cal)
        block_end = None
        for b in blocks:
            if b.start_min <= minute_in_day < b.end_min:
                block_end = b.end_min; break
        if block_end is None:
            t = align_to_working(day0, t, cal); continue
        can = min(r, block_end - minute_in_day)
        t += can; r -= can
        if r > 0:
            t = align_to_working(day0, day_idx*MINUTES_PER_DAY + block_end, cal)
    return t

# =========================
# GA core
# =========================
Chromosome = namedtuple("Chromosome", ["perm","mach_assign"])

@dataclass
class GAConfig:
    pop_size: int = 80
    generations: int = 200
    tournament_k: int = 3
    crossover_rate: float = 0.9
    mutation_rate: float = 0.25
    elite_count: int = 3
    w_tardiness: float = 1.0
    w_setup: float = 0.3
    w_makespan: float = 0.2
    seed: int = 123

def init_population(rng: random.Random, tasks: List[Task], cfg: GAConfig) -> List[Chromosome]:
    n = len(tasks)
    pop = []
    for _ in range(cfg.pop_size):
        perm = list(range(n)); rng.shuffle(perm)
        mach = [rng.choice(tasks[i].compatible_machines) for i in range(n)]
        pop.append(Chromosome(perm, mach))
    return pop

def tournament_select(rng, population, fitnesses, k):
    idxs = rng.sample(range(len(population)), k)
    best = min(idxs, key=lambda i: fitnesses[i])
    return population[best]

def ox_crossover(rng, a: Chromosome, b: Chromosome):
    n=len(a.perm)
    if n<2: return a,b
    i,j=sorted(rng.sample(range(n),2))
    def ox(p1,p2):
        child=[None]*n; child[i:j+1]=p1.perm[i:j+1]
        p2items=[x for x in p2.perm if x not in child]
        ptr=0
        for idx in list(range(0,i))+list(range(j+1,n)):
            child[idx]=p2items[ptr]; ptr+=1
        mach=[p1.mach_assign[k] if rng.random()<0.5 else p2.mach_assign[k] for k in range(n)]
        return Chromosome(child, mach)
    return ox(a,b), ox(b,a)

def mutate(rng, ch: Chromosome, tasks: List[Task], rate: float):
    perm=ch.perm[:]; mach=ch.mach_assign[:]; n=len(perm)
    if rng.random()<rate:
        i,j=rng.sample(range(n),2); perm[i],perm[j]=perm[j],perm[i]
    if rng.random()<rate:
        k=rng.randrange(n); t=tasks[perm[k]]
        mach[perm[k]] = random.choice(t.compatible_machines)
    return Chromosome(perm,mach)

# =========================
# Setup & Speed helpers
# =========================
def get_setup(setup_sd: Dict[Tuple[str,str,str], int], machine: str, last_proc: Optional[str], next_proc: str) -> int:
    if last_proc is None or last_proc == next_proc:
        return 0
    return setup_sd.get((machine, last_proc, next_proc), 0)

def get_speed(speed: Dict[Tuple, float], machine: str, product: str, process: str) -> float:
    return speed.get((machine, product, process)) or speed.get((machine, process)) or 1.0

# =========================
# Task expansion with BOM
# =========================
def build_tasks_with_bom(process_defs, product_defs, orders_single, orders_multi):
    tasks: List[Task] = []
    tid = 0
    extra_preds: Dict[int, List[int]] = defaultdict(list)
    product_last_idx_by_tag: Dict[str, int] = {}
    order_due_working_by_tag: Dict[str, int] = {}
    order_due_date_by_tag: Dict[str, str] = {}

    def expand_product(order_id: str, product_name: str, qty: int, due_min: Optional[int], due_date: Optional[str], tag_suffix: str):
        nonlocal tid
        tag = f"{order_id}|{product_name}{tag_suffix}"
        plan = product_defs[product_name].process_plan
        batch_size = 10
        batches = math.ceil(qty / batch_size)
        ids_for_this_product: List[int] = []
        for idx, p in enumerate(plan):
            dur = process_defs[p].base_duration_min * batches
            t = Task(
                task_id=tid, order_id=order_id, product=product_name, process=p,
                duration_min=dur, compatible_machines=list(process_defs[p].compatible_machines),
                idx_in_flow=idx, tag=tag
            )
            tasks.append(t); ids_for_this_product.append(tid); tid += 1
        product_last_idx_by_tag[tag] = len(plan) - 1
        if due_min is not None:
            order_due_working_by_tag[tag] = int(due_min)
        if due_date is not None:
            order_due_date_by_tag[tag] = str(due_date)

        # BOM expansion
        bom = product_defs[product_name].bom or []
        for item in bom:
            child_prod = item["product"]
            mult = int(item.get("multiplier", 1))
            gate = item.get("gate_process")
            child_ids, _ = expand_product(order_id, child_prod, qty*mult, due_min, due_date, tag_suffix=f"{tag_suffix}#{child_prod}")
            if gate in plan:
                gate_task_id = ids_for_this_product[plan.index(gate)]
                extra_preds[gate_task_id].extend(child_ids)
        return ids_for_this_product, {tag: due_min if due_min is not None else due_date}

    for od in orders_single:
        if od.product not in product_defs:
            continue
        expand_product(od.order_id, od.product, od.qty, od.due_min, od.due_date, tag_suffix="")
    for om in orders_multi:
        for idx, line in enumerate(om.lines, start=1):
            prod = line["product"]
            if prod not in product_defs:
                continue
            expand_product(om.order_id, prod, int(line["qty"]), om.due_min, om.due_date, tag_suffix=f"#{idx}")

    return tasks, extra_preds, product_last_idx_by_tag, order_due_working_by_tag, order_due_date_by_tag

# =========================
# Decoder (SGS ready-queue + calendar-aware)
# =========================
def align_baseline(day0: date, cal) -> int:
    return align_to_working(day0, 0, cal)

def build_schedule(tasks, machines, setup_sd, speed, perm, mach_assign, cal, day0, extra_preds):
    tasks_by_id = {t.task_id: t for t in tasks}
    baseline = align_baseline(day0, cal)
    machine_time = {m: baseline for m in machines.keys()}
    machine_last_proc = {m: None for m in machines.keys()}
    sched: List[ScheduleItem] = []
    done_time: Dict[int, int] = {}
    flow_done: Dict[Tuple[str, int], int] = {}
    total_setup = 0

    if not tasks:
        # ไม่มีงานก็คืนตารางว่าง พร้อม KPI พื้นฐาน
        kpis = {"baseline_min": baseline, "makespan_min": 0, "total_setup_min": 0, "machine_utilization": {m:0.0 for m in machines.keys()}}
        return [], kpis

    unscheduled = set(perm)
    made_progress = True
    while unscheduled and made_progress:
        made_progress = False
        for tid in list(unscheduled):
            t = tasks_by_id[tid]
            flow_ready = (t.idx_in_flow == 0) or ((t.tag, t.idx_in_flow-1) in flow_done)
            bom_ready  = all(pred in done_time for pred in extra_preds.get(tid, []))
            if not (flow_ready and bom_ready):
                continue

            m = mach_assign[tid]
            if m not in t.compatible_machines:
                m = t.compatible_machines[0]

            earliest = align_to_working(day0, max(baseline, machine_time[m]), cal)
            if t.idx_in_flow > 0:
                earliest = max(earliest, flow_done[(t.tag, t.idx_in_flow-1)])
            for pred in extra_preds.get(tid, []):
                earliest = max(earliest, done_time[pred])

            setup = get_setup(setup_sd, m, machine_last_proc[m], t.process)
            sp = max(1e-6, get_speed(speed, m, t.product, t.process))
            proc = math.ceil(t.duration_min / sp)

            start = earliest
            after_setup = add_working_minutes(day0, start, setup, cal) if setup else start
            end = add_working_minutes(day0, after_setup, proc, cal)

            sched.append(ScheduleItem(t.task_id, t.order_id, t.product, t.process, m, start, end, setup, 0))
            machine_time[m] = end
            machine_last_proc[m] = t.process
            done_time[tid] = end
            flow_done[(t.tag, t.idx_in_flow)] = end
            total_setup += setup
            unscheduled.remove(tid)
            made_progress = True

    if unscheduled:
        raise RuntimeError("Decoder deadlock: unmet predecessors; check BOM/flow.")

    first_start = min((s.start_min for s in sched), default=baseline)
    last_end    = max((s.end_min   for s in sched), default=baseline)
    makespan = last_end - first_start

    # availability minutes between first_start and last_end
    def working_available(a, b):
        t = align_to_working(day0, a, cal); total=0
        while t < b:
            day_idx = t // MINUTES_PER_DAY
            minute_in_day = t % MINUTES_PER_DAY
            blocks = working_blocks_for_day(day0, day_idx, cal)
            if not blocks:
                t = (day_idx+1)*MINUTES_PER_DAY; continue
            progressed=False
            for bl in blocks:
                if bl.end_min <= minute_in_day: continue
                if minute_in_day < bl.start_min:
                    t = day_idx*MINUTES_PER_DAY + bl.start_min
                    minute_in_day = bl.start_min
                window_end = min(b, day_idx*MINUTES_PER_DAY + bl.end_min)
                inc = max(0, window_end - (day_idx*MINUTES_PER_DAY + minute_in_day))
                total += inc
                t = window_end; minute_in_day = t % MINUTES_PER_DAY
                progressed=True
                if t >= b: break
            if not progressed:
                t = (day_idx+1)*MINUTES_PER_DAY
        return max(1, total)

    avail = working_available(first_start, last_end) if last_end>first_start else 1
    util = {m: (sum((s.end_min-s.start_min) for s in sched if s.machine==m) / avail) for m in machines.keys()}

    kpis = {
        "baseline_min": baseline,
        "makespan_min": makespan,
        "total_setup_min": total_setup,
        "machine_utilization": util
    }
    return sched, kpis

# =========================
# Tardiness (supports due_min or due_date)
# =========================
def minutes_since_day0(day0: date, dt: datetime) -> int:
    base = datetime.combine(day0, datetime.min.time())
    return int((dt - base).total_seconds() // 60)

def compute_tardiness(sched, tasks, product_last_idx_by_tag, due_working_by_tag, due_date_by_tag, day0, cal):
    task_by_id = {t.task_id: t for t in tasks}
    final_task_id_by_tag = {}
    for t in tasks:
        if t.idx_in_flow == product_last_idx_by_tag.get(t.tag, -999):
            final_task_id_by_tag[t.tag] = t.task_id

    last_end_by_tag: Dict[str, int] = defaultdict(int)
    for si in sched:
        t = task_by_id[si.task_id]
        if t.task_id == final_task_id_by_tag.get(t.tag):
            last_end_by_tag[t.tag] = max(last_end_by_tag[t.tag], si.end_min)

    baseline = align_to_working(day0, 0, cal)
    total_tardiness = 0
    for tag, end_t in last_end_by_tag.items():
        due_abs: Optional[int] = None
        if tag in due_date_by_tag:
            # รองรับ "YYYY-MM-DD HH:MM" หรือ "YYYY-MM-DDTHH:MM"
            dt_str = due_date_by_tag[tag].replace("T"," ")
            try:
                dt = datetime.fromisoformat(dt_str)
            except ValueError:
                # fallback basic
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            due_abs = minutes_since_day0(day0, dt)
        elif tag in due_working_by_tag:
            due_abs = add_working_minutes(day0, baseline, int(due_working_by_tag[tag]), cal)
        else:
            continue
        late = max(0, end_t - due_abs)
        total_tardiness += late

        final_id = final_task_id_by_tag.get(tag)
        if final_id is not None:
            for si2 in sched:
                if si2.task_id == final_id:
                    si2.late_min = late
                    break
    return total_tardiness

# =========================
# Fitness & GA loop
# =========================
def fitness_value(kpis, tardiness, cfg: GAConfig):
    return cfg.w_tardiness*tardiness + cfg.w_setup*kpis["total_setup_min"] + cfg.w_makespan*kpis["makespan_min"]

def evaluate_population(population, tasks, machines, setup_sd, speed, cal, day0, extra_preds, product_last_idx_by_tag, due_working_by_tag, due_date_by_tag, cfg):
    fits=[]; decodes=[]
    for ch in population:
        sched,k = build_schedule(tasks, machines, setup_sd, speed, ch.perm, ch.mach_assign, cal, day0, extra_preds)
        tard = compute_tardiness(sched, tasks, product_last_idx_by_tag, due_working_by_tag, due_date_by_tag, day0, cal)
        f = fitness_value(k, tard, cfg)
        fits.append(f); decodes.append((sched, {**k, "total_tardiness_min": tard}))
    return fits, decodes

def run_ga(tasks, machines, setup_sd, speed, cal, day0, extra_preds, product_last_idx_by_tag, due_working_by_tag, due_date_by_tag, cfg=GAConfig(), seed=None):
    rng=random.Random(seed if seed is not None else cfg.seed)
    population=init_population(rng, tasks, cfg)
    fits, decodes = evaluate_population(population, tasks, machines, setup_sd, speed, cal, day0, extra_preds, product_last_idx_by_tag, due_working_by_tag, due_date_by_tag, cfg)
    best_idx=min(range(len(population)), key=lambda i: fits[i])
    best=population[best_idx]; best_sched, best_k=decodes[best_idx]
    for _ in range(cfg.generations):
        new_pop=[]
        elites=[p for p,_ in sorted(zip(population,fits), key=lambda x:x[1])[:cfg.elite_count]]
        new_pop.extend(elites)
        while len(new_pop)<cfg.pop_size:
            p1=tournament_select(rng, population, fits, cfg.tournament_k)
            p2=tournament_select(rng, population, fits, cfg.tournament_k)
            c1,c2=p1,p2
            if rng.random()<cfg.crossover_rate:
                c1,c2=ox_crossover(rng,p1,p2)
            c1=mutate(rng,c1,tasks,cfg.mutation_rate)
            c2=mutate(rng,c2,tasks,cfg.mutation_rate)
            new_pop.append(c1)
            if len(new_pop)<cfg.pop_size: new_pop.append(c2)
        population=new_pop
        fits, decodes = evaluate_population(population, tasks, machines, setup_sd, speed, cal, day0, extra_preds, product_last_idx_by_tag, due_working_by_tag, due_date_by_tag, cfg)
        idx=min(range(len(population)), key=lambda i: fits[i])
        if fits[idx] < fits[best_idx]:
            best_idx=idx; best=population[idx]; best_sched, best_k=decodes[idx]
    return best, best_sched, best_k

# =========================
# I/O & CLI
# =========================
def minutes_to_dt_str(day0: date, t: int) -> str:
    return (datetime.combine(day0, datetime.min.time()) + timedelta(minutes=t)).strftime("%Y-%m-%d %H:%M")

def print_schedule(day0: date, sched: List[ScheduleItem]):
    cols=["task_id","order_id","product","process","machine","start","end","setup","late"]
    header="{:>7}  {:>8}  {:>10}  {:>8}  {:>7}  {:>16}  {:>16}  {:>5}  {:>5}".format(*cols)
    print(header); print("-"*len(header))
    for si in sorted(sched, key=lambda x: (x.machine, x.start_min)):
        print("{:7d}  {:>8}  {:>10}  {:>8}  {:>7}  {:>16}  {:>16}  {:>5}  {:>5}".format(
            si.task_id, si.order_id, si.product, si.process, si.machine,
            minutes_to_dt_str(day0, si.start_min),
            minutes_to_dt_str(day0, si.end_min),
            si.setup_min, si.late_min
        ))

def print_kpis(kpis: Dict[str, float]):
    print("\nKPI Summary")
    print("-----------")
    print(f"Makespan (min): {kpis['makespan_min']}")
    print(f"Total Setup (min): {kpis['total_setup_min']}")
    print(f"Total Tardiness (min): {kpis.get('total_tardiness_min', 0)}")
    print("Machine Utilization:")
    for m,u in kpis["machine_utilization"].items():
        print(f"  {m}: {u*100:.1f}%")

def save_artifacts(day0: date, sched: List[ScheduleItem], kpis: Dict[str,float], prefix="plan"):
    import csv, json as _json
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from datetime import datetime, timedelta

    csv_path = f"{prefix}_schedule.csv"
    json_path = f"{prefix}_kpis.json"
    png_path  = f"{prefix}_gantt.png"

    # CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["task_id","order_id","product","process","machine","start_min","end_min","start_ts","end_ts","setup_min","late_min"])
        for si in sched:
            w.writerow([
                si.task_id, si.order_id, si.product, si.process, si.machine,
                si.start_min, si.end_min,
                minutes_to_dt_str(day0, si.start_min),
                minutes_to_dt_str(day0, si.end_min),
                si.setup_min, si.late_min
            ])

    # KPI JSON
    with open(json_path, "w", encoding="utf-8") as f:
        _json.dump(kpis, f, indent=2)

    # Gantt (datetime axis)
    try:
        plt.figure(figsize=(11, 0.5*max(1,len(sched)) + 2))
        if sched:
            base_dt = datetime.combine(day0, datetime.min.time())
            rows = sorted(sched, key=lambda x: (x.machine, x.start_min))
            first_start = min(r.start_min for r in rows)
            last_end    = max(r.end_min   for r in rows)
            span_min    = max(1, last_end - first_start)
            span_hours  = span_min / 60.0

            for i, si in enumerate(rows):
                start_dt = base_dt + timedelta(minutes=si.start_min)
                end_dt   = base_dt + timedelta(minutes=si.end_min)
                width_days = (end_dt - start_dt).total_seconds() / 86400.0
                plt.barh(i, width_days, left=mdates.date2num(start_dt), align="center", edgecolor="black")

            plt.yticks(range(len(rows)), [f"{si.machine} | {si.order_id}:{si.product}:{si.process}" for si in rows])

            ax = plt.gca()
            ax.xaxis_date()
            if span_hours > 72:
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
            elif span_hours > 12:
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
            else:
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))
            ax.minorticks_off()
            plt.xlabel("Time")
            plt.title("GA Plan – BOM/Multi-line")
        else:
            plt.title("GA Plan – BOM/Multi-line (No Tasks)")
        plt.tight_layout()
        plt.savefig(png_path, dpi=150)
        plt.close()
    except Exception:
        png_path = ""

    return csv_path, json_path, png_path

# =========================
# API payload normalizer + calendar builder
# =========================
def _split_blocks_by_breaks(blocks: List[Tuple[int,int]], breaks: List[Tuple[int,int]]) -> List[Tuple[int,int]]:
    if not breaks: return blocks
    out=[]
    for s,e in blocks:
        segs=[(s,e)]
        for bs,be in breaks:
            new=[]
            for xs,xe in segs:
                if be<=xs or xe<=bs:
                    new.append((xs,xe))
                else:
                    if xs<bs: new.append((xs,bs))
                    if be<xe: new.append((be,xe))
            segs=new
        out.extend(segs)
    out.sort()
    return [(a,b) for a,b in out if b>a]

def calendar_from_json(dct) -> CalendarConfig:
    raw_wb = dct.get("weekday_blocks", {}) or {}
    breaks_raw = dct.get("breaks", []) or []

    def _to_min(x):
        if isinstance(x, str) and ":" in x:
            hh,mm = x.split(":"); return int(hh)*60+int(mm)
        return int(x)

    brks = [(_to_min(a), _to_min(b)) for a,b in breaks_raw]

    wb_tmp = {}
    for k, blocks in raw_wb.items():
        blks=[]
        for b in blocks:
            s,e = b[0], b[1]
            if isinstance(s,str) and ":" in s: s = parse_hhmm_to_min(s)
            if isinstance(e,str) and ":" in e: e = parse_hhmm_to_min(e)
            s,e = int(s), int(e)
            assert 0 <= s < e <= 24*60, f"Bad block {s}-{e} in weekday {k}"
            blks.append((s,e))
        blks.sort()
        wb_tmp[int(k)] = _split_blocks_by_breaks(blks, brks)

    # Auto-detect JSON 0=Sunday → map เป็น Python 0=Monday
    json_uses_sun0 = False
    if set(wb_tmp.keys()) & set(range(7)):
        day0_has = bool(wb_tmp.get(0))
        day1_has = bool(wb_tmp.get(1))
        day6_has = bool(wb_tmp.get(6))
        if (not day0_has and day1_has) or (not day6_has and day1_has):
            json_uses_sun0 = True

    wb = {}
    for dow, blks in wb_tmp.items():
        py_wd = (dow + 6) % 7 if json_uses_sun0 else dow  # Sun(0)->6, Mon(1)->0, ...
        wb.setdefault(py_wd, [])
        wb[py_wd].extend([ShiftBlock(s,e) for s,e in blks])

    return CalendarConfig(
        weekday_blocks = wb or CalendarConfig.default().weekday_blocks,
        holidays = dct.get("holidays", []),
        treat_weekend_as_off = bool(dct.get("treat_weekend_as_off", True))
    )

def pick_engine_view(raw: dict) -> dict:
    # 1) engine_v1 มาก่อน
    if isinstance(raw.get("engine_v1"), dict):
        return raw["engine_v1"]
    # 2) full ถ้าครบ key ที่ต้องใช้
    needed = {"process_defs","product_defs","orders","orders_multiline","machines","calendar"}
    if isinstance(raw.get("full"), dict) and needed.issubset(set(raw["full"].keys())):
        return raw["full"]
    # 3) ตรง ๆ
    return raw

def build_from_json(data):
    pdefs = data.get("process_defs", [])
    prods = data.get("product_defs", [])
    if not pdefs or not prods:
        raise ValueError("Input missing process_defs or product_defs; pass engine_v1 or include these fields.")

    process_defs={p["name"]: ProcessDef(p["name"], int(p["base_duration_min"]), list(p["compatible_machines"])) for p in pdefs}

    product_defs={}
    for p in prods:
        # process_plan ใน engine_v1 อาจเป็น list ของ string แล้ว
        plan = p["process_plan"]
        plan = [x if isinstance(x, str) else x.get("process") for x in plan]
        product_defs[p["name"]] = ProductDef(p["name"], list(plan), list(p.get("bom", [])))

    orders_single: List[OrderSingle] = []
    for o in data.get("orders", []):
        orders_single.append(OrderSingle(
            o["order_id"], o["product"], int(o["qty"]),
            o.get("due_min"), o.get("due_date")
        ))

    orders_multi: List[OrderMulti] = []
    for om in data.get("orders_multiline", []):
        lines=[{"product": l["product"], "qty": int(l["qty"])} for l in om.get("lines",[])]
        orders_multi.append(OrderMulti(om["order_id"], lines, om.get("due_min"), om.get("due_date")))

    machines={m["name"]: MachineDef(m["name"]) for m in data.get("machines", [])}
    setup_sd={tuple(x["key"]): int(x["value"]) for x in data.get("setup_sd", [])}
    speed={tuple(x["key"]): float(x["value"]) for x in data.get("speed", [])}
    cal = calendar_from_json(data.get("calendar", {}))
    return process_defs, product_defs, orders_single, orders_multi, machines, setup_sd, speed, cal

# =========================
# Main
# =========================
def main():
    ap = argparse.ArgumentParser(description="GA-only Planner with BOM + Multi-line Orders (DB/API friendly)")
    ap.add_argument("--input","-i", required=True, help="Path to JSON input (accepts {full,engine_v1})")
    ap.add_argument("--day0", default=None, help="YYYY-MM-DD baseline (default: today)")
    ap.add_argument("--prefix", default="plan_db", help="Output filename prefix")
    # GA overrides
    ap.add_argument("--pop_size", type=int, default=None)
    ap.add_argument("--generations", type=int, default=None)
    ap.add_argument("--tournament_k", type=int, default=None)
    ap.add_argument("--crossover_rate", type=float, default=None)
    ap.add_argument("--mutation_rate", type=float, default=None)
    ap.add_argument("--elite_count", type=int, default=None)
    ap.add_argument("--w_tardiness", type=float, default=None)
    ap.add_argument("--w_setup", type=float, default=None)
    ap.add_argument("--w_makespan", type=float, default=None)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    raw = json.load(open(args.input,"r",encoding="utf-8"))
    data = pick_engine_view(raw)
    process_defs, product_defs, orders_single, orders_multi, machines, setup_sd, speed, cal = build_from_json(data)

    # day0
    if args.day0:
        y,m,d = map(int, args.day0.split("-")); day0 = date(y,m,d)
    else:
        day0 = date.today()

    tasks, extra_preds, product_last_idx_by_tag, due_working_by_tag, due_date_by_tag = \
        build_tasks_with_bom(process_defs, product_defs, orders_single, orders_multi)

    cfg = GAConfig(
        pop_size      = args.pop_size      if args.pop_size      is not None else 80,
        generations   = args.generations   if args.generations   is not None else 200,
        tournament_k  = args.tournament_k  if args.tournament_k  is not None else 3,
        crossover_rate= args.crossover_rate if args.crossover_rate is not None else 0.9,
        mutation_rate = args.mutation_rate if args.mutation_rate is not None else 0.25,
        elite_count   = args.elite_count   if args.elite_count   is not None else 3,
        w_tardiness   = args.w_tardiness   if args.w_tardiness   is not None else 1.0,
        w_setup       = args.w_setup       if args.w_setup       is not None else 0.3,
        w_makespan    = args.w_makespan    if args.w_makespan    is not None else 0.2,
        seed          = args.seed          if args.seed          is not None else 123
    )

    best, sched, kpis = run_ga(
        tasks, machines, setup_sd, speed, cal, day0,
        extra_preds, product_last_idx_by_tag,
        due_working_by_tag, due_date_by_tag,
        cfg=cfg, seed=cfg.seed
    )

    tard = compute_tardiness(
        sched, tasks, product_last_idx_by_tag,
        due_working_by_tag, due_date_by_tag, day0, cal
    )
    kpis["total_tardiness_min"] = tard

    print("=== Best Schedule (BOM + Multi-line) – DB/API friendly ===")
    print_schedule(day0, sched)
    print_kpis(kpis)

    save_artifacts(day0, sched, kpis, prefix=args.prefix)

if __name__=="__main__":
    main()
