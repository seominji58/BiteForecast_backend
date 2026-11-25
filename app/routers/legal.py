"""개인정보 처리방침·이용약관 웹 페이지 (원스토어 등록용 주소, 2026-11-25). /privacy · /terms"""

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app import legal

router = APIRouter(tags=["legal"], include_in_schema=False)

_STYLE = """
:root{--bg:#f4f6f9;--card:#fff;--text:#14202e;--sub:#4a5868;--line:#e2e7ee;--navy:#0f2c4a}
@media (prefers-color-scheme:dark){
 :root{--bg:#0d1620;--card:#152230;--text:#e8eef5;--sub:#a6b4c3;--line:#24364a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
 font:15px/1.7 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;
 word-break:keep-all}
header{background:var(--navy);color:#fff;padding:20px 16px}
header h1{margin:0 auto;max-width:720px;font-size:20px}
main{max-width:720px;margin:0 auto;padding:16px}
.intro{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.updated{color:var(--sub);font-size:13px;margin:0 0 6px}
section{margin-top:20px}
h2{font-size:16px;margin:0 0 6px}
p{margin:0;color:var(--sub);white-space:pre-line}
footer{max-width:720px;margin:24px auto 40px;padding:0 16px;color:var(--sub);font-size:13px}
a{color:inherit}
"""


def _page(title: str, intro: str, sections: list[tuple[str, str]], other: tuple[str, str]) -> HTMLResponse:
    body = "".join(f"<section><h2>{escape(t)}</h2><p>{escape(b)}</p></section>" for t, b in sections)
    html = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)} · 입질예보</title><style>{_STYLE}</style></head><body>"
        f"<header><h1>입질예보 {escape(title)}</h1></header><main>"
        f'<div class="intro"><p class="updated">시행일 {legal.UPDATED}</p><p>{escape(intro)}</p></div>'
        f"{body}</main>"
        f'<footer>문의 <a href="mailto:{legal.SUPPORT_EMAIL}">{legal.SUPPORT_EMAIL}</a> · '
        f'<a href="{other[0]}">{escape(other[1])}</a></footer></body></html>'
    )
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=3600"})


@router.get("/privacy", response_class=HTMLResponse)
def privacy():
    return _page("개인정보 처리방침", legal.PRIVACY_INTRO, legal.PRIVACY, ("/terms", "이용약관"))


@router.get("/terms", response_class=HTMLResponse)
def terms():
    return _page("이용약관", legal.TERMS_INTRO, legal.TERMS, ("/privacy", "개인정보 처리방침"))
