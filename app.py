# -*- coding: utf-8 -*-
import io
import copy
from datetime import datetime, timezone

import streamlit as st

from schedule import generate, move_task, recompute_counts, weeks_meta

st.set_page_config(page_title="Nöbet Çizelgesi", page_icon="🗓️", layout="wide")

# ---------------- Giriş kapısı (görüntüleme şifresi) ----------------
# Şifre girilmeden hiçbir şey (çizelge/isimler) görünmez.
if not st.session_state.get("view_ok"):
    try:
        _want = st.secrets.get("VIEW_PASSWORD", "") or st.secrets.get("ADMIN_PASSWORD", "")
    except Exception:
        _want = ""
    st.markdown("## 🔒 Nöbet Çizelgesi")
    st.caption("Bu sayfayı görüntülemek için şifre girin.")
    _pw = st.text_input("Şifre", type="password", key="viewpw")
    if st.button("Giriş"):
        if _pw and _want and _pw == _want:
            st.session_state["view_ok"] = True
            st.rerun()
        else:
            st.error("Şifre yanlış.")
    st.stop()

# ---------------- Renkler ----------------
PALETTE = [
    ("#e7f0ff", "#1d4ed8"), ("#e6f7ef", "#0a7d52"), ("#fdeede", "#b54708"),
    ("#f3e8ff", "#7c3aed"), ("#ffe9ee", "#be123c"), ("#e3f6f8", "#0e7490"),
    ("#fff3cd", "#92600a"), ("#eaf0e1", "#3f6212"), ("#fde8f3", "#a3216b"),
    ("#e8ecfb", "#3730a3"), ("#e9f5e1", "#15803d"), ("#fdeae7", "#9a3412"),
]
PERSON_COLORS = ["#1d4ed8", "#0a7d52", "#b54708", "#7c3aed", "#be123c", "#0e7490",
                 "#92600a", "#3f6212", "#a3216b", "#3730a3", "#15803d", "#9a3412"]


def task_color(i):
    return PALETTE[i % len(PALETTE)]


# ---------------- Varsayılan durum ----------------
def default_state():
    return {
        "people": ["Özlem", "Batuhan", "Begüm", "Evrim", "Furkan", "Göksu", "Mine"],
        "tasks": [
            {"name": "Bloomberg", "count": 1, "weight": 10, "channel": True, "exclusive": False, "protected": True},
            {"name": "NTV", "count": 1, "weight": 3, "channel": True, "exclusive": False},
            {"name": "A Para", "count": 1, "weight": 5, "channel": True, "exclusive": False},
            {"name": "UBB", "count": 1, "weight": 5, "channel": False, "exclusive": False},
            {"name": "CNBC-e + Medya Özeti", "count": 1, "weight": 5, "channel": True, "exclusive": False, "protected": True},
            {"name": "CNN + YouTube", "count": 1, "weight": 5, "channel": True, "exclusive": False},
            {"name": "TRT", "count": 1, "weight": 5, "channel": False, "exclusive": False},
            {"name": "X Takibi", "count": 1, "weight": 10, "channel": False, "exclusive": True},
            {"name": "Basın Özeti", "count": 2, "weight": 5, "channel": False, "exclusive": False},
        ],
        "exclusions": {"UBB": ["Begüm", "Özlem"], "NTV": ["Mine"], "CNN + YouTube": ["Mine"],
                       "Bloomberg": ["Mine"], "CNBC-e + Medya Özeti": ["Mine"], "A Para": ["Mine"]},
        "conflicts": [["UBB", "CNBC-e + Medya Özeti"]],
        "softConflicts": [["UBB", "Bloomberg"]],
        "cyclicTasks": ["X Takibi", "NTV", "Bloomberg", "CNN + YouTube", "CNBC-e + Medya Özeti", "A Para"],
        "peers": [["Begüm", "Özlem"], ["Evrim", "Göksu"], ["Furkan", "Mine"]],
        "peerGap": 2,
        "startDate": "2026-06-15", "weekCount": 12, "startWeekNo": 24,
        "leave": [], "notes": {}, "schedule": None,
    }


def normalize(state):
    for t in state.get("tasks", []):
        t.setdefault("count", 1); t.setdefault("weight", 5)
        t.setdefault("channel", False); t.setdefault("exclusive", False)
        if "protected" not in t:
            t["protected"] = t["name"] in {"Bloomberg", "CNBC-e + Medya Özeti"}
        if t.get("channel"):
            t["count"] = 1  # kanal her zaman 1 kişi
    state.setdefault("exclusions", {}); state.setdefault("conflicts", [])
    state.setdefault("peers", []); state.setdefault("leave", []); state.setdefault("notes", {})
    # göç: UBB+Bloomberg artık soft; döngü listesi
    if "softConflicts" not in state:
        state["softConflicts"] = [["UBB", "Bloomberg"]]
        state["conflicts"] = [pr for pr in state.get("conflicts", []) if set(pr) != {"UBB", "Bloomberg"}]
    if "cyclicTasks" not in state:
        state["cyclicTasks"] = ["X Takibi", "NTV", "Bloomberg", "CNN + YouTube",
                                "CNBC-e + Medya Özeti", "A Para"]
    # geçersiz referansları temizle (silinmiş kişi/görev)
    vp = set(state.get("people", []))
    tn = {t["name"] for t in state.get("tasks", [])}
    state["exclusions"] = {k: [p for p in v if p in vp]
                           for k, v in state.get("exclusions", {}).items() if k in tn}
    state["conflicts"] = [pr for pr in state.get("conflicts", []) if pr[0] in tn and pr[1] in tn]
    state["softConflicts"] = [pr for pr in state.get("softConflicts", []) if pr[0] in tn and pr[1] in tn]
    state["peers"] = [pr for pr in state.get("peers", []) if pr[0] in vp and pr[1] in vp]
    state["leave"] = [k for k in state.get("leave", []) if k.split("::", 1)[-1] in vp]
    state["cyclicTasks"] = [c for c in state.get("cyclicTasks", []) if c in tn]
    state["notes"] = {k: v for k, v in state.get("notes", {}).items() if k.split("::", 1)[-1] in vp}
    return state


# ---------------- Supabase ----------------
@st.cache_resource
def get_sb():
    from supabase import create_client
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def load_state():
    try:
        sb = get_sb()
        res = sb.table("nobet_state").select("data").eq("id", "main").execute()
        if res.data and res.data[0].get("data"):
            return normalize({**default_state(), **res.data[0]["data"]})
        s = default_state()
        sb.table("nobet_state").upsert({"id": "main", "data": s}).execute()
        return s
    except Exception as e:
        st.session_state["_db_err"] = str(e)
        return normalize(default_state())


def save_state(state):
    try:
        sb = get_sb()
        sb.table("nobet_state").upsert({
            "id": "main", "data": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception as e:
        st.error(f"Kaydedilemedi: {e}")
        return False


# ---------------- Oturum ----------------
if "state" not in st.session_state:
    st.session_state["state"] = load_state()
if "unlocked" not in st.session_state:
    st.session_state["unlocked"] = False

S = st.session_state["state"]


def persist():
    save_state(S)


def week_labels():
    return [f"Hafta {wk['no']} - {wk['date'].strftime('%d.%m.%Y')}" for wk in weeks_meta(S)]


# ---------------- Başlık + kilit ----------------
c1, c2 = st.columns([3, 1])
with c1:
    st.title("🗓️ Nöbet Çizelgesi")
    st.caption("Haftalık görev dağıtımı · sırayla eşit · ortak")
with c2:
    if st.session_state["unlocked"]:
        st.success("Düzenleme açık")
        if st.button("🔒 Kilitle"):
            st.session_state["unlocked"] = False
            st.rerun()
    else:
        pw = st.text_input("Yönetici şifresi", type="password", label_visibility="collapsed",
                           placeholder="Yönetici şifresi")
        if st.button("🔓 Düzenle"):
            if pw and pw == st.secrets.get("ADMIN_PASSWORD", ""):
                st.session_state["unlocked"] = True
                st.rerun()
            else:
                st.error("Şifre yanlış.")

if st.session_state.get("_db_err"):
    st.warning("Veritabanına bağlanılamadı; yerel varsayılan gösteriliyor. "
               "Streamlit secrets'te SUPABASE_URL / SUPABASE_KEY / ADMIN_PASSWORD tanımlı mı? "
               f"({st.session_state['_db_err']})")

UNLOCKED = st.session_state["unlocked"]


# ---------------- Çizelge HTML ----------------
def render_schedule_html():
    sched = S.get("schedule")
    if not sched:
        st.info("Henüz çizelge oluşturulmadı. Düzenle → Oluştur & Kaydet.")
        return
    people = sched["people"]
    tnames = sched["taskNames"]
    tidx = {n: i for i, n in enumerate(tnames)}
    struck = sched.get("struck", {})
    notes = S.get("notes", {})

    def tag(name, kind=""):
        i = tidx.get(name, 0)
        bg, fg = task_color(i)
        if kind == "struck":
            return (f'<span style="display:inline-block;font-size:11px;padding:2px 7px;margin:2px;'
                    f'border-radius:6px;border:1px dashed #c7cfda;color:{fg};'
                    f'text-decoration:line-through;opacity:.55">{name}</span>')
        return (f'<span style="display:inline-block;font-size:11px;padding:2px 7px;margin:2px;'
                f'border-radius:6px;background:{bg};color:{fg};font-weight:600">{name}</span>')

    html = ['<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;font-family:sans-serif">']
    html.append('<tr><th style="border:1px solid #e3e8ef;padding:6px;background:#1f2a3d;color:#fff">Hf.</th>'
                '<th style="border:1px solid #e3e8ef;padding:6px;background:#2b3850;color:#fff">Tarih</th>')
    for p in people:
        html.append(f'<th style="border:1px solid #e3e8ef;padding:6px;background:#1f2a3d;color:#fff">{p}</th>')
    html.append('<th style="border:1px solid #e3e8ef;padding:6px;background:#1f2a3d;color:#fff">İzinler</th></tr>')

    for row in sched["rows"]:
        html.append('<tr>')
        html.append(f'<td style="border:1px solid #e3e8ef;padding:6px;text-align:center;font-weight:700;background:#f5f7fa">{row["no"]}</td>')
        html.append(f'<td style="border:1px solid #e3e8ef;padding:6px;color:#5f6b7c;background:#f9fafc;white-space:nowrap">{row["dateStr"]}</td>')
        for p in people:
            cell = ""
            if p in row.get("onLeave", []):
                cell = ('<span style="font-size:10px;font-weight:700;color:#b54708;background:#fff1e2;'
                        'border:1px dashed #e8b87e;padding:2px 6px;border-radius:5px">İZİNLİ</span>')
            else:
                for t in row["assign"].get(p, []):
                    cell += tag(t)
                for t in struck.get(f'{row["idx"]}::{p}', []):
                    if t not in row["assign"].get(p, []):
                        cell += tag(t, "struck")
            nt = notes.get(f'{row["idx"]}::{p}', "")
            if nt:
                cell += (f'<div style="font-size:10px;color:#6b5b2a;background:#fffbe9;border:1px solid #f0e2b0;'
                         f'border-radius:5px;padding:2px 5px;margin-top:3px">📝 {nt}</div>')
            html.append(f'<td style="border:1px solid #e3e8ef;padding:5px;vertical-align:top;min-width:110px">{cell}</td>')
        lv = ", ".join(row.get("onLeave", []))
        html.append(f'<td style="border:1px solid #e3e8ef;padding:6px;color:#b54708;background:#fcfaf5">{lv}</td>')
        html.append('</tr>')
    html.append('</table></div>')
    st.markdown("".join(html), unsafe_allow_html=True)

    if sched.get("warnings"):
        with st.expander(f"⚠️ {len(sched['warnings'])} uyarı (kurallar bazı haftalarda gevşetildi)"):
            for w in dict.fromkeys(sched["warnings"]):
                st.write("• " + w)


def render_balance():
    sched = S.get("schedule")
    if not sched:
        return
    import pandas as pd
    people = sched["people"]; tnames = sched["taskNames"]
    counts = sched.get("counts", {})
    data = []
    for p in people:
        rowd = {"Kişi": p}
        for tn in tnames:
            rowd[tn] = counts.get(p, {}).get(tn, 0)
        rowd["Toplam"] = sched.get("totals", {}).get(p, 0)
        data.append(rowd)
    df = pd.DataFrame(data).set_index("Kişi")
    st.markdown("#### Yük dengesi - herkesin her işi kaç kez yaptığı")
    st.dataframe(df, use_container_width=True)


# ---------------- Excel ----------------
def build_xlsx():
    from openpyxl import Workbook
    sched = S.get("schedule")
    wb = Workbook()
    ws = wb.active
    ws.title = "Çizelge"
    people = sched["people"]; tnames = sched["taskNames"]
    ws.append(["Hafta No", "Tarih"] + people + ["İzinler"])
    for row in sched["rows"]:
        line = [row["no"], row["dateStr"]]
        for p in people:
            if p in row.get("onLeave", []):
                base = "İZİNLİ"
            else:
                base = "\n".join(row["assign"].get(p, []))
            nt = S.get("notes", {}).get(f'{row["idx"]}::{p}', "")
            line.append((base + ("\n📝 " + nt if nt else "")) if base else ("📝 " + nt if nt else ""))
        line.append(", ".join(row.get("onLeave", [])))
        ws.append(line)
    ws2 = wb.create_sheet("Yük Dengesi")
    ws2.append(["Kişi"] + tnames + ["Toplam"])
    for p in people:
        ws2.append([p] + [sched.get("counts", {}).get(p, {}).get(tn, 0) for tn in tnames]
                   + [sched.get("totals", {}).get(p, 0)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ==================== SEKMELER ====================
tabs = st.tabs(["📋 Çizelge", "👥 Kişiler & Görevler", "⚖️ Kurallar",
                "🌴 İzinler & Notlar", "✋ Elle Atama", "⚙️ Ayarlar"])

# ---- Çizelge ----
with tabs[0]:
    render_schedule_html()
    st.divider()
    render_balance()
    if S.get("schedule"):
        st.download_button("📊 Excel'e aktar", data=build_xlsx(),
                           file_name="nobet_cizelgesi.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ---- Kişiler & Görevler ----
with tabs[1]:
    if not UNLOCKED:
        st.info("Düzenlemek için sağ üstten şifreyle açın.")
    else:
        import pandas as pd
        st.subheader("Kişiler")
        pdf = pd.DataFrame({"İsim": S["people"]})
        pdf2 = st.data_editor(pdf, num_rows="dynamic", use_container_width=True, key="ppl")
        st.subheader("Görevler")
        tdf = pd.DataFrame(S["tasks"])
        for c in ["count", "weight", "channel", "exclusive", "protected"]:
            if c not in tdf:
                tdf[c] = False if c in ("channel", "exclusive", "protected") else 0
        tdf = tdf.rename(columns={"name": "İş", "count": "kişi", "weight": "ağırlık",
                                  "channel": "kanal", "exclusive": "yalnız", "protected": "öncelikli"})
        tdf = tdf[["İş", "kişi", "ağırlık", "kanal", "yalnız", "öncelikli"]]
        tdf2 = st.data_editor(tdf, num_rows="dynamic", use_container_width=True, key="tsk",
                              column_config={
                                  "kanal": st.column_config.CheckboxColumn(),
                                  "yalnız": st.column_config.CheckboxColumn(),
                                  "öncelikli": st.column_config.CheckboxColumn(
                                      help="Bu iş üst üste aynı kişiye gelmez ve tek kanal kalır (ör. Bloomberg, CNBC-e)."),
                              })
        st.caption("kanal = her hafta 1 kişi, herkese sırayla. yalnız = o hafta başka iş almaz (ör. X Takibi). "
                   "öncelikli = üst üste asla gelmez + tek kanal kalır (kural gevşemelerinden muaf).")
        if st.button("💾 Kişiler & Görevleri kaydet"):
            S["people"] = [str(x).strip() for x in pdf2["İsim"].tolist() if str(x).strip()]
            new_tasks = []
            for _, r in tdf2.iterrows():
                nm = str(r["İş"]).strip()
                if not nm:
                    continue
                new_tasks.append({
                    "name": nm, "count": int(r["kişi"] or 1), "weight": int(r["ağırlık"] or 5),
                    "channel": bool(r["kanal"]), "exclusive": bool(r["yalnız"]),
                    "protected": bool(r["öncelikli"]),
                })
            S["tasks"] = new_tasks
            normalize(S)
            persist()
            st.success("Kaydedildi. Değişikliğin çizelgeye yansıması için 'Oluştur & Kaydet' yapın.")

# ---- Kurallar ----
with tabs[2]:
    if not UNLOCKED:
        st.info("Düzenlemek için şifreyle açın.")
    else:
        st.subheader("Kim hangi işi yapamaz (yasaklar)")
        changed = False
        for t in S["tasks"]:
            cur = [p for p in S["exclusions"].get(t["name"], []) if p in S["people"]]
            sel = st.multiselect(t["name"], S["people"], default=cur, key="ex_" + t["name"])
            if set(sel) != set(cur):
                if sel:
                    S["exclusions"][t["name"]] = sel
                else:
                    S["exclusions"].pop(t["name"], None)
                changed = True
        st.divider()
        st.subheader("Aynı kişide birleşmesin (çakışma)")
        tnames = [t["name"] for t in S["tasks"]]
        cc1, cc2, cc3 = st.columns([2, 2, 1])
        a = cc1.selectbox("İş A", tnames, key="cfa")
        b = cc2.selectbox("İş B", tnames, key="cfb")
        if cc3.button("Ekle", key="addcf"):
            if a != b and not any({a, b} == set(pr) for pr in S["conflicts"]):
                S["conflicts"].append([a, b]); changed = True
        for i, pr in enumerate(list(S["conflicts"])):
            cx1, cx2 = st.columns([4, 1])
            cx1.write(f"• {pr[0]} + {pr[1]}")
            if cx2.button("Kaldır", key="rmcf" + str(i)):
                S["conflicts"].pop(i); changed = True; st.rerun()
        st.divider()
        st.subheader("Peer (eş) çiftleri - çift işleri ve eş kuralı için")
        pp1, pp2, pp3 = st.columns([2, 2, 1])
        pa = pp1.selectbox("Kişi 1", S["people"], key="pra")
        pb = pp2.selectbox("Kişi 2", S["people"], key="prb")
        if pp3.button("Ekle", key="addpr"):
            if pa != pb and not any({pa, pb} == set(pr) for pr in S["peers"]):
                S["peers"].append([pa, pb]); changed = True
        for i, pr in enumerate(list(S["peers"])):
            px1, px2 = st.columns([4, 1])
            px1.write(f"• {pr[0]} & {pr[1]}")
            if px2.button("Kaldır", key="rmpr" + str(i)):
                S["peers"].pop(i); changed = True; st.rerun()
        S["peerGap"] = st.number_input("Eşler arası en az hafta", 0, 12, int(S.get("peerGap", 2)))
        if changed or st.button("💾 Kuralları kaydet"):
            persist()
            st.success("Kaydedildi. 'Oluştur & Kaydet' ile çizelgeye uygulayın.")

# ---- İzinler & Notlar ----
with tabs[3]:
    if not UNLOCKED:
        st.info("Düzenlemek için şifreyle açın.")
    else:
        st.subheader("İzinler")
        labels = week_labels()
        li1, li2, li3 = st.columns([2, 2, 1])
        wsel = li1.selectbox("Hafta", list(range(len(labels))), format_func=lambda i: labels[i], key="lvw")
        psel = li2.selectbox("Kişi", S["people"], key="lvp")
        if li3.button("İzin ekle"):
            k = f"{wsel}::{psel}"
            if k not in S["leave"]:
                S["leave"].append(k); persist()
                st.success("İzin eklendi. 'Oluştur & Kaydet' ile uygulanır.")
        for k in sorted(list(S["leave"])):
            wi, pn = k.split("::"); wi = int(wi)
            if wi < len(labels):
                lx1, lx2 = st.columns([4, 1])
                lx1.write(f"• {pn} - {labels[wi]}")
                if lx2.button("Kaldır", key="rmlv" + k):
                    S["leave"].remove(k); persist(); st.rerun()
        st.divider()
        st.subheader("Hücre notu")
        n1, n2 = st.columns(2)
        nw = n1.selectbox("Hafta", list(range(len(labels))), format_func=lambda i: labels[i], key="ntw")
        npn = n2.selectbox("Kişi", S["people"], key="ntp")
        nkey = f"{nw}::{npn}"
        ntext = st.text_area("Not", value=S["notes"].get(nkey, ""), key="nttext")
        nc1, nc2 = st.columns(2)
        if nc1.button("Notu kaydet"):
            if ntext.strip():
                S["notes"][nkey] = ntext.strip()
            else:
                S["notes"].pop(nkey, None)
            persist(); st.success("Not kaydedildi.")
        if nc2.button("Notu sil"):
            S["notes"].pop(nkey, None); persist(); st.rerun()

# ---- Elle Atama ----
with tabs[4]:
    if not UNLOCKED:
        st.info("Düzenlemek için şifreyle açın.")
    elif not S.get("schedule"):
        st.info("Önce Ayarlar → Oluştur & Kaydet.")
    else:
        st.caption("Bir işi bir kişiden diğerine taşı. Sadece o hücre değişir; "
                   "kaynağında üstü çizili iz kalır. (Yeniden hesaplama yok.)")
        labels = week_labels()
        sched = S["schedule"]
        mw = st.selectbox("Hafta", list(range(len(sched["rows"]))),
                          format_func=lambda i: f"Hafta {sched['rows'][i]['no']} - {sched['rows'][i]['dateStr']}", key="mvw")
        row = sched["rows"][mw]
        # o haftada atanmış (kişi, iş) çiftleri
        pairs = []
        for p in sched["people"]:
            for t in row["assign"].get(p, []):
                pairs.append((p, t))
        if not pairs:
            st.info("Bu haftada atama yok.")
        else:
            m1, m2 = st.columns(2)
            sel = m1.selectbox("Taşınacak iş (kimden)", list(range(len(pairs))),
                               format_func=lambda i: f"{pairs[i][1]}  ←  {pairs[i][0]}", key="mvsel")
            avail = [p for p in sched["people"] if p not in row.get("onLeave", [])
                     and p != pairs[sel][0] and pairs[sel][1] not in row["assign"].get(p, [])]
            to_p = m2.selectbox("Kime", avail, key="mvto") if avail else None
            if st.button("➡️ Taşı") and to_p:
                err = move_task(sched, row["idx"], pairs[sel][1], pairs[sel][0], to_p)
                if err:
                    st.warning(err)
                else:
                    persist(); st.success(f"{pairs[sel][1]} → {to_p}"); st.rerun()
        if st.button("↺ Elle taşımaları geri al (yeniden oluştur)"):
            res = generate(S)
            S["schedule"] = res; persist(); st.rerun()

# ---- Ayarlar ----
with tabs[5]:
    if not UNLOCKED:
        st.info("Düzenlemek için şifreyle açın.")
    else:
        a1, a2, a3 = st.columns(3)
        sd = a1.date_input("Başlangıç tarihi", value=datetime.fromisoformat(S["startDate"]).date(), key="set_sd")
        wc = a2.number_input("Hafta sayısı", 1, 104, int(S["weekCount"]), key="set_wc")
        sw = a3.number_input("İlk hafta no", 1, 53, int(S["startWeekNo"]), key="set_sw")

        def apply_settings():
            S["startDate"] = sd.isoformat(); S["weekCount"] = int(wc); S["startWeekNo"] = int(sw)
            S["leave"] = [k for k in S["leave"] if int(k.split("::")[0]) < S["weekCount"]]

        if st.button("Ayarları kaydet"):
            apply_settings()
            persist(); st.success("Ayarlar kaydedildi.")
        st.divider()
        st.subheader("Çizelgeyi oluştur")
        st.caption("Ekrandaki güncel ayar ve kurallarla baştan üretir (izin devri dahil). "
                   "Elle taşımalar sıfırlanır.")
        if st.button("🔄 Oluştur & Kaydet", type="primary"):
            apply_settings()          # ekrandaki güncel ayarları uygula
            normalize(S)
            res = generate(S)
            S["schedule"] = res
            persist()
            st.success(f"Çizelge oluşturuldu ve kaydedildi. "
                       f"({S['weekCount']} hafta, ilk hafta no {S['startWeekNo']}, "
                       f"başlangıç {datetime.fromisoformat(S['startDate']).strftime('%d.%m.%Y')})")
