"""Fragen-Archiv von "Quiz um Fünf": merkt sich jede gesendete Frage und Behauptung und sorgt fuer Abwechslung.

Das Archiv liegt in diesem Repository im Ordner archiv/: eine Datei je Folge (qz_NNN.json), der Themen-Vorrat (vorrat.json)
und lesbare Listen (UEBERSICHT.md, monate/JJJJ-MM.md). Es wird an drei Stellen benutzt - ueberall derselbe Code:
  1. vor dem Schreiben:  python3 -I tools/quiz_archiv.py plan --id qz_NNN [--kat Erdkunde,Natur] [--feld Hauptst] [--n 45] [--zug 2]
        -> gesperrte Themen, Stand der Kategorien, frisch gezogene unbenutzte Stichworte aus dem Vorrat
  2. vor dem Bau:        python3 -I tools/quiz_archiv.py check <folge.json>            (quiz_build.sh ruft das selbst auf)
        -> Fehlercode 2, wenn eine Frage schon einmal dran war (auch umformuliert oder als Behauptung) oder ein Thema zu frueh wiederkommt
  3. beim Einreichen:    python3 -I tools/quiz_archiv.py export <folge.json> --datum JJJJ-MM-TT
        -> schreibt archiv/<id>.json und die Listen. Ohne diesen Eintrag laedt tools/yt_queue.py nichts hoch,
           und yt_queue.py prueft den Eintrag vor dem Upload noch einmal gegen das Archiv (letzte Sperre).
Weitere Befehle:
  suche <Wort> [<Wort> ...]                  alle gespeicherten Fragen zu einem Stichwort (findet auch Mehrzahl und Zusammensetzungen)
  vorrat-neu <Kategorie> <Feld> "A; B; C"    neue Stichworte in den Themen-Vorrat (Doppelte und schon Verbrauchte werden uebersprungen)
  stand                                      Zahlen als JSON
  selbsttest
Option --archiv <Ordner>: anderer Archiv-Ordner (fuer Tests). Nur Standardbibliothek; laeuft lokal und in GitHub Actions.
"""
import json, math, random, re, sys, unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path

HIER = Path(__file__).resolve().parent
ARCHIV = HIER.parent / "archiv"
SPERRE = 30            # so viele Folgen lang darf dasselbe Thema nicht wiederkommen (rund fuenf Wochen)
DOPPELT = 0.70         # ab dieser Aehnlichkeit gilt eine Frage als schon gesendet (Fehler)
AEHNLICH = 0.50        # ab hier Hinweis: aehnliche Frage, bitte ansehen
NEUESTE = 12           # so viele Folgen stehen ausfuehrlich in UEBERSICHT.md, alle Folgen in monate/
KATEGORIEN = ("Erdkunde", "Geschichte", "Natur", "Wissenschaft", "Sprache", "Kultur", "Sport", "Alltag", "Technik", "Musik",
              "Mathematik", "Körper", "Weltall")          # muessen den Symbolen der Video-Vorlage entsprechen


class ArchivFehler(Exception):
    pass


def norm(text):
    """klein; Umlaute und Akzente auf den Grundbuchstaben (Vögel -> vogel, damit Einzahl und Mehrzahl zusammenfinden); ß -> ss"""
    t = unicodedata.normalize("NFKD", str(text or "").lower().replace("ß", "ss"))
    return "".join(c for c in t if not unicodedata.combining(c))

def _menge(s):
    return set(norm(s).split())

STOP = _menge("""der die das den dem des ein eine einen einem einer eines und oder aber auch nur noch schon sehr mehr als wie was wer wen wem wo
wann warum weshalb wozu wofür woraus worin welche welcher welches welchem welchen wieviel viele viel ist sind war waren wird werden wurde wurden
worden hat haben hatte hatten kann können konnte man es er sie wir ihr ihre ihren ihrem ihrer sein seine seinen seinem seiner im in an am auf aus
bei mit nach von vom zu zum zur über unter vor für durch um gegen ohne bis seit nicht kein keine keinen dass ob wenn weil dieser diese dieses
diesem diesen heute rund etwa fast genau eigentlich heißt nennt gilt gibt liegt steht kommt macht dabei dafür dagegen damit daher dort hier so
da je pro sich wohl zwar denn doch nun dann davon dazu darin also bereits allein allerdings trotzdem zugleich jedoch immer oft meist sogar
deshalb ihn ihm uns unser unsere unseren unseres unserem unserer dich dir du deine dein mal beim ins zwischen während sowie ganz gar
bekannt jeder jede jedes jedem jeden alle allen aller etwas nichts selbst beide beiden einmal zweimal""")
GENERISCH = _menge("""land länder stadt städte welt erde jahr jahre jahren tier tiere mensch menschen deutschland deutsch deutsche deutschen groß
größte größter größtes klein kleinste hoch höchste höchster lang längste erste ersten erster name zahl teil zeit art arten leben lebt
gehört besteht bestehen stammt ursprünglich botanisch üblicherweise freier wildbahn frei genannt heute meter kilometer prozent millionen
million grad tag tage stunden minuten sekunden europa europas weltweit erdteil fläche einwohner farbe wort begriff frage dieser folgenden
viele wenige neu alt alte neue lange kurz gut liter kilo tonnen etwa wurde stamm bedeutet nutzt nutzen braucht brauchen hatte trägt trugen
gebaut liegt fließt leben schnell schnellste zählt gehören ganze halbe mehr weniger gleich gleiche anderen andere eigene eigenen
berühmt berühmte berühmteste bekannteste häufig häufigste meisten ungefähr""")
ZAHLWORT = {norm(k): v for k, v in {"null": "0", "eins": "1", "zwei": "2", "drei": "3", "vier": "4", "fünf": "5", "sechs": "6", "sieben": "7",
            "acht": "8", "neun": "9", "zehn": "10", "elf": "11", "zwölf": "12", "zwanzig": "20", "dreißig": "30", "vierzig": "40",
            "fünfzig": "50", "hundert": "100", "tausend": "1000"}.items()}
REKORD = tuple(norm(w) for w in ("größt", "höchst", "längst", "schnellst", "kleinst", "tiefst", "ältest", "schwerst", "kürzest",
                                 "langlebigst", "bevölkerungsreichst", "meisten"))
ENDUNG = frozenset(("e", "n", "s", "en", "er", "es", "em", "ern", "nen", "innen"))      # Beugungsendungen


@lru_cache(maxsize=None)
def stamm(w):
    if w.isdigit() or len(w) <= 4: return w
    for suf in ("innen", "ern", "en", "er", "es", "em", "e", "n", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4: return w[: -len(suf)]
    return w

GEN = {stamm(w) for w in GENERISCH}

def woerter(text):
    """Text -> Liste der Woerter ohne Fuellwoerter (Zahlwoerter als Ziffern; jede Wortform nur einmal)."""
    t = re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", norm(text))                # 1.440 -> 1440
    out = []
    for w in re.findall(r"[a-z0-9]+", t):
        if w in STOP: continue
        w = ZAHLWORT.get(w, w)
        if len(w) < 3 and not w.isdigit(): continue
        if not any(stamm(w) == stamm(u) for u in out): out.append(w)
    return out

def thema_woerter(text):
    """Thema oder Name -> Woerter. Anders als im Fliesstext zaehlen hier auch kurze Bestandteile (Vitamin C, K2, Ei)
    und Namen, die wie Fuellwoerter aussehen (die Fluesse Oder und Seine)."""
    roh = [ZAHLWORT.get(w, w) for w in re.findall(r"[a-z0-9]+", norm(text))]
    out = []
    for w in ([w for w in roh if w not in STOP] or roh):
        if not any(stamm(w) == stamm(u) for u in out): out.append(w)
    return out

def wortgleich(a, b):
    """Dasselbe Wort, hoechstens anders gebeugt: Wal/Wale, Pinguin/Pinguinen, großen/großer. Schwein und Schweiz bleiben verschieden."""
    if a == b: return True
    if a.isdigit() or b.isdigit(): return False
    kurz, lang = (a, b) if len(a) <= len(b) else (b, a)
    if len(kurz) < 3: return False                                    # ganz kurze Woerter (Ei, K2, Pi) nur bei voelliger Gleichheit
    if lang.startswith(kurz) and lang[len(kurz):] in ENDUNG: return True
    return len(stamm(a)) >= 5 and stamm(a) == stamm(b)                # kurze Staemme taeuschen (Lachs/lachen)

def gleich(a, b):
    """Wortgleich oder Anfang einer Zusammensetzung (Sonne/Sonnenlicht) - der weitere Vergleich fuer Fragetexte."""
    if wortgleich(a, b): return True
    kurz, lang = (a, b) if len(a) <= len(b) else (b, a)
    return len(kurz) >= 5 and not kurz.isdigit() and lang.startswith(kurz)

def schluessel(t):
    """Suchschluessel eines Wortes. Zwei Woerter, die 'gleich' sind, haben immer mindestens einen Schluessel gemeinsam."""
    if t.isdigit(): return ["z" + t]
    if len(t) < 3: return ["k" + t]
    ks = ["5" + t[:5]] if len(t) >= 5 else []
    for e in ("", *ENDUNG):
        if t.endswith(e) and 3 <= len(t) - len(e) <= 4: ks.append("k" + t[: len(t) - len(e)])
    return ks

def markant(t):
    """Traegt das Wort Inhalt? (kein Allerweltswort, keine kleine Zahl)"""
    return stamm(t) not in GEN and not (t.isdigit() and len(t) < 3)

def paare(X, Y):
    """Ordnet Woerter aus X den gleichbedeutenden aus Y zu - jedes Wort aus Y hoechstens einmal."""
    frei = list(range(len(Y))); out = []
    for t in X:
        p = t[:3]
        for j in frei:
            if Y[j][:3] == p and gleich(t, Y[j]):
                out.append((t, Y[j])); frei.remove(j); break
    return out

def einheit(fr):
    """Archiv-Zeile oder Frage -> Wortlisten: Q Frage, A Antwort, K Kern (Frage + Antwort), F Erklaerung, T Thema."""
    a = str(fr.get("a") or "")
    Q = woerter(fr.get("q")); A = [] if a.lower() in ("wahr", "falsch", "") else (woerter(a) or thema_woerter(a))
    K = Q + [t for t in A if t not in Q]
    return {"Q": Q, "A": A, "K": K, "F": woerter(fr.get("fakt")), "T": thema_woerter(fr.get("thema"))}

def fragen_aus_folge(ep):
    """Folgen-Datei (episodes/qz_NNN.json) -> Archiv-Zeilen."""
    tf = ep.get("format") == "wahr_falsch"; out = []; n = 0
    for r in ep.get("rounds", []):
        for q in r.get("questions", []):
            n += 1; ans = q.get("answer")
            if tf: a = "wahr" if (ans is True or (ans == 0 and ans is not False)) else "falsch"      # true/false; als Zahl: 0 = wahr
            else:
                try: a = q["opts"][ans]
                except Exception: a = ""
            out.append({"n": n, "kat": q.get("cat", ""), "thema": str(q.get("thema", "")).strip(), "q": q.get("q", ""), "a": a, "fakt": q.get("fact", "")})
    return out

def nummer(folge_id):
    m = re.search(r"(\d+)", str(folge_id or "")); return int(m.group(1)) if m else 0

def lade_archiv(ordner=None, ohne=None):
    """Archiv-Eintraege, aelteste zuerst. 'ohne' = die gerade gepruefte Folge: sie selbst und alle spaeteren zaehlen nicht mit."""
    ordner = Path(ordner or ARCHIV); out = []; grenze = nummer(ohne)
    for p in sorted(ordner.glob("qz_*.json")):
        try: e = json.loads(p.read_text())
        except ValueError: raise ArchivFehler(f"Archiv-Datei {p.name} ist beschaedigt (kein gueltiges JSON) - aus dem Repository wiederherstellen: git checkout origin/main -- archiv/{p.name}")
        if ohne and (e.get("id") == ohne or (grenze and e.get("nr", 0) >= grenze)): continue
        out.append(e)
    out.sort(key=lambda e: (e.get("nr", 0), e.get("id", "")))
    return out

class Gewicht:
    """Seltene Woerter zaehlen mehr als haeufige (Oktopus sagt mehr als Tier)."""
    def __init__(self, einheiten):
        self.n = max(1, len(einheiten)); self.df = {}
        for u in einheiten:
            for t in {stamm(t) for t in u["K"] + u["F"]}: self.df[t] = self.df.get(t, 0) + 1
    def __call__(self, t):
        w = 1.0 + math.log((self.n + 1) / (self.df.get(stamm(t), 0) + 1))
        if stamm(t) in GEN: w *= 0.3
        if t.isdigit(): w *= 0.45 if len(t) < 3 else 0.9
        return w
    def summe(self, T): return sum(self(t) for t in T)

class Index:
    """Findet zu einer Frage sofort die gespeicherten Fragen, die ueberhaupt ein Stichwort mit ihr teilen -
    so bleibt die Pruefung auch mit vielen tausend gespeicherten Fragen schnell."""
    def __init__(self, einheiten):
        self.alle, self.mark, self.thema = {}, {}, {}
        for i, u in enumerate(einheiten):
            for t in set(u["K"] + u["F"]):
                m = markant(t)
                for k in schluessel(t):
                    self.alle.setdefault(k, set()).add(i)
                    if m: self.mark.setdefault(k, set()).add(i)
            for t in u["T"]:
                for k in schluessel(t): self.thema.setdefault(k, set()).add(i)
    def kandidaten(self, x):
        """gespeicherte Fragen, die mit x mindestens ein markantes Wort teilen (alle anderen haben Aehnlichkeit 0)"""
        out = set()
        for t in set(x["K"] + x["F"]):
            m = markant(t)
            for k in schluessel(t):
                out |= self.mark.get(k, set())
                if m: out |= self.alle.get(k, set())
        return sorted(out)
    def themen(self, T):
        out = set()
        for t in T:
            for k in schluessel(t): out |= self.thema.get(k, set())
        return sorted(out)
    def mit(self, t):
        out = set()
        for k in schluessel(t): out |= self.alle.get(k, set()) | self.thema.get(k, set())
        return sorted(out)

def aehnlichkeit(x, y, W):
    """0..1: wie sehr fragt x dasselbe Wissen ab wie y. Verglichen wird Frage + Antwort (Kern), auch gegen die Erklaerung
    der anderen Frage - so faellt auf, wenn eine Behauptung nur eine fruehere Erklaerung wiederholt.
    Eine Dopplung braucht mindestens zwei gemeinsame markante Woerter (Oktopus + Herzen), ein einzelnes (grenzt) reicht nicht."""
    kx, ky = x["K"], y["K"]
    if not kx or not ky: return 0.0, []
    fx = kx + [t for t in x["F"] if not any(gleich(t, u) for u in kx)]
    fy = ky + [t for t in y["F"] if not any(gleich(t, u) for u in ky)]
    thema_trifft = bool((y["T"] and len(paare(y["T"], fx)) == len(y["T"])) or (x["T"] and len(paare(x["T"], fy)) == len(x["T"])))
    def teil(A, B, nenner_menge, faktor, mind=1):
        p = paare(A, B)
        if len(p) < mind: return 0.0, []
        w = sum(min(W(t), W(u)) for t, u in p) / max(1e-9, W.summe(nenner_menge))
        d = sum(1 for t, _ in p if markant(t)); kern_markant = sum(1 for t in nenner_menge if markant(t))
        if d == 0: return 0.0, []
        if d == 1 and (kern_markant > 2 or not thema_trifft): w = min(w, 0.49 / faktor)   # nur ein gemeinsames Stichwort und anderes Thema: keine Dopplung
        return min(1.0, w) * faktor, [t for t, _ in p]
    kleiner = kx if W.summe(kx) <= W.summe(ky) else ky
    voll_kleiner = fx if W.summe(fx) <= W.summe(fy) else fy
    # Kern gegen Kern; Kern gegen den ganzen Text der anderen (Behauptung wiederholt eine Erklaerung); Text gegen Text nur als Hinweis
    kandidaten = [teil(kx, ky, kleiner, 1.0), teil(kx, fy, kx, 0.9, 2), teil(ky, fx, ky, 0.9, 2), teil(fx, fy, voll_kleiner, 0.65, 3)]
    s, g = max(kandidaten, key=lambda k: k[0])
    if x["A"] and y["A"] and len(paare(x["A"], y["A"])) == len(x["A"]) == len(y["A"]) and any(markant(t) for t in x["A"]):
        qg = paare(x["Q"], y["Q"])                                   # gleiche Antwort und verwandte Frage
        if sum(min(W(t), W(u)) for t, u in qg) / max(1e-9, min(W.summe(x["Q"]), W.summe(y["Q"]))) >= 0.3: s = max(s, 0.75)
    return s, g

def thema_bezug(x, y):
    """Verhaeltnis der Themen zweier Fragen: 2 = dasselbe Thema, 1 = verwandt (bitte ansehen), 0 = verschieden.
    Dasselbe Thema: gleiche Stichworte, auch gebeugt (Pinguin/Pinguine). Geht ein Thema nur im anderen auf (Everest in Mount Everest,
    Sonne in Sonnenlicht), ist es dasselbe, wenn die Frage zum laengeren Thema das kuerzere auch woertlich nennt ("Das Licht der Sonne ...");
    sonst gilt es nur als verwandt (Sonne/Sonnenblume, Wasser/Wasserstoff)."""
    a, b = x["T"], y["T"]
    if not a or not b: return 0
    if len(a) == len(b) and all(any(wortgleich(t, u) for u in b) for t in a): return 2
    bezug = 0
    for kurz, lang, text in ((a, b, y["K"] + y["F"]), (b, a, x["K"] + x["F"])):
        if len(kurz) <= len(lang) and all(any(gleich(t, u) for u in lang) for t in kurz):
            if all(any(wortgleich(t, w) for w in text) for t in kurz): return 2
            bezug = 1
    return bezug

def pruefe(neu_id, neu, archiv, streng=True, thema_folge=""):
    """Vergleicht die Fragen einer Folge mit dem Archiv und untereinander. -> (fehler, hinweise) als Textlisten."""
    alt = [(e, fr, einheit(fr)) for e in archiv for fr in e.get("fragen", [])]
    eigene = [(fr, einheit(fr)) for fr in neu]
    W = Gewicht([u for _, _, u in alt] + [u for _, u in eigene])
    idx = Index([u for _, _, u in alt])
    letzte = {e["id"] for e in archiv[-SPERRE:]}
    fehler, hinweise = [], []
    for i, (fr, x) in enumerate(eigene):
        nr = f"F{fr.get('n', i + 1)}"; kurz = str(fr.get("q", ""))[:70]
        if streng and not x["T"]:
            fehler.append(f"{nr}: Feld 'thema' fehlt - das Stichwort, unter dem man die Antwort im Lexikon nachschlagen wuerde (z. B. \"Zugspitze\") - {kurz}")
        beste = (0.0, None); werte = {}
        for j in idx.kandidaten(x):
            s, _ = aehnlichkeit(x, alt[j][2], W); werte[j] = s
            if s > beste[0]: beste = (s, j)
        for j in idx.themen(x["T"]):
            e, fa, y = alt[j]; bezug = thema_bezug(x, y)
            if not bezug: continue
            wo = f"{e['id']} F{fa.get('n')}: {str(fa.get('q', ''))[:70]}"
            if bezug == 2:
                if e["id"] in letzte: fehler.append(f"{nr}: Thema „{fr.get('thema')}“ kam erst in {wo} - fruehestens nach {SPERRE} Folgen wieder")
                elif werte.get(j, 0.0) < DOPPELT: hinweise.append(f"{nr}: Thema „{fr.get('thema')}“ gab es schon in {wo} - nur mit ganz anderem Inhalt verwenden")
            elif e["id"] in letzte and werte.get(j, 0.0) < AEHNLICH:
                hinweise.append(f"{nr}: Thema „{fr.get('thema')}“ ist verwandt mit „{fa.get('thema')}“ ({wo}) - geht es um dasselbe, ersetzen")
        s, j = beste
        if j is not None:
            e, fa, _ = alt[j]; wo = f"{e['id']} F{fa.get('n')}: {str(fa.get('q', ''))[:80]} -> {fa.get('a')}"
            if s >= DOPPELT: fehler.append(f"{nr}: schon gesendet ({s:.2f}) - {kurz} | war: {wo}")
            elif s >= AEHNLICH: hinweise.append(f"{nr}: aehnlich ({s:.2f}) - {kurz} | war: {wo}")
        for k in range(i):                                           # innerhalb der Folge
            fb, y = eigene[k]; s, _ = aehnlichkeit(x, y, W)
            nb = f"F{fb.get('n', k + 1)}"
            bezug = thema_bezug(x, y)
            if bezug == 2: fehler.append(f"{nr}: Thema „{fr.get('thema')}“ steht in dieser Folge schon bei {nb} („{fb.get('thema')}“)")
            elif s >= DOPPELT: fehler.append(f"{nr}: fragt fast dasselbe wie {nb} in dieser Folge ({s:.2f})")
            elif s >= AEHNLICH: hinweise.append(f"{nr}: aehnelt {nb} in dieser Folge ({s:.2f})")
            elif bezug == 1: hinweise.append(f"{nr}: Thema „{fr.get('thema')}“ ist verwandt mit „{fb.get('thema')}“ bei {nb} - geht es um dasselbe, ersetzen")
    rek = [fr for fr, _ in eigene if any(r in " ".join(woerter(fr.get("q"))) for r in REKORD)]
    if eigene and len(rek) > 0.34 * len(eigene):
        hinweise.append(f"{len(rek)} von {len(eigene)} Fragen fragen nach einem Rekord (groesste, hoechste, schnellste ...) - Frageformen abwechseln")
    if eigene and re.search(r"gemischt|allgemeinwissen", norm(thema_folge)):
        kat = {}
        for fr, _ in eigene: kat[fr.get("kat")] = kat.get(fr.get("kat"), 0) + 1
        top = max(kat, key=kat.get)
        if len(kat) < 6: hinweise.append(f"gemischte Folge mit nur {len(kat)} Kategorien - mindestens sechs verwenden")
        if kat[top] > 0.34 * len(eigene): hinweise.append(f"gemischte Folge, aber {kat[top]} von {len(eigene)} Fragen aus {top} - breiter streuen")
    seen = set(); fehler = [f for f in fehler if not (f in seen or seen.add(f))]
    return fehler, hinweise

def pruefe_eintrag(pfad, ordner=None):
    """Fuer tools/yt_queue.py: Archiv-Eintrag gegen alle frueheren pruefen. -> Liste der Fehler (leer = darf hochgeladen werden)."""
    e = json.loads(Path(pfad).read_text())
    if not e.get("fragen"): return ["Archiv-Eintrag enthaelt keine Fragen"]
    fehler, _ = pruefe(e.get("id"), e["fragen"], lade_archiv(ordner or Path(pfad).parent, ohne=e.get("id")))
    return fehler

# ---------------------------------------------------------------- Vorrat und Planung

def lade_vorrat(ordner=None, roh=False):
    p = Path(ordner or ARCHIV) / "vorrat.json"
    if not p.exists(): return {} if not roh else {"kategorien": {}}
    try: v = json.loads(p.read_text())
    except ValueError: raise ArchivFehler("archiv/vorrat.json ist beschaedigt (kein gueltiges JSON) - wiederherstellen: git checkout origin/main -- archiv/vorrat.json")
    return v if roh else v.get("kategorien", {})

def verbraucht(stichwort, alt, idx):
    """Ein Stichwort aus dem Vorrat gilt als verbraucht, wenn es Thema einer gespeicherten Frage war oder die Antwort einer Frage ist."""
    t = thema_woerter(stichwort)
    if not t: return True
    for j in idx.themen(t):
        T = alt[j]["T"]
        if T and len(t) >= len(T) and all(any(wortgleich(a, b) for b in t) for a in T): return True
    for j in idx.mit(t[0]):
        if all(any(wortgleich(a, b) for b in alt[j]["A"]) for a in t): return True
    return False

def plan(folge_id, kats=None, felder=None, n=45, ordner=None, zug=1):
    archiv = lade_archiv(ordner, ohne=folge_id); vor = lade_vorrat(ordner)
    alt = [einheit(fr) for e in archiv for fr in e.get("fragen", [])]; idx = Index(alt)
    z = [f"Fragen-Archiv: {len(archiv)} Folgen, {len(alt)} Fragen und Behauptungen gespeichert. Keine davon darf wiederkommen - 'check' prueft das."]
    if archiv:
        z.append("\nLetzte Folgen (Thema der Folge - dasselbe nicht noch einmal in derselben Woche):")
        z += [f"  {e['id']} · {e.get('datum', '')} · {e.get('thema') or e.get('titel', '')}" for e in archiv[-8:]]
    gesamt, zuletzt = {}, {}
    for k, e in enumerate(archiv):
        for fr in e.get("fragen", []):
            gesamt[fr.get("kat")] = gesamt.get(fr.get("kat"), 0) + 1
            if k >= len(archiv) - 10: zuletzt[fr.get("kat")] = zuletzt.get(fr.get("kat"), 0) + 1
    alle_kats = list(vor) or sorted(gesamt)
    z.append("\nKategorien (Fragen bisher gesamt / in den letzten 10 Folgen) - in gemischten Folgen die seltenen bevorzugen:")
    z.append("  " + " · ".join(f"{k} {gesamt.get(k, 0)}/{zuletzt.get(k, 0)}" for k in sorted(alle_kats, key=lambda k: (zuletzt.get(k, 0), gesamt.get(k, 0)))))
    z.append(f"\nGESPERRT - Themen der letzten {SPERRE} Folgen (duerfen nicht vorkommen - auch nicht unter anderem Namen, als Mehrzahl oder als Teil einer anderen Frage):")
    for e in archiv[-SPERRE:]:
        z.append(f"  {e['id']}: " + ", ".join(str(fr.get("thema") or fr.get("q", "")[:30]) for fr in e.get("fragen", [])))
    if len(archiv) > SPERRE:
        z.append("  Aeltere Folgen: Das Thema darf wiederkommen, aber nie dieselbe Frage oder Tatsache ('check' findet das; 'suche <Stichwort>' zeigt, was dazu schon gefragt wurde).")
    rng = random.Random(f"{folge_id}|{len(archiv)}|{zug}")
    wahl = []
    for kat, fl in vor.items():
        if kats and not any(norm(k) in norm(kat) for k in kats): continue
        for feld, stichworte in fl.items():
            if felder and not any(norm(f) in norm(feld) for f in felder): continue
            wahl.append((kat, feld, [s for s in stichworte if not verbraucht(s, alt, idx)], len(stichworte)))
    frei_gesamt = sum(len(f) for _, _, f, _ in wahl)
    z.append(f"\nVORSCHLAEGE aus dem Themen-Vorrat ({frei_gesamt} unbenutzte Stichworte in dieser Auswahl; andere Ziehung mit --zug 2, mehr mit --n 70) - "
             "mindestens zwei Drittel der Fragen daraus bauen, soweit der Vorrat zum Thema der Folge passt:")
    if not frei_gesamt:
        z.append("  (keine passenden Stichworte - eigene Themen waehlen und den Vorrat mit 'vorrat-neu' ergaenzen)")
    else:
        # Jede Kategorie bekommt einen Anteil; was zuletzt selten dran war, bekommt mehr. Innerhalb der Kategorie reihum durch die Felder.
        je_kat = {}
        for kat, feld, frei, _ in wahl:
            if frei: je_kat.setdefault(kat, []).append((feld, frei))
        gew = {k: 1.0 / (1.0 + zuletzt.get(k, 0) / 25.0) for k in je_kat}
        anteil = {k: max(2, round(n * gew[k] / sum(gew.values()))) for k in je_kat}
        for kat in sorted(je_kat, key=lambda k: (zuletzt.get(k, 0), k)):
            felder_k = je_kat[kat]; rng.shuffle(felder_k); gezogen = []; runde = 0
            while len(gezogen) < anteil[kat] and runde < 40:
                for feld, frei in felder_k:
                    kandidaten = [x for x in frei if all(x != g for g, _ in gezogen)]
                    if kandidaten and len(gezogen) < anteil[kat]: gezogen.append((rng.choice(kandidaten), feld))
                runde += 1
            z.append(f"  {kat}: " + " | ".join(f"{x} ({feld})" for x, feld in gezogen))
    if kats or felder:
        z.append("\nFelder in dieser Auswahl (frei/gesamt) - mit --feld eingrenzen: " + " · ".join(f"{feld} {len(frei)}/{ges}" for _, feld, frei, ges in wahl))
    knapp = [f"{kat} · {feld} ({len(frei)} frei)" for kat, feld, frei, _ in wahl if len(frei) < 4]
    if knapp: z.append("\nVorrat fast leer - je Feld 10 bis 15 neue Stichworte ergaenzen (vorrat-neu): " + "; ".join(knapp[:12]))
    return "\n".join(z)

def vorrat_neu(kat, feld, stichworte, ordner=None):
    """Neue Stichworte in den Themen-Vorrat schreiben. -> Meldung als Text."""
    ordner = Path(ordner or ARCHIV); v = lade_vorrat(ordner, roh=True); kats = v.setdefault("kategorien", {})
    if kat not in KATEGORIEN: raise ArchivFehler(f"Kategorie „{kat}“ gibt es nicht - erlaubt: {', '.join(KATEGORIEN)}")
    feld = feld.strip()
    if not 3 <= len(feld) <= 50: raise ArchivFehler("Feld-Name fehlt (z. B. \"Inseln\")")
    archiv = lade_archiv(ordner); alt = [einheit(fr) for e in archiv for fr in e.get("fragen", [])]; idx = Index(alt)
    vorhanden = [thema_woerter(s) for fl in kats.values() for ss in fl.values() for s in ss]
    neu, doppelt, benutzt, schlecht = [], [], [], []
    for s in stichworte:
        s = " ".join(str(s).split()); t = thema_woerter(s)
        if not t or not 2 <= len(s) <= 40: schlecht.append(s); continue
        if any(len(t) == len(u) and all(any(wortgleich(a, b) for b in u) for a in t) for u in vorhanden): doppelt.append(s); continue
        if verbraucht(s, alt, idx): benutzt.append(s); continue
        neu.append(s); vorhanden.append(t)
    if neu:
        kats.setdefault(kat, {}).setdefault(feld, []).extend(neu); v["stand"] = date.today().isoformat()
        (ordner / "vorrat.json").write_text(json.dumps(v, ensure_ascii=False, indent=1) + "\n")
    m = [f"Vorrat {kat} · {feld}: {len(neu)} neue Stichworte" + (": " + ", ".join(neu) if neu else "")]
    if doppelt: m.append("  schon im Vorrat: " + ", ".join(doppelt))
    if benutzt: m.append("  schon gesendet: " + ", ".join(benutzt))
    if schlecht: m.append("  unbrauchbar (leer oder laenger als 40 Zeichen): " + ", ".join(schlecht))
    return "\n".join(m)

def suche(begriffe, ordner=None, grenze=30):
    """Alle gespeicherten Fragen, in denen ein Stichwort vorkommt (Frage, Antwort, Erklaerung oder Thema)."""
    archiv = lade_archiv(ordner); reihen = [(e, fr, einheit(fr)) for e in archiv for fr in e.get("fragen", [])]
    idx = Index([u for _, _, u in reihen]); z = []
    for b in begriffe:
        t = woerter(b) or thema_woerter(b)
        if not t: z.append(f"„{b}“: kein Suchwort"); continue
        ids = [i for i in idx.mit(t[0]) if all(any(gleich(a, w) for w in reihen[i][2]["K"] + reihen[i][2]["F"] + reihen[i][2]["T"]) for a in t)]
        z.append(f"„{b}“: " + (f"{len(ids)} Treffer" + (f" (die letzten {grenze})" if len(ids) > grenze else "") if ids else "noch nie dran"))
        for i in ids[-grenze:]:
            e, fr, _ = reihen[i]
            z.append(f"  {e['id']} F{fr.get('n')} [{fr.get('thema', '')}] {fr.get('q', '')} -> {fr.get('a', '')} | {str(fr.get('fakt', ''))[:110]}")
    return "\n".join(z)

def listen(ordner=None):
    """Lesbare Listen: UEBERSICHT.md (Zahlen, Monate, die neuesten Folgen) und monate/JJJJ-MM.md (alle Folgen). -> {Pfad: Text}"""
    archiv = lade_archiv(ordner); zelle = lambda s: str(s or "").replace("|", "/").replace("\n", " ")
    def block(e):
        z = [f"## Folge {e.get('nr')} · {e.get('datum', '')} · {zelle(e.get('titel'))}", "", "| Nr. | Thema | Frage oder Behauptung | Antwort |", "|---|---|---|---|"]
        z += [f"| {fr.get('n')} | {zelle(fr.get('thema'))} | {zelle(fr.get('q'))} | {zelle(fr.get('a'))} |" for fr in e.get("fragen", [])]
        return z + [""]
    zahl = lambda es: f"{len(es)} Folgen, {sum(len(e.get('fragen', [])) for e in es)} Fragen und Behauptungen"
    monate = {}
    for e in archiv: monate.setdefault(str(e.get("datum") or "")[:7] or "ohne-datum", []).append(e)
    out = {}
    for m, es in monate.items():
        z = [f"# Fragen-Archiv von Quiz um Fünf · {m}", "", f"{zahl(es)}. [Zur Übersicht](../UEBERSICHT.md)", ""]
        for e in reversed(es): z += block(e)
        out[f"monate/{m}.md"] = "\n".join(z) + "\n"
    z = ["# Fragen-Archiv von Quiz um Fünf", "",
         f"**{zahl(archiv)}.** Was hier steht, kommt nicht noch einmal dran: Vor jeder neuen Folge werden alle Fragen mit diesem Archiv "
         f"verglichen (auch umformuliert oder als Wahr-oder-falsch-Behauptung), und ein Thema darf frühestens nach {SPERRE} Folgen wiederkommen. "
         "Ohne bestandene Prüfung wird nichts hochgeladen.", "",
         "Diese Listen werden automatisch erzeugt (`tools/quiz_archiv.py export`) – nicht von Hand ändern.", "",
         "Alle Folgen nach Monaten: " + " · ".join(f"[{m}](monate/{m}.md) ({zahl(monate[m])})" for m in sorted(monate, reverse=True)), "",
         f"Die neuesten {min(NEUESTE, len(archiv))} Folgen:", ""]
    for e in reversed(archiv[-NEUESTE:]): z += block(e)
    out["UEBERSICHT.md"] = "\n".join(z) + "\n"
    return out

def stand(ordner=None):
    archiv = lade_archiv(ordner); alt = [einheit(fr) for e in archiv for fr in e.get("fragen", [])]; idx = Index(alt); vor = lade_vorrat(ordner)
    alle = [s for fl in vor.values() for ss in fl.values() for s in ss]
    return {"folgen": len(archiv), "fragen": len(alt), "letzte": archiv[-1]["id"] if archiv else None,
            "vorrat_gesamt": len(alle), "vorrat_frei": sum(1 for s in alle if not verbraucht(s, alt, idx)), "sperre_folgen": SPERRE,
            "themen_gesperrt": len({norm(fr.get("thema")) for e in archiv[-SPERRE:] for fr in e.get("fragen", []) if fr.get("thema")})}

def selbsttest():
    A = [{"id": "qz_001", "nr": 1, "fragen": [
        {"n": 1, "kat": "Natur", "thema": "Oktopus", "q": "Wie viele Herzen hat ein Oktopus?", "a": "Drei", "fakt": "Zwei Herzen pumpen das Blut durch die Kiemen, das dritte versorgt den Körper."},
        {"n": 2, "kat": "Erdkunde", "thema": "Canberra", "q": "Wie heißt die Hauptstadt von Australien?", "a": "Canberra", "fakt": "Canberra wurde eigens als Hauptstadt geplant – als Kompromiss zwischen Sydney und Melbourne."},
        {"n": 3, "kat": "Weltall", "thema": "Merkur", "q": "Welcher Planet ist der Sonne am nächsten?", "a": "Merkur", "fakt": "Merkur umrundet die Sonne in nur 88 Tagen. Der heißeste Planet ist trotzdem die Venus."},
        {"n": 4, "kat": "Natur", "thema": "Pinguin", "q": "Welcher dieser Vögel kann nicht fliegen?", "a": "Pinguin", "fakt": "Pinguine nutzen ihre Flügel als Flossen."},
        {"n": 5, "kat": "Natur", "thema": "Wolf", "q": "Wie nennt man eine Gruppe von Wölfen?", "a": "Rudel", "fakt": "Ein Rudel ist meist eine Familie: die Eltern und ihr Nachwuchs."},
        {"n": 6, "kat": "Erdkunde", "thema": "Schweiz", "q": "Wie heißt die Hauptstadt der Schweiz?", "a": "Bern", "fakt": "Bern ist Sitz von Regierung und Parlament; die größte Stadt ist Zürich."}]}]
    def f(q, a, thema, fakt="", archiv=A): return pruefe("qz_009", [{"n": 1, "kat": "x", "thema": thema, "q": q, "a": a, "fakt": fakt}], archiv)[0]
    assert f("Ein Oktopus hat drei Herzen.", "wahr", "Krake"), "umformulierte Behauptung muss auffallen"
    assert f("Sydney ist die Hauptstadt von Australien.", "falsch", "Sydney", "Die Hauptstadt heißt Canberra."), "falsche Behauptung zur selben Tatsache"
    assert f("Merkur ist der heißeste Planet unseres Sonnensystems.", "falsch", "Venus", "Der heißeste Planet ist die Venus."), "Tatsache aus einer frueheren Erklaerung"
    assert f("Pinguine leben in freier Wildbahn am Nordpol.", "falsch", "Pinguine", "Pinguine leben fast nur auf der Südhalbkugel."), "gleiches Thema innerhalb der Sperre"
    assert f("Ein Wolfsrudel besteht meist aus einer Familie.", "wahr", "Wölfe", "Die Eltern führen das Rudel."), "Mehrzahl mit Umlaut ist dasselbe Thema"
    assert f("In welcher Stadt tagt das Schweizer Parlament?", "Bern", "Bundeshaus", "Das Bundeshaus steht in Bern."), "gleiche Antwort, verwandte Frage"
    assert not f("Wie heißt die Hauptstadt von Kanada?", "Ottawa", "Ottawa", "Ottawa liegt in der Provinz Ontario."), "andere Hauptstadt ist erlaubt"
    assert not f("Wie heißt die Hauptstadt von Schweden?", "Stockholm", "Schweden", "Stockholm liegt auf 14 Inseln."), "Schweden ist nicht die Schweiz"
    assert not f("Wie viele Beine hat ein Hummer?", "Zehn", "Hummer", "Hummer gehören zu den Zehnfußkrebsen."), "anderes Tier ist erlaubt"
    assert gleich("wal", "wale") and gleich("sonne", "sonnenlicht") and gleich("pinguin", "pinguinen") and not wortgleich("sonne", "sonnenlicht")
    for a, b in (("schweiz", "schweden"), ("schwein", "schweiz"), ("hummel", "hummer"), ("dynamo", "dynamit"), ("kamel", "kamera"), ("lachs", "lachen"), ("ei", "eis")):
        assert not gleich(a, b), f"{a} ist nicht {b}"
    assert wortgleich("grossen", "grosser") and wortgleich("vogel", "vogeln")
    assert thema_woerter("Oder") == ["oder"] and thema_woerter("Vitamin C") == ["vitamin", "c"] and thema_woerter("Die Blechtrommel") == ["blechtrommel"]
    def bezug(t1, q1, t2, q2): return thema_bezug(einheit({"thema": t1, "q": q1}), einheit({"thema": t2, "q": q2}))
    assert bezug("Vitamin C", "", "Vitamin D", "") == 0 and bezug("Everest", "Wie hoch ist der Everest?", "Mount Everest", "Der Mount Everest ist der höchste Berg.") == 2
    assert bezug("Sonne", "Die Sonne ist ein Stern.", "Sonnenlicht", "Das Licht der Sonne braucht acht Minuten zur Erde.") == 2, "dasselbe Thema unter anderem Namen"
    assert bezug("Sonne", "Die Sonne ist ein Stern.", "Sonnenblume", "Aus den Kernen der Sonnenblume wird Öl gepresst.") == 1, "verwandt, aber nicht dasselbe"
    assert bezug("Schwein", "", "Schweiz", "") == 0 and bezug("Wasser", "Wasser gefriert bei null Grad.", "Wasserstoff", "Wasserstoff ist das leichteste Element.") == 1
    B = [{"id": "qz_001", "nr": 1, "fragen": [{"n": 1, "kat": "Erdkunde", "thema": "Oder", "q": "Welcher Fluss bildet einen großen Teil der Grenze zwischen Deutschland und Polen?", "a": "Oder", "fakt": "Zusammen mit der Neiße."},
                                               {"n": 2, "kat": "Erdkunde", "thema": "K2", "q": "Wie heißt der zweithöchste Berg der Erde?", "a": "K2", "fakt": "Er ist 8.611 Meter hoch."}]}]
    assert f("Die Oder mündet in die Ostsee.", "wahr", "Oder", archiv=B) and f("Der K2 liegt im Karakorum.", "wahr", "K2", archiv=B), "kurze Namen und Namen wie Fuellwoerter"
    assert not f("Die Elbe mündet in die Nordsee.", "wahr", "Elbe", archiv=B)
    for a, b in (("wal", "walen"), ("arzt", "arztinnen"), ("vogel", "vogeln"), ("haus", "hauser"), ("sonne", "sonnenlicht"), ("pinguine", "pinguinen")):
        assert gleich(a, b) and set(schluessel(a)) & set(schluessel(b)), f"Suchschluessel fehlt: {a}/{b}"
    alt = [{"id": f"qz_{k:03d}", "nr": k, "fragen": [{"n": 1, "kat": "x", "thema": f"Fueller{k}", "q": f"Fuellfrage Nummer {k} zu Dingsda{k}?", "a": f"Antwort{k}", "fakt": ""}]} for k in range(2, 2 + SPERRE)]
    spaeter = A + alt
    assert not f("Pinguine leben in freier Wildbahn am Nordpol.", "falsch", "Pinguine", "Pinguine leben fast nur auf der Südhalbkugel.", spaeter), "nach der Sperre darf das Thema mit neuem Inhalt wiederkommen"
    assert f("Ein Oktopus hat drei Herzen.", "wahr", "Krake", archiv=spaeter), "dieselbe Tatsache bleibt fuer immer gesperrt"
    print("Selbsttest ok")

def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"): print(__doc__); return 0
    cmd = argv[1]; opt = {}; pos = []
    it = iter(argv[2:])
    for a in it:
        if a.startswith("--"): opt[a[2:]] = next(it, "")
        else: pos.append(a)
    ordner = Path(opt["archiv"]) if opt.get("archiv") else ARCHIV
    split = lambda s, tr=",": [x.strip() for x in s.split(tr) if x.strip()] if s else None
    if cmd == "selbsttest": selbsttest(); return 0
    if cmd == "stand": print(json.dumps(stand(ordner), ensure_ascii=False)); return 0
    if cmd == "plan":
        print(plan(opt.get("id", "neu"), split(opt.get("kat")), split(opt.get("feld")), int(opt.get("n") or 45), ordner, opt.get("zug") or 1)); return 0
    if cmd == "suche":
        if not pos: print("Aufruf: suche <Wort> [<Wort> ...]"); return 1
        print(suche(pos, ordner)); return 0
    if cmd == "vorrat-neu":
        if len(pos) < 3: print('Aufruf: vorrat-neu <Kategorie> <Feld> "Stichwort 1; Stichwort 2; ..."'); return 1
        print(vorrat_neu(pos[0], pos[1], split(" ; ".join(pos[2:]), ";") or [], ordner)); return 0
    if cmd in ("check", "export"):
        if not pos: print(f"Aufruf: {cmd} <folge.json>"); return 1
        ep = json.loads(Path(pos[0]).read_text()); eid = ep.get("id", Path(pos[0]).stem)
        if eid.startswith("muster"): print(f"{eid}: Musterdatei - wird nicht geprueft und nie archiviert"); return 0
        if not re.fullmatch(r"qz_\d{3,}", eid): print(f"FEHLER: id „{eid}“ - erwartet qz_NNN"); return 1
        neu = fragen_aus_folge(ep); archiv = lade_archiv(ordner, ohne=eid)
        fehler, hinweise = pruefe(eid, neu, archiv, thema_folge=ep.get("theme", ""))
        print(f"Archiv-Pruefung {eid}: {len(neu)} Fragen gegen {sum(len(e.get('fragen', [])) for e in archiv)} gespeicherte aus {len(archiv)} Folgen")
        for h in hinweise: print("Hinweis:", h)
        for x in fehler: print("FEHLER:", x)
        if fehler:
            print(f"{len(fehler)} Meldungen - die genannten Fragen durch Fragen zu einem anderen Thema ersetzen (frische Stichworte: plan --id {eid} --zug 2), dann erneut pruefen.")
            return 2
        if cmd == "check":
            print("Archiv ok - keine Dopplung" + (f" ({len(hinweise)} Hinweise ansehen)" if hinweise else "")); return 0
        datum = opt.get("datum", ""); ziel = ordner / f"{eid}.json"
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", datum): print("FEHLER: --datum JJJJ-MM-TT (Sendetag der Folge) fehlt"); return 1
        if ziel.exists() and "ersetzen" not in opt:
            war = json.loads(ziel.read_text()).get("datum", "")
            if war and war < date.today().isoformat():
                print(f"FEHLER: {eid} wurde schon am {war} gesendet - der Eintrag wird nicht ueberschrieben. Die neue Folge braucht die naechste freie Nummer."); return 1
        eintrag = {"id": eid, "nr": nummer(eid), "datum": datum, "titel": ep.get("title", ""), "format": ep.get("format", "quiz"),
                   "thema": ep.get("theme", ""), "fragen": neu}
        ordner.mkdir(exist_ok=True); (ordner / "monate").mkdir(exist_ok=True)
        ziel.write_text(json.dumps(eintrag, ensure_ascii=False, indent=1) + "\n")
        for pfad, text in listen(ordner).items(): (ordner / pfad).write_text(text)
        print(f"Archiv-Eintrag geschrieben: {ziel} ({len(neu)} Fragen). Jetzt zusammen mit dem Upload-Auftrag einreichen (git add archiv queue).")
        print("STAND " + json.dumps(stand(ordner), ensure_ascii=False)); return 0
    print("Unbekannter Befehl:", cmd); return 1

if __name__ == "__main__":
    try: sys.exit(main(sys.argv))
    except ArchivFehler as e:
        print("FEHLER:", e); sys.exit(1)
