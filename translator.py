#!/usr/bin/env python3
"""한국어 ↔ 일본어 번역기 (Streamlit)"""
import re

import streamlit as st
from deep_translator import GoogleTranslator

st.set_page_config("한국어 ↔ 일본어 번역기", "🌐", layout="centered")

HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
KANA = re.compile(r"[぀-ヿ]")

MAX_CHUNK = 4500  # 무료 번역 API 1회 요청 길이 제한 회피


def detect_lang(text):
    """한글·가나 글자 수를 비교해 한국어/일본어를 자동 판별. 판별 불가시 None"""
    hangul = len(HANGUL.findall(text))
    kana = len(KANA.findall(text))
    if kana > 0 and kana >= hangul:
        return "ja"
    if hangul > 0:
        return "ko"
    return None


def split_chunks(text, size=MAX_CHUNK):
    """줄바꿈 단위로 텍스트를 나눠 API 길이 제한을 피함"""
    if len(text) <= size:
        return [text]
    chunks, buf = [], ""
    for line in text.splitlines(keepends=True):
        if buf and len(buf) + len(line) > size:
            chunks.append(buf)
            buf = ""
        buf += line
    if buf:
        chunks.append(buf)
    return chunks


@st.cache_data(ttl=3600, show_spinner=False)
def translate(text, source, target):
    tr = GoogleTranslator(source=source, target=target)
    return "".join(tr.translate(chunk) or "" for chunk in split_chunks(text))


st.title("🌐 한국어 ↔ 일본어 번역기")
st.caption("입력한 언어를 자동으로 판별해 반대 언어로 번역합니다 (Google 번역 기반)")

mode = st.radio(
    "번역 방향",
    ["자동 감지", "한국어 → 일본어", "일본어 → 한국어"],
    horizontal=True,
)

placeholder = {
    "자동 감지": "한국어 또는 일본어 문장을 입력하세요…",
    "한국어 → 일본어": "번역할 한국어 문장을 입력하세요…",
    "일본어 → 한국어": "번역할 일본어 문장을 입력하세요…",
}[mode]

text = st.text_area("입력", height=200, placeholder=placeholder)

if st.button("번역하기", type="primary", disabled=not text.strip()):
    if mode == "한국어 → 일본어":
        src, tgt = "ko", "ja"
    elif mode == "일본어 → 한국어":
        src, tgt = "ja", "ko"
    else:
        src = detect_lang(text)
        if src is None:
            st.warning("한국어 또는 일본어 문장을 입력해주세요.")
            st.stop()
        tgt = "ja" if src == "ko" else "ko"

    label = {"ko": "한국어", "ja": "일본어"}
    st.caption(f"{label[src]} → {label[tgt]}로 번역합니다")

    try:
        with st.spinner("번역 중…"):
            result = translate(text, src, tgt)
    except Exception as e:
        st.error(f"번역에 실패했습니다: {e}")
    else:
        st.text_area("번역 결과", value=result, height=200)
