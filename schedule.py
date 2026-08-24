# -*- coding: utf-8 -*-
"""
Nöbet çizelgesi dağıtım algoritması (saf Python, test edilebilir).

- X Takibi: dahil olan (yasaklı olmayan) TÜM kişiler üzerinde temiz döngü;
  periyot = kişi sayısı (7 kişi -> 7 haftada bir herkes birer kez).
- Kanallar (NTV, Bloomberg, CNN, CNBC-e, A Para): adil round-robin - herkes her
  kanalı eşit yapar, aynı iş üst üste gelmez, kişi başına 1 kanal.
  Bloomberg ve CNBC-e "öncelikli": üst üste ASLA gelmez ve tek kanal kalır.
- Sonra UBB/TRT/Basın Özeti yerleşir.
- İzin: cerrahi overlay. Yeni kişi (yasağı yoksa) otomatik her işe dahil olur.
"""
from datetime import date, timedelta

LIGHT = {"CNN + YouTube", "NTV", "A Para"}
DEFAULT_PROTECTED = {"Bloomberg", "CNBC-e + Medya Özeti"}


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
    hard_conf = state.get("conflicts", []) or []
    soft_conf = state.get("softConflicts", []) or []
    leave = set(state.get("leave", []) or [])
    weeks = weeks_meta(state)

    Wmap = {t["name"]: _weight(t) for t in tasks}
    Wn = lambda n: Wmap.get(n, 5)
    task_by = {t["name"]: t for t in tasks}
    names = [t["name"] for t in tasks]
    channel_set = {t["name"] for t in tasks if t.get("channel")}
    protected = {t["name"] for t in tasks if t.get("protected") or t["name"] in DEFAULT_PROTECTED}

    default_cyclic = ["X Takibi", "NTV", "Bloomberg", "CNN + YouTube",
                      "CNBC-e + Medya Özeti", "A Para"]
    cyclic_tasks = [c for c in (state.get("cyclicTasks") or default_cyclic) if c in names]
    x_names = [c for c in cyclic_tasks if task_by.get(c, {}).get("exclusive")]
    x_name = x_names[0] if x_names else None
    channel_cyclic = [c for c in cyclic_tasks if c != x_name and c in channel_set]

    hard_map = {n: set() for n in names}
    for pr in hard_conf:
        a, b = pr[0], pr[1]
        if a in hard_map and b in hard_map:
            hard_map[a].add(b); hard_map[b].add(a)
    soft_map = {n: set() for n in names}
    for pr in soft_conf:
        a, b = pr[0], pr[1]
        if a in soft_map and b in soft_map:
            soft_map[a].add(b); soft_map[b].add(a)

    x_people = [p for p in people if (x_name is None or p not in excl.get(x_name, []))]

    non_cyclic = [t for t in tasks if t["name"] not in set(cyclic_tasks)]
    non_cyclic.sort(key=lambda t: (0 if hard_map[t["name"]] else 1,
                                   (t.get("count") or 1), -_weight(t)))

    taskCnt = {p: {n: 0 for n in names} for p in people}
    lastTW = {p: {} for p in people}
    prev_assign = {p: [] for p in people}
    warnings = []

    base_rows = []
    for wk in weeks:
        w = wk["idx"]
        assign = {p: [] for p in people}

        def do_assign(p, tname):
            assign[p].append(tname)
            taskCnt[p][tname] += 1
            lastTW[p][tname] = w

        def has_exclusive(p):
            return any(task_by.get(x, {}).get("exclusive") for x in assign[p])

        # ---- X TAKİBİ: temiz N-döngü ----
        if x_name and x_people:
            do_assign(x_people[w % len(x_people)], x_name)

        # ---- KANALLAR: haftalik eslestirme (tum kanallar yerlesir, ust uste yok, iyi yayilim) ----
        avail_ch = [p for p in people if not has_exclusive(p)]

        def _cand(ch, relax):
            cs = [p for p in avail_ch if p not in excl.get(ch, [])]
            if (not relax) or (ch in protected):
                cs = [p for p in cs if ch not in prev_assign[p]]  # ust uste yok
            cs.sort(key=lambda p: (taskCnt[p][ch], lastTW[p].get(ch, -999), people.index(p)))
            return cs

        matched = {}
        for _relax in (False, True):
            order2 = sorted(channel_cyclic, key=lambda ch: (0 if ch in protected else 1, len(_cand(ch, _relax))))
            res = {}
            used = set()

            def _bt(i):
                if i == len(order2):
                    return True
                ch = order2[i]
                for p in _cand(ch, _relax):
                    if p in used:
                        continue
                    res[ch] = p
                    used.add(p)
                    if _bt(i + 1):
                        return True
                    del res[ch]
                    used.discard(p)
                return False

            if _bt(0):
                matched = res
                if _relax:
                    warnings.append(f"Hafta {wk['no']}: kanal ust-uste kurali gevsetildi.")
                break
        if not matched:
            warnings.append(f"Hafta {wk['no']}: bazi kanallar yerlestirilemedi.")
        for ch, p in matched.items():
            do_assign(p, ch)

        # ---- DÖNGÜSEL OLMAYANLAR (UBB, TRT, Basın Özeti) ----
        def elig_nc(p, t, lv):
            if has_exclusive(p):
                return False
            if p in excl.get(t["name"], []):
                return False
            if t["name"] in assign[p]:
                return False
            for x in assign[p]:
                if x in hard_map[t["name"]]:
                    return False
            if t["name"] in prev_assign[p] and lv < 1:
                return False
            return True

        def key_nc(p, t):
            soft_pen = 1 if any(x in soft_map[t["name"]] for x in assign[p]) else 0
            lt = lastTW[p].get(t["name"], -999)
            return (taskCnt[p][t["name"]], len(assign[p]), soft_pen, lt, people.index(p))

        for t in non_cyclic:
            need = (t.get("count") or 1)
            placed = 0
            while placed < need:
                picked = None
                for lv in range(2):
                    c = [p for p in people if elig_nc(p, t, lv)]
                    if c:
                        c.sort(key=lambda p: key_nc(p, t))
                        picked = c[0]
                        break
                if picked is None:
                    warnings.append(f"Hafta {wk['no']}: '{t['name']}' yerleştirilemedi.")
                    break
                do_assign(picked, t["name"])
                placed += 1

        for p in people:
            prev_assign[p] = assign[p][:]
        base_rows.append({"no": wk["no"], "dateStr": wk["date"].strftime("%d.%m.%Y"),
                          "idx": w, "assign": {p: assign[p][:] for p in people}})

    # ---- İZİN OVERLAY (cerrahi) ----
    struck = {}
    rows = []
    for br in base_rows:
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

    counts = {p: {n: 0 for n in names} for p in people}
    totals = {p: 0 for p in people}
    for row in rows:
        for p in people:
            for tn in row["assign"].get(p, []):
                counts[p][tn] = counts[p].get(tn, 0) + 1
                totals[p] += 1

    return {"rows": rows, "struck": struck, "warnings": warnings,
            "counts": counts, "totals": totals, "people": people, "taskNames": names}


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
