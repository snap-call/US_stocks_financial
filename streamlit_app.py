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
            # 응답이 유효한지 확인
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

def save_watch_ticker_to_sheet(new_ticker):
    existing = sheet.get_all_values()
    start_col_idx = 4  # D열부터 시작 (A=1)
    first_row = existing[0] if existing else []

    watch_tickers = []
    for col_idx in range(start_col_idx - 1, len(first_row)):
        val = first_row[col_idx].strip() if col_idx < len(first_row) else ""
        if val:
            watch_tickers.append(val)

    if new_ticker in watch_tickers:
        return False

    new_col_idx = start_col_idx + len(watch_tickers)
    col_letter = chr(ord('A') + new_col_idx - 1)
    # 여기서 2차원 리스트로 감싸기!
    sheet.update(f'{col_letter}1', [[new_ticker]])
    return True

def load_watch_tickers():
    existing = sheet.get_all_values()
    if not existing:
        return []
    first_row = existing[0]
    start_col_idx = 4
    watch_tickers = []
    for col_idx in range(start_col_idx - 1, len(first_row)):
        val = first_row[col_idx].strip()
        if val:
            watch_tickers.append(val)
    return watch_tickers

def save_target_price_to_sheet(ticker, target_price):
    existing = sheet.get_all_values()
    if not existing or len(existing) < 2:
        return False

    first_row = existing[0]  # 티커
    start_col_idx = 3  # D열 = index 3

    for col_idx in range(start_col_idx, len(first_row)):
        if first_row[col_idx].strip().upper() == ticker.upper():
            col_letter = chr(ord('A') + col_idx)
            sheet.update(f'{col_letter}2', [[target_price]])
            return True
    return False
def delete_ticker_from_sheet(ticker):
    existing = sheet.get_all_values()
    if not existing:
        return False

    first_row = existing[0]
    start_col_idx = 3

    for col_idx in range(start_col_idx, len(first_row)):
        if first_row[col_idx].strip().upper() == ticker.upper():
            col_letter = chr(ord('A') + col_idx)
            sheet.batch_clear([f'{col_letter}1', f'{col_letter}2'])
            return True
    return False
def compact_watch_tickers():
    existing = sheet.get_all_values()
    if len(existing) < 2:
        return

    tickers_row = existing[0]
    prices_row = existing[1]

    # D열부터 끝까지 유효한 티커만 추출
    tickers = []
    prices = []
    for i in range(3, len(tickers_row)):  # D열 = index 3
        t = tickers_row[i].strip()
        p = prices_row[i].strip() if i < len(prices_row) else ""
        if t:
            tickers.append(t)
            prices.append(p)

    # 기존 시트 영역 초기화
    num_cols = len(tickers_row)
    clear_ranges = [f'{chr(ord("A")+i)}1:{chr(ord("A")+i)}2' for i in range(3, num_cols)]
    sheet.batch_clear(clear_ranges)

    # 새로 재정렬해서 입력
    for idx, (t, p) in enumerate(zip(tickers, prices)):
        col_letter = chr(ord('A') + 3 + idx)
        sheet.update(f'{col_letter}1', [[t]])
        sheet.update(f'{col_letter}2', [[p]])

# --- 페이지 구분 ---
page = st.sidebar.radio("페이지 선택", ["홈", "재무제표 보기", "티커 추가", "주식 감시"])

tickers = load_tickers()
sector_list = sorted(set([t["sector"] for t in tickers]))

if page == "홈":
    st.title("📈 주식 티커 재무제표 뷰어")
    st.write("환영합니다!")

elif page == "재무제표 보기":
    st.title("📊 재무제표 보기")

    metrics_pairs = {
        'PER': ('peAnnual', 'peTTM'),
        'PBR': ('pbAnnual', None),
        'ROE': ('roeRfy', 'roeTTM'),
        'ROA': ('roaRfy', 'roaTTM'),
        'D/E': ('totalDebt/totalEquityAnnual', None),
        'CR': ('currentRatioAnnual', None),
        'EV/FCF': ('currentEv/freeCashFlowAnnual', 'currentEv/freeCashFlowTTM'),
        'DY': ('dividendYieldIndicatedAnnual', None),
    }

    ascending_metrics = {
        'PER': False, 'PBR': False,
        'ROE': True, 'ROA': True,
        'D/E': False, 'CR': True,
        'EV/FCF': False, 'DY': True,
    }

    sector_to_tickers = defaultdict(list)
    for item in tickers:
        sector_to_tickers[item["sector"]].append(item["ticker"])

    def highlight_quartile(series, ascending=True):
        clean_series = pd.to_numeric(series.str.extract(r'([\-\d\.]+)')[0], errors='coerce')
        try:
            valid = clean_series.dropna()
            quartiles = pd.qcut(valid.rank(method='first', ascending=ascending), 4, labels=False)
            colors = [''] * len(series)
            for idx, q in zip(valid.index, quartiles):
                colors[idx] = f'background-color: {["#ff8e88", "#f3e671", "#91bfdb", "#87ffbb"][q]}'
            return colors
        except:
            return [''] * len(series)

    total = sum(len(tks) for tks in sector_to_tickers.values())
    k = 0
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    error_text = st.empty()

    for sector, tickers_ in sector_to_tickers.items():
        data_for_pd = []
        for ticker in tickers_:
            retries = 0
            max_retries = 5
            while retries < max_retries:
                try:
                    data = client.company_basic_financials(ticker, 'all')
                    if 'metric' not in data:
                        break
                    metric_data = data['metric']
                    row = {"Ticker": ticker}
                    for metric, (annual_key, ttm_key) in metrics_pairs.items():
                        val = None
                        flag = ''
                        if ttm_key and metric_data.get(ttm_key) is not None:
                            val = metric_data[ttm_key]
                            flag = '(t)'
                        elif annual_key and metric_data.get(annual_key) is not None:
                            val = metric_data[annual_key]
                            flag = '(a)'
                        row[metric] = f"{round(val, 2)} {flag}" if val is not None else None
                    data_for_pd.append(row)
                    time.sleep(0.12)
                    break
                except Exception as e:
                    retries += 1
                    error_text.warning(f"❌ {ticker} 에러: {e} (재시도 {retries}/{max_retries})")
                    time.sleep(10)

            k += 1
            progress_bar.progress(k / total)
            status_text.text(f"✅ {ticker} 처리 완료 ({k}/{total})")

        if data_for_pd:
            df = pd.DataFrame(data_for_pd)
            styled_df = df.style
            for metric in metrics_pairs:
                styled_df = styled_df.apply(
                    highlight_quartile,
                    subset=[metric],
                    ascending=ascending_metrics[metric]
                )
            st.subheader(f"📍 {sector}")
            st.dataframe(styled_df, use_container_width=True)

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
    st.write("※ 현재 감시할 티커 목록:")
    st.write(", ".join(watch_tickers) if watch_tickers else "없음")

    # 📊 현재가 정보 표 만들기
    data = []
    existing = sheet.get_all_values()
    first_row = existing[0]
    second_row = existing[1] if len(existing) > 1 else []

    for col_idx in range(3, len(first_row)):
        ticker = first_row[col_idx].strip()
        if not ticker:
            continue

        try:
            target_price_str = second_row[col_idx].strip() if col_idx < len(second_row) else ""
            if not target_price_str:
                continue

            target_price = float(target_price_str)

            try:
                quote = get_quote_with_retry(ticker)  # ✅ 재시도 함수 사용
                current_price = quote['c']
                gap_percent = (current_price - target_price) / target_price * 100

                # 색상 조건
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

    # 📊 표 출력
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
