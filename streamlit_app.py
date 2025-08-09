import finnhub
import streamlit as st
import pandas as pd
import time
import gspread
from collections import defaultdict
from google.oauth2.service_account import Credentials

API_KEY = st.secrets["FINNHUB_API_KEY"]
client = finnhub.Client(api_key=API_KEY)

# --- Google Sheets 인증 ---
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive"
]

credentials = Credentials.from_service_account_info(
    st.secrets["gcp_service_account"], scopes=scope
)
client_gs = gspread.authorize(credentials)
sheet = client_gs.open("streamlit_tickers").sheet1

# --- 유틸 함수 ---
def get_quote_with_retry(ticker, max_retries=5, delay=10):
    for attempt in range(max_retries):
        try:
            quote = client.quote(ticker)
            if quote and 'c' in quote and quote['c'] != 0:
                return quote
            else:
                raise ValueError(f"{ticker} 응답 없음 또는 현재가가 0입니다.")
        except Exception as e:
            if attempt < max_retries - 1:
                st.warning(f"{ticker} 재시도 {attempt + 1}/{max_retries} - 10초 대기 중...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"{ticker} 호출 실패: {e}")

def load_tickers():
    return sheet.get_all_records()

def save_ticker_to_sheet(new_ticker, new_sector):
    existing = sheet.get_all_values()
    if any(row[0] == new_ticker for row in existing[1:]):
        return False
    sheet.append_row([new_ticker, new_sector])
    return True

# -- 감시 티커, 목표가 세로 저장 방식 --

def save_watch_ticker_to_sheet(new_ticker, target_price=""):
    existing = sheet.get_all_values()
    tickers_col = [row[3] if len(row) > 3 else "" for row in existing]  # D열 티커 리스트

    if new_ticker in tickers_col:
        return False  # 이미 존재

    row_idx = len(tickers_col) + 1  # 1-based index, 헤더 포함
    sheet.update(f'D{row_idx}', [[new_ticker]])
    sheet.update(f'E{row_idx}', [[target_price]])
    return True

def load_watch_tickers():
    existing = sheet.get_all_values()
    if not existing:
        return []
    tickers = []
    for row in existing[1:]:  # 2행부터 시작
        if len(row) > 3 and row[3].strip():
            tickers.append(row[3].strip())
    return tickers

def save_target_price_to_sheet(ticker, target_price):
    existing = sheet.get_all_values()
    if not existing:
        return False

    for idx, row in enumerate(existing[1:], start=2):  # 2행부터 시작 (1-based)
        if len(row) > 3 and row[3].strip().upper() == ticker.upper():
            sheet.update(f'E{idx}', [[target_price]])
            return True
    return False

def delete_ticker_from_sheet(ticker):
    existing = sheet.get_all_values()
    if not existing:
        return False

    for idx, row in enumerate(existing[1:], start=2):
        if len(row) > 3 and row[3].strip().upper() == ticker.upper():
            # D열, E열 해당 행 지우기 (빈 문자열로)
            sheet.update(f'D{idx}', [[""]])
            sheet.update(f'E{idx}', [[""]])
            return True
    return False

def compact_watch_tickers():
    existing = sheet.get_all_values()
    if len(existing) < 2:
        return

    tickers = []
    prices = []
    for row in existing[1:]:
        t = row[3].strip() if len(row) > 3 else ""
        p = row[4].strip() if len(row) > 4 else ""
        if t:
            tickers.append(t)
            prices.append(p)

    # 기존 D,E열 전체 초기화 (1행 제외)
    num_rows = len(existing)
    clear_ranges = [f'D2:D{num_rows}', f'E2:E{num_rows}']
    sheet.batch_clear(clear_ranges)

    # 정리된 티커, 목표가 다시 입력
    for idx, (t, p) in enumerate(zip(tickers, prices), start=2):
        sheet.update(f'D{idx}', [[t]])
        sheet.update(f'E{idx}', [[p]])

# --- 페이지 구분 ---
page = st.sidebar.radio("페이지 선택", ["홈", "재무제표 보기", "티커 추가", "주식 감시"])

tickers = load_tickers()
sector_list = sorted(set([t["sector"] for t in tickers]))

if page == "홈":
    st.title("📈 주식 티커 재무제표 뷰어")
    st.write("환영합니다!")

elif page == "재무제표 보기":
    st.title("📊 재무제표 보기")

    # ... (기존 재무제표 보기 코드 유지) ...

elif page == "티커 추가":
    st.title("➕ 티커 추가")

    st.write("현재 등록된 섹터:")
    with st.expander("보기"):
        for i, sector in enumerate(sector_list, 1):
            st.write(f"{i}. {sector}")

    new_ticker = st.text_input("추가할 티커 (예: AAPL, Information Technology)")
    if st.button("추가"):
        try:
            ticker, sector = map(str.strip, new_ticker.split(","))
            if save_ticker_to_sheet(ticker, sector):
                st.success(f"{ticker} ({sector}) 추가 완료")
            else:
                st.warning("이미 존재하는 티커입니다.")
        except:
            st.error("형식이 잘못되었습니다. 예: AAPL, Information Technology")

    grouped = defaultdict(list)
    for t in tickers:
        grouped[t["sector"]].append(t["ticker"])

    for sector in sorted(grouped):
        with st.expander(f"{sector} ({len(grouped[sector])}개)"):
            for t in grouped[sector]:
                st.write(f"- {t}")

elif page == "주식 감시":
    st.title("👀 주식 감시")

    # 📌 티커 추가
    new_watch_ticker = st.text_input("감시할 티커 입력 (예: AAPL)")
    if st.button("감시 티커 추가"):
        ticker = new_watch_ticker.strip().upper()
        if ticker:
            if save_watch_ticker_to_sheet(ticker):
                st.success(f"감시 티커 {ticker}가 저장되었습니다!")
            else:
                st.warning("이미 존재하는 감시 티커입니다.")
        else:
            st.error("티커를 올바르게 입력해주세요.")

    # ✅ 감시 목록 로드
    watch_tickers = load_watch_tickers()

    # 📊 현재가 정보 표 만들기
    data = []
    existing = sheet.get_all_values()

    for idx, row in enumerate(existing[1:], start=2):  # 2행부터 감시 티커가 세로 저장
        if len(row) <= 3:
            continue
        ticker = row[3].strip()
        if not ticker:
            continue
        target_price_str = row[4].strip() if len(row) > 4 else ""
        try:
            target_price = float(target_price_str)
            if target_price <= 0:
                st.warning(f"{ticker} 목표가가 0 이하입니다. 건너뜁니다.")
                continue

            try:
                quote = get_quote_with_retry(ticker)
                current_price = quote['c']
                gap_percent = (current_price - target_price) / target_price * 100

                if abs(gap_percent) > 10:
                    color = '⬜️'
                elif abs(gap_percent) > 5:
                    color = '🟩'
                elif abs(gap_percent) > 2.5:
                    color = '🟨'
                else:
                    color = '🟧'

                data.append({
                    "티커": ticker,
                    "목표가": target_price,
                    "현재가": round(current_price, 2),
                    "괴리율 (%)": round(gap_percent, 2),
                    "상태": color
                })

            except Exception as e:
                st.error(f"{ticker} 처리 실패: {e}")

        except ValueError:
            st.warning(f"{ticker}의 목표가 값이 올바르지 않습니다. (예: '{target_price_str}')")

    if data:
        df = pd.DataFrame(data)
        st.dataframe(df)
    else:
        st.info("표시할 데이터가 없습니다.")

    # 🎯 목표가 수정
    st.subheader("🎯 목표가 수정")
    if watch_tickers:
        selected_ticker = st.selectbox("목표가를 수정할 티커 선택", watch_tickers)
        new_price = st.number_input("새 목표가 입력", min_value=0.0, step=1.0, format="%.2f")
        if st.button("목표가 수정"):
            if save_target_price_to_sheet(selected_ticker, new_price):
                st.success(f"{selected_ticker}의 목표가가 {new_price}으로 수정되었습니다.")
            else:
                st.error("수정 실패: 해당 티커를 찾을 수 없습니다.")
    else:
        st.write("감시 중인 티커가 없습니다.")

    # 🗑️ 티커 삭제
    st.subheader("🗑️ 티커 삭제")
    if watch_tickers:
        ticker_to_delete = st.selectbox("삭제할 티커 선택", watch_tickers)
        if st.button("티커 삭제"):
            if delete_ticker_from_sheet(ticker_to_delete):
                compact_watch_tickers()
                st.success(f"{ticker_to_delete}가 감시 리스트에서 삭제되었습니다.")
            else:
                st.error("삭제 실패: 해당 티커를 찾을 수 없습니다.")
    else:
        st.write("감시 중인 티커가 없습니다.")
