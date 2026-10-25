"""베트맨 내부 JSON 엔드포인트로 회차 경기를 받는다 (브라우저 불필요).

흐름
  1) POST /buyPsblGame/inqCacheBuyAbleGameInfoList.do  → 지금 구매 가능한 게임(gmId, gmTs) 목록
  2) GET  /main/mainPage/gamebuy/gameSlip.do?gmId=..&gmTs=..  → 세션 쿠키
  3) POST /buyPsblGame/gameInfoInq.do {"gmId","gmTs","gameYear"} → compSchedules(keys/datas 열 구조)

필드 이름(homeName, winAllot, betNm 등)은 공개된 다른 수집기에서 확인한 것이며,
베트맨이 바꾸면 깨질 수 있다. 그때는 raw/ 에 저장된 원본으로 맞춘다.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://www.betman.co.kr"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
PROTO_ID = "G101"
DELAY = 3.0  # 요청 간 간격(초)

# betNm → 마켓. '축구 전반 승무패' 같은 전반 마켓은 정산 기준이 달라 제외한다.
PROTO_MARKETS = {"축구 승무패": "1x2", "축구 핸디캡": "handicap", "축구 언더오버": "uo", "축구 SUM": "sum"}
KST = timezone(timedelta(hours=9))


class Betman:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
        self._warm = False

    def _post(self, path: str, body: dict, referer: str) -> dict:
        r = self.s.post(BASE + path, data=json.dumps(body), timeout=30, headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
        })
        r.raise_for_status()
        text = r.text.lstrip()
        if text.startswith("<"):
            raise RuntimeError(f"{path}: JSON 대신 HTML 응답 (요청 형식 변경 또는 차단)")
        return r.json()

    def buyable(self) -> dict:
        if not self._warm:
            self.s.get(BASE + "/", timeout=30)
            self._warm = True
            time.sleep(DELAY)
        return self._post("/buyPsblGame/inqCacheBuyAbleGameInfoList.do",
                          {"_sbmInfo": {"debugMode": "false"}}, BASE + "/")

    def round(self, gm_id: str, gm_ts: int | str) -> dict:
        year = "20" + str(gm_ts)[:2]
        page = f"{BASE}/main/mainPage/gamebuy/gameSlip.do?gmId={gm_id}&year={year}&gmTs={gm_ts}"
        self.s.get(page, timeout=30)
        time.sleep(DELAY)
        return self._post("/buyPsblGame/gameInfoInq.do",
                          {"gmId": gm_id, "gmTs": int(gm_ts), "gameYear": year,
                           "_sbmInfo": {"debugMode": "false"}}, page)


def list_games(buyable: dict) -> list[dict]:
    """구매 가능 목록 응답 어디에 있든 gmId/gmTs 를 가진 항목을 모두 모은다."""
    found: list[dict] = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("gmId") and x.get("gmTs"):
                found.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(buyable)
    uniq = {}
    for g in found:
        uniq.setdefault((g["gmId"], str(g["gmTs"])), g)
    return list(uniq.values())


def _name(g: dict) -> str:
    return " ".join(str(v) for k, v in g.items() if isinstance(v, str) and ("Nm" in k or "name" in k.lower()))


def pick_toto(games: list[dict]) -> dict | None:
    """축구토토 승무패 회차 찾기: 이름에 '승무패'가 있고 '프로토'·'전반'이 아닌 것, 없으면 gmId G011."""
    for g in games:
        nm = _name(g)
        if "승무패" in nm and "전반" not in nm and g["gmId"] != PROTO_ID and "프로토" not in nm:
            return g
    return next((g for g in games if g["gmId"] == "G011"), None)


def _rows(doc: dict) -> list[dict]:
    cs = doc.get("compSchedules") or {}
    keys = cs.get("keys") or []
    return [dict(zip(keys, row)) for row in cs.get("datas") or []]


def _kick(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, KST).strftime("%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_proto(doc: dict, soccer_only: bool = True) -> tuple[list[dict], dict]:
    out, skipped = [], {}
    for r in _rows(doc):
        if soccer_only and r.get("itemCode") not in (None, "SC"):
            continue
        bet = r.get("betNm") or ""
        market = PROTO_MARKETS.get(bet)
        if not market:
            skipped[bet or "?"] = skipped.get(bet or "?", 0) + 1
            continue
        w, d, l = _f(r.get("winAllot")), _f(r.get("drawAllot")), _f(r.get("loseAllot"))
        if market == "uo":
            odds = {"under": w, "over": l}
        elif market == "sum":
            odds = {"odd": w, "even": l}
        elif d > 1:
            odds = {"home": w, "draw": d, "away": l}
        else:
            odds = {"home": w, "away": l}
        if not all(v > 1 for v in odds.values()):
            skipped["배당 미공시"] = skipped.get("배당 미공시", 0) + 1
            continue
        line = r.get("winHandi")
        out.append({
            "no": r.get("matchSeq"),
            "league": r.get("leagueName") or "",
            "kickoff": _kick(r.get("gameDate")),
            "home": (r.get("homeName") or "").strip(),
            "away": (r.get("awayName") or "").strip(),
            "home_bid": r.get("homeId"),
            "away_bid": r.get("awayId"),
            "market": market,
            "line": _f(line) if market in ("handicap", "uo") and line not in (None, "") else None,
            "odds": odds,
            "single": str(r.get("sgl")) in ("Y", "1", "true", "True"),
        })
    out.sort(key=lambda m: (m["no"] or 0))
    return out, skipped


def parse_toto(doc: dict) -> list[dict]:
    out, seen = [], set()
    rows = _rows(doc)
    for i, r in enumerate(rows):
        home, away = (r.get("homeName") or "").strip(), (r.get("awayName") or "").strip()
        if not home or not away or (home, away) in seen:
            continue
        seen.add((home, away))
        no = r.get("matchSeq") or i + 1
        out.append({
            "no": int(no),
            "league": r.get("leagueName") or "",
            "kickoff": _kick(r.get("gameDate")),
            "home": home,
            "away": away,
            "home_bid": r.get("homeId"),
            "away_bid": r.get("awayId"),
            "votes": None,
        })
    out.sort(key=lambda m: m["no"])
    return out[:14]


def fetch_all(soccer_only: bool = True, proto_ts: str | None = None, toto_ts: str | None = None,
              log=print) -> tuple[list, list, dict]:
    """반환: (proto 경기, toto 경기, 원본 덤프)"""
    bm = Betman()
    raw: dict = {}
    games: list[dict] = []
    if not (proto_ts and toto_ts):
        raw["buyable"] = bm.buyable()
        games = list_games(raw["buyable"])
        log("구매 가능 게임: " + ", ".join(f"{g['gmId']}/{g['gmTs']} {_name(g)[:20]}" for g in games) or "없음")

    proto, toto = [], []
    pts = proto_ts or next((str(g["gmTs"]) for g in games if g["gmId"] == PROTO_ID), None)
    if pts:
        doc = bm.round(PROTO_ID, pts)
        raw["proto"] = doc
        proto, skipped = parse_proto(doc, soccer_only)
        cl = doc.get("currentLottery") or {}
        log(f"프로토 승부식 {cl.get('gmOsidTs', pts)}회차: 축구 {len(proto)}항목"
            + (f" (제외: {', '.join(f'{k} {v}' for k, v in list(skipped.items())[:4])})" if skipped else ""))
    else:
        log("발매 중인 프로토 승부식 회차를 찾지 못했습니다.")

    tg = {"gmId": "G011", "gmTs": toto_ts} if toto_ts else pick_toto(games)
    if tg:
        time.sleep(DELAY)
        doc = bm.round(tg["gmId"], tg["gmTs"])
        raw["toto"] = doc
        toto = parse_toto(doc)
        log(f"축구토토 승무패 {tg['gmId']}/{tg['gmTs']}: {len(toto)}경기")
    else:
        log("발매 중인 축구토토 승무패 회차를 찾지 못했습니다.")
    return proto, toto, raw
