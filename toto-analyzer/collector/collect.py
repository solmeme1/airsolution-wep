"""베트맨 회차 경기 + API-Football 분석 데이터 수집기.

사용법 (collector 폴더에서):
    python collect.py              # 베트맨 자동 수집 + 분석 데이터
    python collect.py --manual     # 브라우저를 띄워 직접 회차 화면을 연 뒤 수집
    python collect.py --from-text proto.txt --toto-text toto.txt   # 복사한 텍스트로 수집
    python collect.py --serve      # 수집 후 분석 웹 열기
결과: ../web/data/latest.json
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE.parent / "web"
DATA = WEB / "data"
RAW = HERE / "raw"
CACHE = HERE / "cache"

sys.path.insert(0, str(HERE))
from betman_parser import parse_proto, parse_toto  # noqa: E402
from matching import Matcher  # noqa: E402

DEFAULT_PROTO_URL = "https://www.betman.co.kr/main/mainPage/gamebuy/gameSlip.do?gmId=G101"
DEFAULT_TOTO_URL = "https://www.betman.co.kr/main/mainPage/gamebuy/gameSlip.do?gmId=G011"


def load_env() -> None:
    env = HERE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------- API-Football 응답 줄이기 ----------

def _g(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return default if d is None else d


def _num(x):
    try:
        return float(str(x).rstrip("%"))
    except (TypeError, ValueError):
        return None


def slim_prediction(p: dict | None) -> dict | None:
    if not p:
        return None
    def team(side):
        t = _g(p, "teams", side, default={})
        lg = t.get("league") or {}
        return {
            "name": t.get("name"),
            "last5": {
                "form": _num(_g(t, "last_5", "form")),
                "att": _num(_g(t, "last_5", "att")),
                "def": _num(_g(t, "last_5", "def")),
                "gf": _num(_g(t, "last_5", "goals", "for", "average")),
                "ga": _num(_g(t, "last_5", "goals", "against", "average")),
            },
            "form": lg.get("form") or "",
            "played": {k: _g(lg, "fixtures", "played", k) for k in ("home", "away", "total")},
            "gf": {k: _num(_g(lg, "goals", "for", "average", k)) for k in ("home", "away", "total")},
            "ga": {k: _num(_g(lg, "goals", "against", "average", k)) for k in ("home", "away", "total")},
        }
    h2h = []
    for f in (p.get("h2h") or [])[:10]:
        h2h.append({
            "date": _g(f, "fixture", "date", default="")[:10],
            "home": _g(f, "teams", "home", "name"),
            "away": _g(f, "teams", "away", "name"),
            "gh": _g(f, "goals", "home"),
            "ga": _g(f, "goals", "away"),
        })
    pr = p.get("predictions") or {}
    return {
        "percent": {k: _num(_g(pr, "percent", k)) for k in ("home", "draw", "away")},
        "advice": pr.get("advice"),
        "under_over": pr.get("under_over"),
        "home": team("home"),
        "away": team("away"),
        "comparison": {k: {s: _num(v.get(s)) for s in ("home", "away")}
                       for k, v in (p.get("comparison") or {}).items() if isinstance(v, dict)},
        "h2h": h2h,
    }


def slim_injuries(rows: list) -> list:
    return [{
        "team": _g(r, "team", "name"),
        "team_id": _g(r, "team", "id"),
        "player": _g(r, "player", "name"),
        "type": _g(r, "player", "type"),
        "reason": _g(r, "player", "reason"),
    } for r in rows]


def slim_lineups(rows: list) -> list:
    return [{
        "team": _g(r, "team", "name"),
        "team_id": _g(r, "team", "id"),
        "formation": r.get("formation"),
        "coach": _g(r, "coach", "name"),
        "xi": [{"name": _g(x, "player", "name"), "pos": _g(x, "player", "pos"), "no": _g(x, "player", "number")}
               for x in r.get("startXI") or []],
    } for r in rows]


# ---------- 메인 흐름 ----------

def collect_betman(args) -> tuple[list, list, dict]:
    RAW.mkdir(exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d_%H%M}"
    use_text = bool(args.from_text or args.toto_text)

    # 1순위: 베트맨 JSON 엔드포인트 (브라우저 불필요)
    if not use_text and not (args.manual or args.browser):
        try:
            from betman_api import fetch_all
            proto, toto, raw = fetch_all(soccer_only=not args.all_sports, proto_ts=args.proto_ts,
                                         toto_ts=args.toto_ts, log=log)
            dump = RAW / f"betman_api_{stamp}.json"
            dump.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
            log(f"원본 응답 저장: {dump}")
            if proto or toto:
                return proto, toto, {"proto": "betman api", "toto": "betman api"}
            log("JSON 방식으로 경기를 받지 못해 브라우저 방식으로 다시 시도합니다.")
        except Exception as e:
            log(f"JSON 방식 실패({e}). 브라우저 방식으로 다시 시도합니다.")

    # 2순위: 브라우저 화면 텍스트, 3순위: 복사해 둔 텍스트 파일
    raw: dict = {}
    if use_text:
        proto_txt = Path(args.from_text).read_text(encoding="utf-8") if args.from_text else ""
        toto_txt = Path(args.toto_text).read_text(encoding="utf-8") if args.toto_text else ""
        raw = {"proto": {"url": "text", "text": proto_txt}, "toto": {"url": "text", "text": toto_txt}}
    else:
        try:
            from betman_fetch import capture
        except ImportError:
            log("Playwright가 설치되어 있지 않습니다: pip install playwright && python -m playwright install chromium")
            return [], [], {}
        urls = {
            "proto": os.environ.get("BETMAN_PROTO_URL", DEFAULT_PROTO_URL),
            "toto": os.environ.get("BETMAN_TOTO_URL", DEFAULT_TOTO_URL),
        }
        log("베트맨 화면 여는 중...")
        raw = capture(urls, headless=not args.show, manual=args.manual)

    dump = RAW / f"betman_{stamp}.json"
    dump.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"원본 화면 저장: {dump}")

    proto = parse_proto(raw.get("proto", {}).get("text", ""), soccer_only=not args.all_sports)
    toto = parse_toto(raw.get("toto", {}).get("text", ""))
    log(f"프로토 {len(proto)}개 항목, 승무패 {len(toto)}경기 인식")
    if not proto and not toto:
        log("경기를 하나도 인식하지 못했습니다. --manual 로 다시 실행하거나, "
            f"{dump.name} 파일을 보내주시면 파서를 맞춰 드릴게요.")
    return proto, toto, {k: v.get("url") for k, v in raw.items()}


def enrich_api(games: list, key: str, max_fixtures: int, matcher: Matcher) -> tuple[dict, int | None]:
    """API-Football: 경기 연결 + 예측·부상·라인업. 실패해도 예외를 밖으로 던지지 않는다."""
    from football import Football, QuotaExceeded

    fb = Football(key, CACHE)
    dates = sorted({g["kickoff"][:10] for g in games if g.get("kickoff")}) or [datetime.now().strftime("%Y-%m-%d")]
    fixtures: list = []
    try:
        for d in dates[:5]:
            log(f"API-Football 경기 일정 {d}")
            fixtures += fb.fixtures_by_date(d)
    except Exception as e:
        msg = str(e)
        if "plan" in msg.lower() or "season" in msg.lower():
            log(f"API-Football 무료 요금제로는 이 시즌 데이터를 받을 수 없습니다: {msg}")
        else:
            log(f"API-Football 경기 일정 조회 실패: {msg}")
        log("→ football-data.co.uk 무료 통계로 대신 분석합니다 (부상·라인업 제외).")
        return {}, fb.remaining

    cache: dict[tuple, tuple] = {}
    for g in games:
        k = (g["home"], g["away"], g.get("kickoff"))
        if k not in cache:
            cache[k] = matcher.match(g, fixtures)
        f, how = cache[k]
        if f:
            g["fixture_id"] = f["fixture"]["id"]
            g["match_how"] = how
        else:
            g["match_why"] = how

    order: list[int] = []  # 승무패 경기 먼저, 그다음 프로토 번호 순
    for g in games:
        fid = g.get("fixture_id")
        if fid and fid not in order:
            order.append(fid)
    fx_by_id = {f["fixture"]["id"]: f for f in fixtures}
    out: dict = {}
    now = datetime.now()
    for fid in order[:max_fixtures]:
        f = fx_by_id[fid]
        item = {
            "id": fid,
            "league": f["league"]["name"],
            "league_id": f["league"]["id"],
            "kickoff": f["fixture"]["date"][:16],
            "home": {"id": f["teams"]["home"]["id"], "name": f["teams"]["home"]["name"]},
            "away": {"id": f["teams"]["away"]["id"], "name": f["teams"]["away"]["name"]},
            "source": "API-Football",
        }
        out[fid] = item
        try:
            log(f"분석 데이터: {item['home']['name']} vs {item['away']['name']}")
            item["prediction"] = slim_prediction(fb.predictions(fid))
            item["injuries"] = slim_injuries(fb.injuries(fid))
            if datetime.fromisoformat(item["kickoff"]) - now < timedelta(minutes=90):
                item["lineups"] = slim_lineups(fb.lineups(fid))
        except QuotaExceeded as e:
            log(f"API 한도 도달: {e}")
            break
        except Exception as e:  # 한 경기 실패가 전체를 막지 않게
            log(f"  실패: {e}")
            item["error"] = str(e)
    if len(order) > max_fixtures:
        log(f"MAX_FIXTURES={max_fixtures} 제한으로 {len(order) - max_fixtures}경기는 API 분석 생략")
    log(f"API 호출 {fb.calls}회, 남은 호출: {fb.remaining}")
    return out, fb.remaining


def enrich_fd(games: list, fixtures: dict, matcher: Matcher) -> None:
    """API 예측이 없는 경기를 football-data.co.uk 통계로 채운다."""
    from footballdata import FootballData

    fd = FootballData(CACHE, log=log)
    done: dict[tuple, str | None] = {}
    n = 0
    for g in games:
        fx = fixtures.get(g.get("fixture_id"))
        if fx and fx.get("prediction"):
            continue
        k = (g["home"], g["away"], g.get("kickoff"))
        if k not in done:
            done[k] = None
            div = fd.div_for(g.get("league", ""))
            if div and fd.matches(div):
                names = fd.teams(div)
                h, a = matcher.pick_name(g["home"], names), matcher.pick_name(g["away"], names)
                if h and a:
                    pred = fd.stats(div, h, a)
                    if fx:  # API 경기 정보는 있는데 예측만 실패한 경우: 통계만 채운다
                        fx["prediction"] = pred
                        done[k] = g["fixture_id"]
                    else:
                        fid = f"fd:{div}:{h}|{a}|{g.get('kickoff') or ''}"
                        fixtures[fid] = {"id": fid, "league": div, "kickoff": g.get("kickoff"),
                                         "home": {"id": None, "name": h}, "away": {"id": None, "name": a},
                                         "prediction": pred, "injuries": [], "source": "football-data.co.uk"}
                        done[k] = fid
                    n += 1
                else:
                    g["match_why"] = f"football-data 팀명 불일치 ({div})"
        if done[k] is not None:
            g["fixture_id"] = done[k]
            g.setdefault("match_how", "팀명(football-data)")
    if n:
        log(f"football-data.co.uk 통계로 {n}경기 보충")


def unmatched_list(games: list) -> list:
    seen, out = set(), []
    for g in games:
        k = (g["home"], g["away"], g.get("kickoff"))
        if not g.get("fixture_id") and k not in seen:
            seen.add(k)
            out.append({"home": g["home"], "away": g["away"], "kickoff": g.get("kickoff"),
                        "league": g.get("league"), "why": g.get("match_why", "통계 없는 리그")})
    return out


def check() -> None:
    """설치 직후 점검: API 키 상태와 베트맨 접속."""
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not key or "여기에" in key:
        log("✗ API_FOOTBALL_KEY 가 collector/.env 에 없습니다.")
    else:
        try:
            from football import Football
            st = Football(key, CACHE).status()
            sub = st.get("subscription") or {}
            req = st.get("requests") or {}
            log(f"✓ API-Football: {sub.get('plan', '?')} 요금제, 오늘 {req.get('current', '?')}/{req.get('limit_day', '?')}회 사용")
        except Exception as e:
            log(f"✗ API-Football 점검 실패: {e}")
    try:
        from betman_api import Betman, list_games
        games = list_games(Betman().buyable())
        log(f"✓ 베트맨 접속: 구매 가능 게임 {len(games)}개 "
            + ", ".join(f"{g['gmId']}/{g['gmTs']}" for g in games[:8]))
    except Exception as e:
        log(f"✗ 베트맨 JSON 접속 실패: {e}  (브라우저 방식 --browser 로 시도해 보세요)")


def serve(port: int) -> None:
    os.chdir(WEB)
    handler = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        url = f"http://127.0.0.1:{port}/index.html"
        log(f"분석 웹: {url}  (종료: Ctrl+C)")
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        httpd.serve_forever()


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser(description="베트맨 + API-Football 수집기")
    ap.add_argument("--manual", action="store_true", help="브라우저를 띄워 직접 회차 화면을 연 뒤 수집")
    ap.add_argument("--show", action="store_true", help="브라우저 창을 보이게 실행")
    ap.add_argument("--browser", action="store_true", help="JSON 방식 대신 브라우저 화면으로 수집")
    ap.add_argument("--proto-ts", help="프로토 회차 직접 지정 (예: 260125)")
    ap.add_argument("--toto-ts", help="승무패 회차 직접 지정")
    ap.add_argument("--check", action="store_true", help="API 키와 베트맨 접속만 점검")
    ap.add_argument("--from-text", help="프로토 화면을 복사한 텍스트 파일")
    ap.add_argument("--toto-text", help="승무패 화면을 복사한 텍스트 파일")
    ap.add_argument("--all-sports", action="store_true", help="축구 외 종목도 포함")
    ap.add_argument("--no-api", action="store_true", help="API-Football 호출 생략")
    ap.add_argument("--no-stats", action="store_true", help="football-data.co.uk 무료 통계 생략")
    ap.add_argument("--serve", action="store_true", help="수집 후 분석 웹 열기")
    ap.add_argument("--serve-only", action="store_true", help="수집 없이 분석 웹만 열기")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    if args.serve_only:
        serve(args.port)
        return
    if args.check:
        check()
        return

    proto, toto, sources = collect_betman(args)

    fixtures: dict = {}
    remaining = None
    games = toto + proto  # 승무패를 먼저(우선순위)
    matcher = Matcher(HERE / "team_alias.json", HERE / "team_alias_learned.json")
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if "여기에" in key:
        key = ""
    if games and not args.no_api:
        if key:
            fixtures, remaining = enrich_api(games, key, int(os.environ.get("MAX_FIXTURES", "25")), matcher)
        else:
            log("API_FOOTBALL_KEY가 없어 부상·라인업 없이 분석합니다. collector/.env 에 키를 넣어주세요.")
    if games and not args.no_stats:
        try:
            enrich_fd(games, fixtures, matcher)
        except Exception as e:
            log(f"football-data 통계 보충 실패: {e}")
    unmatched = unmatched_list(games)

    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "sources": sources,
        "proto": proto,
        "toto": toto,
        "fixtures": {str(k): v for k, v in fixtures.items()},
        "unmatched": unmatched,
        "api_remaining": remaining,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    (DATA / "latest.json").write_text(text, encoding="utf-8")
    (DATA / f"{datetime.now():%Y%m%d_%H%M}.json").write_text(text, encoding="utf-8")
    log(f"저장 완료: {DATA / 'latest.json'}")
    if unmatched:
        log(f"팀 매칭 실패 {len(unmatched)}경기 → team_alias.json 에 별칭을 추가하면 다음부터 연결됩니다:")
        for u in unmatched[:15]:
            log(f"  - {u['home']} vs {u['away']} ({u['kickoff']}, {u['league']}): {u['why']}")

    if args.serve:
        serve(args.port)


if __name__ == "__main__":
    main()
