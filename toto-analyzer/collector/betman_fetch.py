"""Playwright로 베트맨 구매 화면을 열어 화면 텍스트와 JSON 응답을 저장한다."""
from __future__ import annotations

import json


def _page_text(page) -> str:
    parts = []
    for fr in page.frames:
        try:
            parts.append(fr.inner_text("body", timeout=5000))
        except Exception:
            pass
    return "\n".join(parts)


def capture(urls: dict[str, str], headless: bool = True, manual: bool = False) -> dict[str, dict]:
    """urls: {"proto": url, "toto": url}. 반환: {kind: {"url", "text", "json"}}"""
    from playwright.sync_api import sync_playwright

    results: dict[str, dict] = {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=headless and not manual)
        except Exception:
            browser = p.chromium.launch(headless=headless and not manual)
        ctx = browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul",
                                  viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        captured: list[dict] = []

        def on_response(resp):
            try:
                if "betman" in resp.url and "json" in (resp.headers.get("content-type") or ""):
                    captured.append({"url": resp.url, "body": resp.json()})
            except Exception:
                pass

        page.on("response", on_response)

        for kind, url in urls.items():
            if not url:
                continue
            captured.clear()
            label = "프로토 승부식" if kind == "proto" else "축구토토 승무패"
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            if manual:
                input(f"\n[{label}] 브라우저에서 구매 화면(경기 목록이 보이는 화면)을 연 뒤 여기서 Enter를 누르세요... ")
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                page.wait_for_timeout(3000)
            # 긴 목록은 스크롤해야 다 그려지는 경우가 있다
            for _ in range(15):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(300)
            results[kind] = {
                "url": page.url,
                "text": _page_text(page),
                "json": json.loads(json.dumps(captured[-30:], ensure_ascii=False, default=str)),
            }
        browser.close()
    return results
