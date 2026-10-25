"""베트맨 응답을 흉내 낸 가짜 데이터로 수집기 전체 흐름을 돌려본다 (베트맨 접속 없이).

    python tests/run_offline.py        # web/data/latest.json 생성 (football-data 통계는 실제로 받음)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "collector"))
import betman_api  # noqa: E402
import collect  # noqa: E402

KEYS = ["matchSeq", "itemCode", "leagueName", "betNm", "homeName", "awayName", "homeId", "awayId",
        "winAllot", "drawAllot", "loseAllot", "winHandi", "gameDate", "sgl"]
MS = 1792335600000


def proto_doc():
    rows, n = [], 0
    def add(lg, bet, h, a, w, d, l, line=None):
        nonlocal n
        n += 1
        rows.append([n, "SC", lg, bet, h, a, 0, 0, w, d, l, line, MS, "N"])
    for lg, h, a, o in [("잉글랜드 프리미어리그", "아스널", "코번트리", (1.25, 5.6, 9.5)),
                        ("잉글랜드 프리미어리그", "맨체스터 유나이티드", "토트넘 홋스퍼", (2.2, 3.4, 2.9)),
                        ("스페인 라리가", "레알 마드리드", "FC바르셀로나", (2.35, 3.6, 2.6)),
                        ("독일 분데스리가", "FC바이에른뮌헨", "보루시아도르트문트", (1.45, 4.6, 5.2)),
                        ("이탈리아 세리에A", "인터밀란", "AC밀란", (1.9, 3.3, 3.8)),
                        ("프랑스 리그1", "파리 생제르맹", "올랭피크 마르세유", (1.5, 4.2, 5.0))]:
        add(lg, "축구 승무패", h, a, *o)
        add(lg, "축구 언더오버", h, a, 1.95, 0, 1.7, 2.5)
        add(lg, "축구 핸디캡", h, a, 2.6, 3.5, 2.2, -1.0)
    return {"compSchedules": {"keys": KEYS, "datas": rows}, "currentLottery": {"gmOsidTs": 125}}


def fake_fetch_all(**kw):
    p = proto_doc()
    proto, _ = betman_api.parse_proto(p)
    toto = betman_api.parse_toto({"compSchedules": {"keys": KEYS, "datas": [
        r for r in p["compSchedules"]["datas"] if r[3] == "축구 승무패"]}})
    return proto, toto, {"proto": p}


betman_api.fetch_all = fake_fetch_all
sys.argv = ["collect.py", "--no-api"] + sys.argv[1:]
collect.main()
