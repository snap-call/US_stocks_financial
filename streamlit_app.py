import finnhub
import streamlit as st
import json
import os
import pandas as pd
import time
from dotenv import load_dotenv
from collections import defaultdict

# 현재 파일 위치 기준으로 tickers.json 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TICKER_FILE = os.path.join(BASE_DIR, "tickers.json")

# 1. 파일에서 티커 목록 불러오기
def load_tickers():
    if os.path.exists(TICKER_FILE):
        with open(TICKER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

# 2. 티커 목록 저장
def save_tickers(tickers):
    with open(TICKER_FILE, "w", encoding="utf-8") as f:
        json.dump(tickers, f, ensure_ascii=False, indent=2)

page = st.sidebar.radio("이동할 페이지를 선택하세요", ["홈", "재무제표 보기", "티커 추가"])
tickers = load_tickers()
sector_list = set([ticker["sector"] for ticker in tickers])
sector_list_unique = []
for x in sector_list:
    if x not in sector_list_unique:
        sector_list_unique.append(x)

if page == "홈":
    st.title("📈 주식 티커 재무제표 뷰어")
    st.write("환영합니다!")

elif page == "재무제표 보기":
    st.title("📈 재무제표 보기")

    # 세션 상태 초기화
    if "progress" not in st.session_state:
        st.session_state.progress = 0
    if "status_text" not in st.session_state:
        st.session_state.status_text = ""
    if "error_text" not in st.session_state:
        st.session_state.error_text = ""

    progress_bar = st.progress(st.session_state.progress)
    status_text = st.empty()
    error_text = st.empty()

    # 환경변수에서 API 키 불러오기
    API_KEY = st.secrets["FINNHUB_API_KEY"]
    client = finnhub.Client(api_key=API_KEY)

    # JSON 파일에서 sector별로 ticker 정리
    with open(TICKER_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    sector_to_tickers = {}
    for item in raw_data:
        sector = item["sector"]
        ticker = item["ticker"]
        if sector not in sector_to_tickers:
            sector_to_tickers[sector] = []
        sector_to_tickers[sector].append(ticker)

    # 불러올 지표
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

    # 분위수 방향 (True: 낮을수록 좋음, False: 높을수록 좋음)
    ascending_metrics = {
        'PER': False, 'PBR': False,
        'ROE': True, 'ROA': True,
        'D/E': False, 'CR': True,
        'EV/FCF': False, 'DY': True
    }

    # 색상 정의 (1분위 ~ 4분위)
    quartile_colors = ["#ff8e88", "#f3e671", '#91bfdb', "#87ffbb"]

    # 분위수 기반 색 강조 함수
    def highlight_quartile(series, ascending=True):
        # 숫자 추출 후 변환, 실패시 NaN
        clean_series = pd.to_numeric(series.str.extract(r'([-\d\.]+)')[0], errors='coerce')
        try:
            valid = clean_series.dropna()
            quartiles = pd.qcut(valid.rank(method='first', ascending=ascending), 4, labels=False)
            colors = [''] * len(series)
            for idx, q in zip(valid.index, quartiles):
                colors[idx] = f'background-color: {quartile_colors[q]}'
            return colors
        except Exception as e:
            print(f"highlight_quartile error: {e}")
            return [''] * len(series)

    total = sum(len(tks) for tks in sector_to_tickers.values())
    k = 0

    for sector, tickers in sector_to_tickers.items():
        data_for_pd = []

        for ticker in tickers:
            retries = 0
            max_retries = 5
            success = False

            while retries < max_retries and not success:
                try:
                    data = client.company_basic_financials(ticker, 'all')
                    if not data or 'metric' not in data:
                        st.session_state.error_text = f"❌ {ticker} - 데이터 없음"
                        error_text.warning(st.session_state.error_text)
                        break

                    metric_data = data['metric']
                    row_data = {"Ticker": ticker}
                    for metric, (annual_key, ttm_key) in metrics_pairs.items():
                        val = None
                        flag = ''
                        if ttm_key and metric_data.get(ttm_key) is not None:
                            val = metric_data.get(ttm_key)
                            flag = '(t)'
                        elif annual_key and metric_data.get(annual_key) is not None:
                            val = metric_data.get(annual_key)
                            flag = '(a)'
                        # N/A 대신 None으로
                        row_data[metric] = f"{round(val, 2)} {flag}" if val is not None else None

                    data_for_pd.append(row_data)
                    success = True
                    time.sleep(0.12)

                except Exception as e:
                    retries += 1
                    st.session_state.error_text = f"❌ {ticker} 에러: {e} (재시도 {retries}/{max_retries})"
                    error_text.warning(st.session_state.error_text)
                    time.sleep(10)

            k += 1
            st.session_state.progress = k / total
            st.session_state.status_text = f"✅ {ticker} 처리 완료 ({k}/{total})"
            progress_bar.progress(st.session_state.progress)
            status_text.text(st.session_state.status_text)

        # 표 출력
        if data_for_pd:
            df = pd.DataFrame(data_for_pd).reset_index(drop=True)
            styled_df = df.style
            for metric in metrics_pairs:
                styled_df = styled_df.apply(
                    highlight_quartile,
                    subset=[metric],
                    ascending=ascending_metrics[metric]
                )

            st.subheader(f"📊 {sector}")
            st.dataframe(styled_df, use_container_width=True)

elif page == "티커 추가":
    st.title("티커 추가")

    sectors = defaultdict(list)
    for item in tickers:
        sector = item.get("sector", "기타")
        ticker = item.get("ticker", "")
        sectors[sector].append(ticker)

    st.write("현재 입력 가능한 sector:",)
    with st.expander("더보기"):
        for i, sector in enumerate(sector_list_unique, 1):
            st.write(f"{i}. {sector}")
    new_ticker = st.text_input("추가할 티커 입력 (예: AAPL, Information Technology)", "")
    if st.button("티커 추가"):
        try:
            ticker, sector = map(str.strip, new_ticker.split(","))
            if new_ticker and not any(d['ticker'] == ticker for d in tickers):
                tickers.append({
                    "ticker": ticker,
                    "sector": sector
                })
                save_tickers(tickers)
                st.success(f"{ticker} ({sector}) 추가 완료!")
            else:
                st.warning("이미 존재하는 티커입니다.")
        except Exception:
            st.error("유효한 입력 형식이 아닙니다. 예: AAPL, Information Technology")

    st.write("현재 티커 목록:")

    for sector in sorted(sectors.keys()):
        with st.expander(f"{sector} ({len(sectors[sector])}개)"):
            for i, ticker in enumerate(sectors[sector], 1):
                st.write(f"{i}. {ticker}")
