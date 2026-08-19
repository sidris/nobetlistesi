"""
Nöbet çizelgesi dağıtım algoritması (saf Python, test edilebilir).
JS sürümünün birebir portu: X Takibi sabit-sıra çıpa, kanallar sırayla (haftalık
döndürülerek) eşit, round-robin (herkes sırayla eşit), üst üste aynı iş yok,
kişi başına 1 kanal, yasak/çakışma/eş kuralları, ağırlık (yalnız gösterim),
ve izin overlay'i (cerrahi: sadece izinlinin işleri boş/CNN-NTV-A Para'ya aktarılır).
"""
from datetime import date, timedelta

LIGHT = {"CNN + YouTube", "NTV", "A Para"}


def _weight(t):
    w = t.get("weight")
    return 5 if w is None else w


def weeks_meta(state):
    base = date.fromisoformat(state["startDate"])
    return [
        {"idx": w, "no": state["startWeekNo"] + w, "date": base + timedelta(days=7 * w)}
        for w in range(state["weekCount"])
    ]


def generate(state):
    people = list(state["people"])
    tasks = state["tasks"]
    excl = state.get("exclusions", {}) or {}
    conflicts = state.get("conflicts", []) or []
    peers = state.get("peers", []) or []
    gap = state.get("peerGap", 0) or 0
    pins = state.get("pins", {}) or {}
    leave = set(state.get("leave", []) or [])
    weeks = weeks_meta(state)

    Wmap = {t["name"]: _weight(t) for t in tasks}
    Wn = lambda n: Wmap.get(n, 5)
    conflict_map = {t["name"]: set() for t in tasks}
    for pr in conflicts:
        a, b = pr[0], pr[1]
        if a in conflict_map and b in conflict_map:
            conflict_map[a].add(b)
            conflict_map[b].add(a)
    channel_set = {t["name"] for t in tasks if t.get("channel")}
    DEFAULT_PROTECTED = {"Bloomberg", "CNBC-e + Medya Özeti"}
    protected_set = {t["name"] for t in tasks if t.get("protected") or t["name"] in DEFAULT_PROTECTED}

    singles = [t for t in tasks if not t.get("pair")]
    singles.sort(key=lambda t: (0 if t.get("exclusive") else 1,
                                0 if t.get("channel") else 1,
                                -_weight(t)))
    pair_tasks = [t for t in tasks if t.get("pair")]

    warnings = []

    def build_base(use_pins, collect_warn):
        task_cnt = {p: {t["name"]: 0 for t in tasks} for p in people}
        last_tw = {p: {} for p in people}
        prev_assign = {p: [] for p in people}
        pair_count = {f"{a}|{b}": 0 for a, b in peers}
        last_pair_week = {}
        x_ptr = [0]
        rows = []

        for wk in weeks:
            w = wk["idx"]
            this_week = {p: [] for p in people}
            has_excl = {}
            holders = {t["name"]: [] for t in tasks}
            pair_used = {}

            def valid(p, t, lv):
                if has_excl.get(p):
                    return False
                if t.get("exclusive") and this_week[p]:
                    return False
                if p in holders[t["name"]]:
                    return False
                if p in excl.get(t["name"], []):
                    return False  # yasak: hiç gevşemez
                # aynı iş iki hafta üst üste
                if t["name"] in prev_assign[p]:
                    if t["name"] in protected_set:
                        return False  # Bloomberg/CNBC-e: kesin, asla üst üste
                    elif lv < 1:
                        return False  # diğerleri: ilk gevşer (Mine+TRT üst üste olabilir)
                # çakışma
                if lv < 1:
                    for x in this_week[p]:
                        if x in conflict_map[t["name"]]:
                            return False
                # kişi başına 1 kanal
                if t.get("channel"):
                    exist = [x for x in this_week[p] if x in channel_set]
                    if exist:
                        if t["name"] in protected_set or any(x in protected_set for x in exist):
                            return False  # Bloomberg/CNBC-e tek kanal kalır: gevşemez
                        elif lv < 2:
                            return False  # diğer kanallar: en son gevşer
                return True

            def cmp_key(p, t):
                lt = last_tw[p].get(t["name"], -999)
                ww = sum(Wn(x) for x in this_week[p])
                return (task_cnt[p][t["name"]], lt, len(this_week[p]), ww, people.index(p))

            def pickS(t):
                for lv in range(3):
                    c = [p for p in people if valid(p, t, lv)]
                    if c:
                        if lv >= 2 and collect_warn:
                            warnings.append(f"Hafta {wk['no']}: “{t['name']}” için kişi-başına-1-kanal gevşetildi.")
                        c.sort(key=lambda p: cmp_key(p, t))
                        return c[0]
                return None

            def do_assign(p, t):
                this_week[p].append(t["name"])
                task_cnt[p][t["name"]] += 1
                last_tw[p][t["name"]] = w
                holders[t["name"]].append(p)
                if t.get("exclusive"):
                    has_excl[p] = True

            # pin fazı
            if use_pins:
                for t in tasks:
                    cap = 1 if t.get("channel") else (t.get("count") or 1)
                    for p in [x for x in pins.get(f"{w}::{t['name']}", []) if x in people]:
                        if not t.get("pair") and len(holders[t["name"]]) >= cap:
                            continue
                        if p in holders[t["name"]]:
                            continue
                        if has_excl.get(p):
                            continue
                        if t.get("exclusive") and this_week[p]:
                            continue
                        do_assign(p, t)

            excl_s = [t for t in singles if t.get("exclusive")]
            chan_s = [t for t in singles if t.get("channel") and not t.get("exclusive")]
            other_s = [t for t in singles if not t.get("channel") and not t.get("exclusive")]

            def pick_excl(t):
                n = len(people)
                for k in range(n):
                    idx = (x_ptr[0] + k) % n
                    p = people[idx]
                    if p in excl.get(t["name"], []):
                        continue
                    if has_excl.get(p):
                        continue
                    if this_week[p]:
                        continue
                    if p in holders[t["name"]]:
                        continue
                    x_ptr[0] = (idx + 1) % n
                    return p
                return None

            for t in excl_s:
                need = t.get("count") or 1
                while len(holders[t["name"]]) < need:
                    pk = pick_excl(t)
                    if pk is None:
                        if collect_warn:
                            warnings.append(f"Hafta {wk['no']}: “{t['name']}” atanamadı.")
                        break
                    do_assign(pk, t)

            sh = (w % len(chan_s)) if chan_s else 0
            rot_c = chan_s[sh:] + chan_s[:sh]
            for t in rot_c + other_s:
                need = 1 if t.get("channel") else (t.get("count") or 1)
                while len(holders[t["name"]]) < need:
                    pk = pickS(t)
                    if pk is None:
                        break
                    do_assign(pk, t)

            # çift işleri
            def pair_elig(pr, t, relax_gap):
                key = f"{pr[0]}|{pr[1]}"
                if pair_used.get(key):
                    return False
                for m in pr:
                    if m in excl.get(t["name"], []):
                        return False
                    if has_excl.get(m):
                        return False
                    if m in holders[t["name"]]:
                        return False
                    for x in this_week[m]:
                        if x in conflict_map[t["name"]]:
                            return False
                if (not relax_gap) and gap > 0 and key in last_pair_week and (w - last_pair_week[key]) < gap:
                    return False
                return True

            for t in pair_tasks:
                total_need = (t.get("count") or 1) * 2
                if len(holders[t["name"]]) > 0:
                    while len(holders[t["name"]]) < total_need:
                        c = [p for p in people if not has_excl.get(p) and p not in holders[t["name"]]]
                        if not c:
                            break
                        c.sort(key=lambda p: cmp_key(p, t))
                        do_assign(c[0], t)
                    continue
                pps = t.get("count") or 1
                for _ in range(pps):
                    picked = None
                    for rg in range(2):
                        if picked:
                            break
                        cand = [pr for pr in peers if pair_elig(pr, t, rg == 1)]
                        if cand:
                            cand.sort(key=lambda A: (pair_count[f"{A[0]}|{A[1]}"],
                                                     last_pair_week.get(f"{A[0]}|{A[1]}", -99),
                                                     peers.index(A)))
                            picked = cand[0]
                    if picked:
                        key = f"{picked[0]}|{picked[1]}"
                        for m in picked:
                            do_assign(m, t)
                        pair_used[key] = True
                        pair_count[key] += 1
                        last_pair_week[key] = w

            for p in people:
                prev_assign[p] = this_week[p][:]
            rows.append({"no": wk["no"], "dateStr": wk["date"].strftime("%d.%m.%Y"),
                         "idx": w, "assign": {p: this_week[p][:] for p in people}})
        return rows

    pinned_base = build_base(True, True)
    struck = {}  # elle taşımalar move_task ile eklenir (cerrahi)

    # izin overlay (cerrahi)
    rows = []
    for br in pinned_base:
        w = br["idx"]
        assign = {p: br["assign"][p][:] for p in people}
        on_leave = [p for p in people if f"{w}::{p}" in leave]
        for L in on_leave:
            tasks_L = assign[L][:]
            assign[L] = []
            for T in tasks_L:
                cand = [p for p in people if p not in on_leave and T not in assign[p]]
                if not cand:
                    continue
                is_chan = T in channel_set

                def has_chan(p):
                    return any(x in channel_set for x in assign[p])

                def tier(p):
                    if not assign[p]:
                        return 0
                    if any(x in LIGHT for x in assign[p]):
                        return 1
                    return 2

                def keyf(p):
                    ex = 1 if p in excl.get(T, []) else 0
                    ch = (1 if has_chan(p) else 0) if is_chan else 0
                    return (ex, ch, tier(p), len(assign[p]), people.index(p))

                cand.sort(key=keyf)
                assign[cand[0]].append(T)
        rows.append({"no": br["no"], "dateStr": br["dateStr"], "idx": w,
                     "assign": assign, "onLeave": on_leave})

    # sayımlar: herkes × her iş
    tnames = [t["name"] for t in tasks]
    counts = {p: {tn: 0 for tn in tnames} for p in people}
    totals = {p: 0 for p in people}
    for row in rows:
        for p in people:
            for tn in row["assign"].get(p, []):
                counts[p][tn] = counts[p].get(tn, 0) + 1
                totals[p] += 1

    return {
        "rows": rows,
        "struck": struck,
        "warnings": warnings,
        "counts": counts,
        "totals": totals,
        "people": people,
        "taskNames": tnames,
    }


def recompute_counts(sched):
    people = sched["people"]
    tnames = sched["taskNames"]
    counts = {p: {tn: 0 for tn in tnames} for p in people}
    totals = {p: 0 for p in people}
    for row in sched["rows"]:
        for p in people:
            for tn in row["assign"].get(p, []):
                counts[p][tn] = counts[p].get(tn, 0) + 1
                totals[p] += 1
    sched["counts"] = counts
    sched["totals"] = totals


def move_task(sched, w, task, from_p, to_p):
    """Elle taşıma: yalnızca bu tag'i taşır, başka hiçbir şeyi değiştirmez.
    Kaynakta üstü çizili iz bırakır. (None, err) döner."""
    row = next((r for r in sched["rows"] if r["idx"] == w), None)
    if row is None:
        return "Hafta bulunamadı."
    if from_p == to_p:
        return None
    if to_p in row.get("onLeave", []):
        return "İzinli kişiye taşınamaz."
    if task not in row["assign"].get(from_p, []):
        return "Bu iş kaynak kişide yok."
    if task in row["assign"].get(to_p, []):
        return "Hedefte zaten var."
    row["assign"][from_p] = [x for x in row["assign"][from_p] if x != task]
    row["assign"].setdefault(to_p, []).append(task)
    sched.setdefault("struck", {})
    sk = f"{w}::{from_p}"
    sched["struck"].setdefault(sk, [])
    if task not in sched["struck"][sk]:
        sched["struck"][sk].append(task)
    tk = f"{w}::{to_p}"
    if tk in sched["struck"] and task in sched["struck"][tk]:
        sched["struck"][tk] = [x for x in sched["struck"][tk] if x != task]
        if not sched["struck"][tk]:
            del sched["struck"][tk]
    recompute_counts(sched)
    return None
