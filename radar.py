import sys
import time
import re
import subprocess
from datetime import datetime
from collections import deque

def auto_install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    import requests
except ImportError:
    auto_install("requests")
    import requests

try:
    import xml.etree.ElementTree as ET
except ImportError:
    pass

try:
    import yfinance as yf
except ImportError:
    auto_install("yfinance")
    import yfinance as yf

try:
    from deep_translator import GoogleTranslator
    translator = GoogleTranslator(source='auto', target='ko')
except ImportError:
    try:
        auto_install("deep-translator")
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='auto', target='ko')
    except Exception:
        translator = None

TELEGRAM_BOT_TOKEN = "8940691671:AAGG8zhJuRY-SA4ew500bSx5aX9ZgsQzJes"
TELEGRAM_CHAT_ID = "8959379899"

MY_HOLDINGS = ['GPUS', 'CLDI', 'BNAI']

SEC_HEADERS = {
    'User-Agent': 'TaeYoungHeavyResearch radar_admin@taeyoung.com',
    'Accept-Encoding': 'gzip, deflate'
}

WEB_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,/;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}

session = requests.Session()
session.headers.update(SEC_HEADERS)

seen_filings = deque(maxlen=2000)
recent_ticker_alerts = {}
cik_to_ticker = {}
ticker_to_cik = {}
cik_to_name = {}
is_first_run = True
loop_counter = 0

ITEM_8K_MAP = {
    "1.01": ("🔥 [호재/계약] 중요 본계약 체결 (파트너십/투자의향/공급계약 등)", True),
    "1.02": ("⚠️ [주의/해지] 기존 중요 계약의 해지 또는 종료", False),
    "1.03": ("🚨 [초특급악재] 파산 또는 법정관리 신청!", False),
    "2.01": ("🔥 [대형이벤트] 기업 인수합병(M&A) 또는 주요 자산 취득/처분 완료", True),
    "2.02": ("📊 [실적발표] 분기/연간 영업 실적 및 재무 상태 공식 발표", None),
    "2.03": ("⚠️ [채무발생] 신규 금융 채무 또는 대출 약정 발생", None),
    "2.04": ("🚨 [악재/채무] 채무 불이행(디폴트) 또는 원리금 상환 독촉 이벤트", False),
    "3.01": ("⚡ [상장유지/변동] 나스닥 상장 조건 통보 (경고인지 '회복/유예' 호재인지 원문 필독)", None),
    "3.02": ("⚠️ [주의/희석] 미등록 지분 증권(신주/전환사채 등) 발행 판매", False),
    "3.03": ("ℹ️ [권리변동] 주주 권리의 중대한 변경 (주식병합/정관변경 등)", None),
    "4.01": ("⚠️ [회계법인] 기존 회계 감사인 교체 (재무 이슈 점검 필요)", False),
    "4.02": ("🚨 [악재/회계오류] 과거 재무제표 신뢰 불가 판정 (분식회계/재작성 위험)", False),
    "5.02": ("👤 [인사변동] 핵심 임원(CEO/CFO) 또는 이사진 사임/선임", None),
    "5.03": ("ℹ️ [정관변경] 기업 정관 개정 또는 회계연도 변경 (주식병합 여부 확인)", None),
    "5.07": ("🗳️ [주주총회] 주주총회 안건 투표 결과 공식 보고", None),
    "7.01": ("📢 [공식발표] Regulation FD 공시 (프레젠테이션/임상결과/신사업 보도자료)", True),
    "8.01": ("⚡ [핵심이벤트] 기타 주요 경영 이벤트 발표 (자사주매입/임상승인/상폐회복 등)", True)
}

def load_sec_ticker_map():
    global cik_to_ticker, ticker_to_cik, cik_to_name
    try:
        print("📥 SEC 공식 거래소 상장 데이터베이스 동기화 중...")
        url = "https://www.sec.gov/files/company_tickers_exchange.json"
        res = session.get(url, timeout=15)
        if res.status_code == 200:
            data = res.json()
            fields = data.get('fields', [])
            rows = data.get('data', [])
            
            cik_idx = fields.index('cik') if 'cik' in fields else 0
            name_idx = fields.index('name') if 'name' in fields else 1
            ticker_idx = fields.index('ticker') if 'ticker' in fields else 2
            exch_idx = fields.index('exchange') if 'exchange' in fields else 3
            
            for row in rows:
                exch = str(row[exch_idx] or '').upper()
                if any(valid in exch for valid in ['NASDAQ', 'NYSE', 'AMEX', 'BATS', 'CBOE']):
                    cik_str = str(row[cik_idx]).zfill(10)
                    tkr = str(row[ticker_idx]).upper().strip()
                    if '-' not in tkr:
                        cik_to_ticker[cik_str] = tkr
                        ticker_to_cik[tkr] = cik_str
                        cik_to_name[cik_str] = str(row[name_idx]).title()
                        
            print(f"✅ 정식 상장사 DB 장착 완료! (나스닥/NYSE: {len(cik_to_ticker)}개)")
        else:
            print(f"⚠️ 거래소 DB 로드 지연 (상태코드: {res.status_code})")
    except Exception as e:
        print(f"⚠️ 거래소 DB 로드 실패: {e}")

HISTORICAL_SURGE_PATTERNS = [
    {
        "pattern_name": "클래식 숏스퀴즈형 (품절주 + 고공매도/고CTB 화약고)",
        "max_float": 10_000_000,
        "min_short": 15.0,
        "required_form": ["8-K", "SC 13D", "6-K", "RW", "PRE-SURGE"],
        "weight": 40
    },
    {
        "pattern_name": "폭등 직전 바닥 매집형 (시총 $150M 이하 + 거래량 급증 + 미분출)",
        "max_market_cap": 150_000_000,
        "min_vol_spike": 2.2,
        "required_form": ["8-K", "Form 4", "6-K", "SC 13D", "PRE-SURGE"],
        "weight": 35
    },
    {
        "pattern_name": "내부자/세력 바닥 매집형 (Form 4/13D + OBV 우상향)",
        "min_obv_score": 10,
        "required_form": ["4", "SC 13D", "13G", "PRE-SURGE"],
        "weight": 25
    }
]

def send_telegram_msg(message, is_loud=False):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": not is_loud
    }
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception:
        pass

def parse_human_number(val_str):
    if not val_str or val_str == '-':
        return 0
    val_str = val_str.upper().replace(',', '').replace('%', '').strip()
    try:
        if val_str.endswith('B'):
            return float(val_str[:-1]) * 1_000_000_000
        elif val_str.endswith('M'):
            return float(val_str[:-1]) * 1_000_000
        elif val_str.endswith('K'):
            return float(val_str[:-1]) * 1_000
        else:
            return float(val_str)
    except Exception:
        return 0

def scrape_finviz_data(ticker):
    res_data = {
        "market_cap": 0, "float_shares": 0, "short_pct": 0.0,
        "price": 0.0, "change_pct": 0.0, "rel_volume": 0.0, "valid": False
    }
    try:
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        res = requests.get(url, headers=WEB_HEADERS, timeout=8)
        if res.status_code != 200:
            return res_data
        
        res_data["valid"] = True
        clean_text = re.sub(r'<[^>]+>', '|', res.text)
        tokens = [t.strip() for t in clean_text.split('|') if t.strip()]
        
        for i, token in enumerate(tokens):
            if token == "Market Cap" and i + 1 < len(tokens):
                res_data["market_cap"] = parse_human_number(tokens[i+1])
            elif token == "Shs Float" and i + 1 < len(tokens):
                res_data["float_shares"] = parse_human_number(tokens[i+1])
            elif token == "Short Float" and i + 1 < len(tokens):
                val = tokens[i+1].replace('%', '').strip()
                try:
                    res_data["short_pct"] = float(val)
                except Exception:
                    pass
            elif token == "Price" and i + 1 < len(tokens):
                res_data["price"] = parse_human_number(tokens[i+1])
            elif token == "Change" and i + 1 < len(tokens):
                val = tokens[i+1].replace('%', '').strip()
                try:
                    res_data["change_pct"] = float(val)
                except Exception:
                    pass
            elif token == "Rel Volume" and i + 1 < len(tokens):
                try:
                    res_data["rel_volume"] = float(tokens[i+1])
                except Exception:
                    pass
    except Exception:
        pass
    return res_data

def scrape_ctb_rate(ticker):
    try:
        for exch in ['nasdaq', 'nyse', 'amex']:
            url = f"https://chartexchange.com/symbol/{exch}-{ticker.lower()}/borrow-fee/"
            res = requests.get(url, headers=WEB_HEADERS, timeout=5)
            if res.status_code == 200:
                m = re.search(r'Latest Fee Rate.*?([\d\.,]+)%', res.text, re.IGNORECASE)
                if not m:
                    m = re.search(r'current borrow fee rate of\s+([\d\.,]+)%', res.text, re.IGNORECASE)
                if m:
                    val = float(m.group(1).replace(',', ''))
                    if 0 < val < 5000:
                        return val
                break
    except Exception:
        pass
    return 0.0

def find_best_sentences(html_content):
    raw_html = html_content[:90000]
    raw_html = re.sub(r'<(script|style)[^>]>.?</\1>', ' ', raw_html, flags=re.DOTALL | re.IGNORECASE)
    clean_doc = re.sub(r'<[^>]+>', ' ', raw_html)
    clean_doc = re.sub(r'&#\d+;|&[a-zA-Z]+;', ' ', clean_doc)
    clean_doc = re.sub(r'\s+', ' ', clean_doc).strip()

    sentences = re.split(r'(?<=[.!?])\s+', clean_doc)
    good_sentences = []
    
    boiler_keywords = [
        'UNITED STATES', 'SECURITIES AND EXCHANGE', 'WASHINGTON', 'COMMISSION FILE',
        'EXACT NAME OF REGISTRANT', 'CHECK THE APPROPRIATE BOX', 'EMERGING GROWTH COMPANY',
        'PURSUANT TO SECTION', 'FORM 8-K', 'FORM 6-K', 'CURRENT REPORT', 'TABLE OF CONTENTS',
        'SIGNATURE', 'TELEPHONE NUMBER', 'ZIP CODE', 'DELAWARE', 'NEVADA', 'FORWARD-LOOKING',
        'FURNISHED HEREWITH', 'INCORPORATED BY REFERENCE', 'EXHIBIT 99'
    ]
    action_keywords = [
        'ENTERED INTO', 'ANNOUNCED', 'AGREEMENT', 'ACQUIRED', 'APPROVED', 'FDA', 'PATENT',
        'MILLION', 'BILLION', '$', 'SHARES', 'OFFERING', 'WARRANT', 'CLINICAL', 'REVENUE',
        'PARTNERSHIP', 'CONTRACT', 'DIVIDEND', 'SPLIT', 'NASDAQ', 'COMPLIANCE', 'PURCHASE',
        'ISSUED', 'LOAN', 'DEBT', 'MERGER', 'TRIAL', 'GRANTED', 'TERMINATED', 'APPOINTED',
        'RESULTS', 'LAUNCHED', 'SIGNED', 'CLOSED', 'PRICE OF', 'REGAINED', 'WITHDRAW'
    ]

    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) < 40 or len(s_clean) > 380:
            continue
        s_up = s_clean.upper()
        if any(b in s_up for b in boiler_keywords):
            continue
        if any(a in s_up for a in action_keywords):
            good_sentences.append(s_clean)
            if len(good_sentences) >= 2:
                break
    return good_sentences, clean_doc

def extract_real_filing_summary(form_type, index_link, summary_html):
    form_upper = form_type.upper()
    bullet_1 = ""
    bullet_2 = ""
    sentiment_override = None
    full_scanned_text = ""

    try:
        detected_items = re.findall(r'Item\s+(\d+\.\d+)', summary_html, re.IGNORECASE)
        
        res = session.get(index_link, timeout=10)
        index_text = res.text if res.status_code == 200 else ""
        full_scanned_text += " " + index_text[:20000]
        
        if not detected_items and index_text:
            detected_items = re.findall(r'Item\s+(\d+\.\d+)', index_text, re.IGNORECASE)

        if detected_items:
            unique_items = []
            for it in detected_items:
                if it not in unique_items and it in ITEM_8K_MAP:
                    unique_items.append(it)
            if unique_items:
                descriptions = []
                for it in unique_items[:2]:
                    desc, sent = ITEM_8K_MAP[it]
                    descriptions.append(f"[Item {it}] {desc}")
                    if sent is False:
                        sentiment_override = False
                    elif sent is True and sentiment_override is not False:
                        sentiment_override = True
                bullet_1 = "• " + " / ".join(descriptions)

        if form_upper == '4' or 'FORM 4' in form_upper:
            xml_links = re.findall(r'href="(/Archives/edgar/data/[^"]+\.xml)"', index_text)
            raw_xml_url = None
            for xl in xml_links:
                if 'xsl' not in xl.lower():
                    raw_xml_url = "https://www.sec.gov" + xl
                    break
            if not raw_xml_url and xml_links:
                raw_xml_url = "https://www.sec.gov" + re.sub(r'/xsl[^/]+/', '/', xml_links[0])

            if raw_xml_url:
                x_res = session.get(raw_xml_url, timeout=8)
                if x_res.status_code == 200:
                    x_text = x_res.text
                    owner_m = re.search(r'<rptOwnerName>\s*([^<]+)\s*</rptOwnerName>', x_text)
                    owner_name = owner_m.group(1).strip().title() if owner_m else "내부자(임원/대주주)"
                    
                    acq_disp = re.findall(r'<transactionAcquiredDisposedCode>\s*<value>\s*([AD])\s*</value>', x_text)
                    shares_list = re.findall(r'<transactionShares>\s*<value>\s*([\d\.]+)\s*</value>', x_text)
                    prices_list = re.findall(r'<transactionPricePerShare>\s*<value>\s*([\d\.]+)\s*</value>', x_text)
                    
                    total_buy = 0.0
                    total_sell = 0.0
                    avg_price = float(prices_list[0]) if prices_list else 0.0

                    for idx, code in enumerate(acq_disp):
                        sh = float(shares_list[idx]) if idx < len(shares_list) else 0.0
                        if code == 'A':
                            total_buy += sh
                        elif code == 'D':
                            total_sell += sh

                    price_str = f"(단가 약 ${avg_price:.2f})" if avg_price > 0 else "(스톡옵션/보상 부여)"
                    if total_buy > 0 and total_sell == 0:
                        bullet_1 = f"• 🔥 [내부자 취득] {owner_name}: 총 {total_buy:,.0f}주 신규 취득/매수 {price_str}"
                        bullet_2 = "• 내부자 지분 확대 팩트 포착! 바닥권 책임 경영 및 주가 부양 시그널."
                        sentiment_override = True
                        return f"{bullet_1}\n{bullet_2}", sentiment_override, full_scanned_text
                    elif total_sell > 0 and total_buy == 0:
                        bullet_1 = f"• ⚠️ [내부자 처분] {owner_name}: 총 {total_sell:,.0f}주 장내 매도/처분 {price_str}"
                        bullet_2 = "• 내부자 차익 실현 또는 물량 출회 팩트! 단기 수급 저항 주의."
                        sentiment_override = False
                        return f"{bullet_1}\n{bullet_2}", sentiment_override, full_scanned_text

        doc_links = re.findall(r'href="(/Archives/edgar/data/[^"]+\.(?:htm|html|txt))"', index_text, re.IGNORECASE)
        main_doc_url = None
        exhibit_doc_url = None
        
        for dl in doc_links:
            dl_low = dl.lower()
            if 'index' in dl_low or 'r1.htm' in dl_low:
                continue
            if not main_doc_url:
                main_doc_url = "https://www.sec.gov" + dl
            if any(ex in dl_low for ex in ['ex99', 'ex-99', 'ex_99', 'press', 'pr']):
                exhibit_doc_url = "https://www.sec.gov" + dl
                break

        good_sentences = []
        if main_doc_url:
            d_res = session.get(main_doc_url, timeout=8)
            if d_res.status_code == 200:
                good_sentences, clean_doc = find_best_sentences(d_res.text)
                full_scanned_text += " " + clean_doc

        if len(good_sentences) == 0 and exhibit_doc_url:
            ex_res = session.get(exhibit_doc_url, timeout=8)
            if ex_res.status_code == 200:
                good_sentences, clean_ex = find_best_sentences(ex_res.text)
                full_scanned_text += " " + clean_ex

        if good_sentences:
            if not bullet_1:
                s1_kr = translator.translate(good_sentences[0][:300]) if translator else good_sentences[0][:300]
                bullet_1 = f"• [원문 팩트1] {s1_kr}"
                if len(good_sentences) > 1:
                    s2_kr = translator.translate(good_sentences[1][:300]) if translator else good_sentences[1][:300]
                    bullet_2 = f"• [원문 팩트2] {s2_kr}"
            else:
                s1_kr = translator.translate(good_sentences[0][:300]) if translator else good_sentences[0][:300]
                bullet_2 = f"• [원문 요약] {s1_kr}"

        scan_up = full_scanned_text.upper()
        if any(good_comp in scan_up for good_comp in [
            'REGAINED COMPLIANCE', 'HAS REGAINED COMPLIANCE', 'EXTENSION OF 180 CALENDAR DAYS',
            'ADDITIONAL 180-DAY', 'WITHDRAWAL OF REGISTRATION', 'REQUEST TO WITHDRAW'
        ]):
            sentiment_override = True
            bullet_1 = "• 🔥 [특급호재 판독] 나스닥 상장유지 조건 회복(또는 유예 승인 / 유증 철회) 공식 확인!"
        elif any(bad in scan_up for bad in ['BANKRUPTCY', 'CHAPTER 11', 'RECEIVERSHIP', 'DELISTING DETERMINATION']):
            sentiment_override = False
        elif any(warn in scan_up for warn in ['NOT IN COMPLIANCE', 'DEFICIENCY LETTER', 'FAILS TO COMPLY']):
            if 'REGAINED' not in scan_up:
                sentiment_override = False
        elif any(dil in scan_up for dil in ['REGISTERED DIRECT OFFERING', 'PUBLIC OFFERING', 'UNDERWRITTEN OFFERING']):
            sentiment_override = False

    except Exception:
        pass

    if not bullet_1:
        if 'RW' in form_upper:
            bullet_1 = "• 🔥 [유증 철회(RW)] 기존 신청했던 신주 발행/유상증자 등록을 공식 철회함 (희석 해소 호재)!"
            sentiment_override = True
        elif '13D' in form_upper or '13G' in form_upper:
            bullet_1 = "• [대량 지분 보고] 외부 기관/큰손 투자자의 5% 이상 지분 취득 또는 변동 보고."
        elif any(f in form_upper for f in ['S-1', 'S-3', '424B']):
            bullet_1 = "• [신주/유증 등록] 자금 조달을 위한 신주 발행 또는 전환사채/워런트 물량 등록."
            sentiment_override = False
        elif '144' in form_upper:
            bullet_1 = "• [매각 예정 통지] 주요 주주 또는 임원의 보유 주식 장내 매각 예정 신고."
            sentiment_override = False
        else:
            bullet_1 = f"• [{form_type} 공시 접수] 기업 주요 경영 사항 및 첨부 보도자료(Exhibit) 제출."

    if not bullet_2:
        if sentiment_override is False:
            bullet_2 = "• ⚠️ 하방 압력 또는 지분 희석 리스크 감지. 섣부른 진입 자제 및 원문 확인 필수."
        elif sentiment_override is True:
            bullet_2 = "• 🔥 폭등 도화선이 될 핵심 재료 포함! 바닥 수급 결합 시 1순위 공략 대상."
        else:
            bullet_2 = "• 📄 세부 재무 수치나 일반 경영 보고입니다. 하단 SEC 원문 링크 참고."

    return f"{bullet_1}\n{bullet_2}", sentiment_override, full_scanned_text

def check_dilution_and_switches(cik, ticker, current_doc_text=""):
    atm_on = False
    toxic_on = False
    eloc_on = False
    atm_detail = ""
    toxic_detail = ""
    shield_msg = "🟢 [클린] 최근 주요 공시 내 유증/워런트 폭탄 징후 없음!"

    doc_up = (current_doc_text or "").upper()

    amt_match = re.search(r'UP TO\s+\$\s*([\d\.,]+)\s*(MILLION|M\b)', doc_up)
    if amt_match:
        atm_detail = f":${amt_match.group(1)}M"

    ex_match = re.search(r'EXERCISE PRICE OF\s+\$\s*([\d\.]+)', doc_up)
    if ex_match:
        toxic_detail = f":행사가${ex_match.group(1)}"

    if any(k in doc_up for k in [
        'AT-THE-MARKET', 'AT THE MARKET', 'ATM OFFERING', 'ATM PROGRAM',
        'EQUITY DISTRIBUTION AGREEMENT', 'CONTROLLED EQUITY OFFERING', 'SALES AGREEMENT'
    ]):
        atm_on = True

    if any(k in doc_up for k in [
        'EQUITY LINE OF CREDIT', 'ELOC', 'STANDBY EQUITY PURCHASE AGREEMENT',
        'STANDBY EQUITY DISTRIBUTION', 'COMMITTED EQUITY FACILITY', 'YORKVILLE'
    ]):
        eloc_on = True

    if any(k in doc_up for k in [
        'CONVERTIBLE PROMISSORY NOTE', 'SENIOR CONVERTIBLE NOTE', 'VARIABLE RATE',
        'TOXIC', 'DEATH SPIRAL', 'COMMON STOCK PURCHASE WARRANT',
        'RESET PRICE', 'FLOOR PRICE', 'STREETERVILLE', 'LIND GLOBAL', 'IONIC VENTURES', 'SABBY'
    ]):
        toxic_on = True

    if cik:
        try:
            cik_padded = str(cik).zfill(10)
            sub_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
            res = session.get(sub_url, timeout=8)
            if res.status_code == 200:
                sub_data = res.json()
                recent = sub_data.get('filings', {}).get('recent', {})
                forms = recent.get('form', [])[:20]
                items = recent.get('items', [])[:20]

                has_s3 = False
                has_424b = False
                has_s1 = False
                has_rw = False

                for idx, f in enumerate(forms):
                    f_up = str(f).upper()
                    it_str = str(items[idx]) if idx < len(items) else ""

                    if f_up == 'RW':
                        has_rw = True
                    elif f_up in ['S-3', 'S-3ASR', 'F-3']:
                        has_s3 = True
                    elif f_up == '424B5':
                        has_424b = True
                        atm_on = True
                    elif f_up in ['424B3', '424B4']:
                        has_424b = True
                        toxic_on = True
                    elif f_up in ['S-1', 'S-1/A', 'F-1'] and not has_rw:
                        has_s1 = True
                        toxic_on = True

                    if f_up == '8-K' and '3.02' in it_str and '2.03' in it_str:
                        toxic_on = True

                if has_rw and not has_424b:
                    shield_msg = "🔥 [클린/호재] 최근 RW(유상증자 철회) 공시로 오버행 해소!"
                elif has_424b and atm_on:
                    shield_msg = f"🚨 [위험] 최근 424B5(ATM 수시유증{atm_detail}) 가동 이력 포착!"
                elif has_424b:
                    shield_msg = f"🚨 [위험] 최근 424B(워런트/신주발행{toxic_detail}) 이력 포착!"
                elif has_s3:
                    shield_msg = "⚠️ [경계] 최근 S-3(선반유증 등록) 이력 존재!"
                elif has_s1:
                    shield_msg = "🚨 [위험] 최근 S-1(대규모 신주/워런트 유증) 이력 발견!"
        except Exception:
            pass

    if atm_on or toxic_on or eloc_on:
        active_list = []
        if atm_on: active_list.append("ATM")
        if toxic_on: active_list.append("TOXIC")
        if eloc_on: active_list.append("ELOC")
        if "🟢" in shield_msg:
            shield_msg = f"🚨 [위험] 공시 내 {', '.join(active_list)} 물량 희석 징후 포착!"

    atm_str = f"ATM(🚨ON{atm_detail})" if atm_on else "ATM(🟢OFF)"
    toxic_str = f"TOXIC(🚨ON{toxic_detail})" if toxic_on else "TOXIC(🟢OFF)"
    eloc_str = f"ELOC(🚨ON)" if eloc_on else "ELOC(🟢OFF)"
    
    switch_line = f"{atm_str} | {toxic_str} | {eloc_str}"
    is_any_toxic_on = atm_on or toxic_on or eloc_on
    
    return shield_msg, switch_line, is_any_toxic_on

def analyze_chart_smart_money(stock, daily_change_pct=0.0):
    if not yf or stock is None:
        return "차트 분석 미활성", 0, False, 1.0, 0
    try:
        df = stock.history(period="5d", interval="5m", prepost=True)
        if df is None or df.empty or len(df) < 5:
            return "⚖️ [차트 수급] 장 시작 전 또는 거래량 극소", 0, False, 1.0, 0
            
        closes = df['Close'].values
        volumes = df['Volume'].values
        last_price = float(closes[-1]) if len(closes) > 0 else 0
        
        obv = [0]
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]:
                obv.append(obv[-1] + volumes[i])
            elif closes[i] < closes[i-1]:
                obv.append(obv[-1] - volumes[i])
            else:
                obv.append(obv[-1])
                
        obv_trend_up = obv[-1] > obv[-4] if len(obv) >= 4 else True
        avg_vol = sum(volumes[:-5]) / len(volumes[:-5]) if len(volumes) > 5 else volumes[0]
        recent_vol = max(volumes[-3:]) if len(volumes) >= 3 else volumes[-1]
        
        vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0
        is_vol_spike = vol_ratio >= 2.2
        
        chart_score = 0
        if daily_change_pct >= 25.0:
            status = f"⚠️ [이미 급등중: +{daily_change_pct:.1f}%] 추격 매수 주의 (눌림목 대기)"
            chart_score = -10
        elif obv_trend_up and is_vol_spike and (-5.0 <= daily_change_pct < 15.0):
            status = f"🦈 [폭등 직전 매집포착] 바닥권 거래량 {vol_ratio:.1f}배 폭발 + OBV 매집!"
            chart_score = 35
        elif obv_trend_up and is_vol_spike:
            status = f"🔥 [수급 폭증] 5분봉 세력 유입 (거래량 {vol_ratio:.1f}배)"
            chart_score = 25
        elif not obv_trend_up and is_vol_spike:
            status = "🏃‍♂️ [수급 이탈] 5분봉 대량 매도 및 윗꼬리 설거지 경고"
            chart_score = -20
        elif obv_trend_up:
            status = "📈 [차트 수급] 바닥권 완만한 세력 매집세 (OBV 우상향)"
            chart_score = 15
        else:
            status = "⚖️ [차트 수급] 특이 수급 움직임 없음 (관망세)"
            chart_score = 0
            
        return status, chart_score, is_vol_spike, vol_ratio, last_price
    except Exception:
        return "⚖️ [차트 수급] 실시간 차트 연동 대기 중", 0, False, 1.0, 0

def get_market_data(ticker, is_holding=False):
    if not yf or ticker == "UNKNOWN":
        return None
        
    if len(ticker) >= 5 and ticker[-1] in ['W', 'U', 'R', 'P', 'F', 'Q']:
        return None

    try:
        stock = yf.Ticker(ticker)
        try:
            hist = stock.history(period="2d")
        except Exception:
            hist = None

        fv_data = scrape_finviz_data(ticker)
        market_cap = fv_data["market_cap"]
        float_shares = fv_data["float_shares"]
        short_pct = fv_data["short_pct"]
        current_price = fv_data["price"]
        change_pct = fv_data["change_pct"]

        if not fv_data["valid"] and (hist is None or hist.empty or hist['Volume'].sum() == 0):
            return None

        chart_status, chart_score, is_vol_spike, vol_ratio, chart_price = analyze_chart_smart_money(stock, change_pct)
        if current_price == 0 and chart_price > 0:
            current_price = chart_price

        if market_cap == 0 or float_shares == 0:
            try:
                info = stock.info
                if info and isinstance(info, dict):
                    exch_code = str(info.get('exchange', '')).upper()
                    if any(otc in exch_code for otc in ['PNK', 'OTC', 'GREY']):
                        return None
                    if market_cap == 0:
                        market_cap = info.get('marketCap', 0) or 0
                    if float_shares == 0:
                        float_shares = info.get('floatShares', info.get('sharesOutstanding', 0)) or 0
                    if short_pct == 0:
                        short_raw = info.get('shortPercentOfFloat', 0) or 0
                        short_pct = short_raw * 100 if 0 < short_raw <= 1.0 else short_raw
            except Exception:
                pass

        if market_cap == 0 and current_price > 0 and float_shares > 0:
            market_cap = current_price * float_shares

        if not is_holding and market_cap == 0 and current_price == 0:
            return None

        borrow_pct = scrape_ctb_rate(ticker)
        
        latest_news = "특이 뉴스 없음"
        is_key_news = False
        
        try:
            news_list = stock.news
            if news_list and len(news_list) > 0:
                first_news = news_list[0]
                headline = "최신 뉴스 없음"
                if isinstance(first_news, dict):
                    content = first_news.get('content', {})
                    if isinstance(content, dict) and 'title' in content:
                        headline = content['title']
                    else:
                        headline = first_news.get('title', first_news.get('headline', '최신 뉴스 없음'))
                elif hasattr(first_news, 'title'):
                    headline = first_news.title
                
                if headline and headline != "최신 뉴스 없음":
                    latest_news = headline
                    key_keywords = [
                        'NVIDIA', 'AI', 'DATA CENTER', 'AGREEMENT', 'CONTRACT', 'PARTNERSHIP', 
                        'FDA', 'PATENT', 'SUPPLY', 'ORDERS', 'MERGER', 'ACQUISITION', 
                        'RECORD', 'BEAT', 'SURGE', 'JUMP', 'SOAR', 'APPROVAL', 'CLINICAL', 
                        'PHASE', 'GRANT', 'FUNDING', 'INVESTMENT', 'LAUNCH', 'EXPANSION', 'COMPLIANCE'
                    ]
                    if any(k in headline.upper() for k in key_keywords):
                        is_key_news = True
        except Exception:
            pass

        return {
            "market_cap": market_cap,
            "price": current_price,
            "change_pct": change_pct,
            "float_shares": float_shares,
            "short_pct": short_pct,
            "borrow_pct": borrow_pct,
            "latest_news": latest_news,
            "is_key_news": is_key_news,
            "chart_status": chart_status,
            "chart_score": chart_score,
            "is_vol_spike": is_vol_spike,
            "vol_ratio": max(vol_ratio, fv_data.get("rel_volume", 1.0))
        }
    except Exception:
        return None

def parse_company_and_ticker(title):
    ticker = "UNKNOWN"
    comp_name = "미국 상장 기업"
    cik = None
    
    cik_matches = re.findall(r'\((\d{10})\)', title)
    for c in cik_matches:
        if c in cik_to_ticker:
            cik = c
            ticker = cik_to_ticker[c]
            comp_name = cik_to_name.get(c, "미국 상장 기업")
            break
        
    return ticker, comp_name, cik

def calculate_historical_pattern_match(form_type, market_data):
    if not market_data:
        return 30, "일반 공시 변동 패턴"
        
    matched_score = 0
    matched_patterns = []
    
    m_cap = market_data["market_cap"]
    float_sh = market_data["float_shares"]
    short_pct = market_data["short_pct"]
    borrow_pct = market_data["borrow_pct"]
    vol_ratio = market_data["vol_ratio"]
    
    p1 = HISTORICAL_SURGE_PATTERNS[0]
    if (0 < float_sh <= p1["max_float"]) and (short_pct >= p1["min_short"] or borrow_pct >= 50.0):
        matched_score += p1["weight"]
        matched_patterns.append("클래식 숏스퀴즈 화약고 패턴")
        
    p2 = HISTORICAL_SURGE_PATTERNS[1]
    if (0 < m_cap <= p2["max_market_cap"]) and (vol_ratio >= p2["min_vol_spike"]) and (-5.0 <= market_data.get("change_pct", 0) <= 15.0):
        matched_score += p2["weight"]
        matched_patterns.append("폭등 직전 바닥 매집 패턴")
        
    p3 = HISTORICAL_SURGE_PATTERNS[2]
    if market_data["chart_score"] >= p3["min_obv_score"] and any(f in form_type.upper() for f in p3["required_form"]):
        matched_score += p3["weight"]
        matched_patterns.append("내부자/세력 선취매 패턴")
        
    similarity_pct = min(99, max(30, matched_score + 25 if matched_score > 0 else 35))
    pattern_desc = ", ".join(matched_patterns) if matched_patterns else "일반 중소형주 공시 패턴"
    
    return similarity_pct, pattern_desc

def analyze_advanced_filing(title, form_type, market_data, sentiment_override=None):
    title_upper = title.upper()
    form_upper = form_type.upper()
    score = 50
    
    if market_data:
        m_cap = market_data["market_cap"]
        float_sh = market_data["float_shares"]
        short_pct = market_data["short_pct"]
        borrow_pct = market_data["borrow_pct"]
        score += market_data["chart_score"]
        
        if 0 < m_cap <= 150_000_000:
            score += 15
        if 0 < float_sh <= 5_000_000:
            score += 20
        elif 0 < float_sh <= 15_000_000:
            score += 10
        if short_pct >= 15.0 or borrow_pct >= 80.0:
            score += 20
        if market_data.get("is_vol_spike", False):
            score += 15

    if sentiment_override is False:
        return "🚨 [원문판독: 악재/희석/주의]", "하방 압력 및 물량 출회 주의", "⚠️ 추격 매수 금지 및 관망", 25, False

    if 'PRE-SURGE' in form_upper:
        score += 20
        return "🦈 [폭등 직전 바닥 이상수급 포착]", "+20% ~ +100%+ 슈팅 대기 구간", "🚀 호가창 체결강도 및 돌파 타점 노리기", score, True
    elif 'RW' in form_upper:
        score += 25
        return "🔥 [RW: 유상증자 전격 철회!]", "+30% ~ +120% 오버행 해소 슈팅", "🚀🚀 유증 취소 팩트! 바닥 즉시 공략", score, True
    elif form_upper == '4' or 'FORM 4' in form_upper:
        score += 15
        return "🔥 [내부자 지분 취득/매수]", "+15% ~ +50% 상방 압력", "🚀 바닥 지지 확인 후 매수 검토", score, True
    elif '13D' in form_upper or '13G' in form_upper:
        score += 25
        return "🔥 [세력/기관 5% 대량취득]", "+30% ~ +120% 폭등 잠재력", "🚀🚀 적극 매수 검토", score, True
    elif any(f in form_upper for f in ['S-1', 'S-3', '144', '424B']):
        return "🚨 [악재/물량희석·매각주의]", "하방 변동성 확대 주의", "⚠️ 진입 보류 및 관망", 20, False
    elif '8-K' in form_upper or '6-K' in form_upper:
        score += 15
        if sentiment_override is True or any(k in title_upper for k in ['MERGER', 'ACQUISITION', 'AGREEMENT', 'CONTRACT', 'PARTNERSHIP', 'FDA', 'PATENT', 'COMPLIANCE']):
            score += 20
            return "🔥 [8-K/6-K 폭등 촉매 포착]", "+30% ~ +150%+ 단기 슈팅 잠재력", "🚀🚀 아직 안 날아갔다면 즉시 타점 공략", score, True
        else:
            return "⚡ [8-K/6-K 수시 경영공시]", "±10% ~ ±40% 단기 급등락", "🎯 원문 2줄 요약 확인 후 대응", score, True
    else:
        return "ℹ️ [일반 주요 공시]", "단기 변동성 유의", "👀 원문 참고", score, None

def scan_pre_surge_candidates():
    global recent_ticker_alerts
    current_ts = time.time()
    try:
        url = "https://finviz.com/screener.ashx?v=111&f=exch_nasd,sh_float_u5,sh_price_u20,sh_relvol_o1.5&o=-volume"
        res = requests.get(url, headers=WEB_HEADERS, timeout=10)
        if res.status_code != 200:
            return

        tickers = re.findall(r'quote\.ashx\?t=([A-Z]{2,5})&', res.text)
        unique_tickers = []
        for t in tickers:
            if t not in unique_tickers and t in ticker_to_cik:
                unique_tickers.append(t)

        for tkr in unique_tickers[:6]:
            dedup_key = f"{tkr}_PRESURGE"
            if dedup_key in recent_ticker_alerts and (current_ts - recent_ticker_alerts[dedup_key] < 7200):
                continue

            m_data = get_market_data(tkr)
            if not m_data:
                continue

            chg = m_data.get("change_pct", 0.0)
            float_sh = m_data.get("float_shares", 0)
            if not (-4.0 <= chg <= 12.0):
                continue
            if float_sh <= 0 or float_sh > 5_000_000:
                continue
            if m_data.get("chart_score", 0) < 15:
                continue

            cik = ticker_to_cik.get(tkr)
            comp_name = cik_to_name.get(cik, tkr)
            dilution_status, switch_line, is_any_toxic_on = check_dilution_and_switches(cik, tkr, "")

            if is_any_toxic_on:
                continue

            grade, volatility, action_guide, score, _ = analyze_advanced_filing("PRE-SURGE ACCUMULATION", "PRE-SURGE", m_data, True)
            similarity_pct, matched_pattern_name = calculate_historical_pattern_match("PRE-SURGE", m_data)

            m_cap_str = f"${m_data['market_cap'] / 1_000_000:.1f}M"
            float_str = f"{float_sh / 1_000_000:.2f}M주"
            short_str = f"{m_data['short_pct']:.1f}%" if m_data['short_pct'] > 0 else "미집계"
            ctb_str = f"{m_data['borrow_pct']:.1f}%" if m_data['borrow_pct'] > 0 else "일반(낮음)"
            toss_web_link = f"https://tossinvest.com/stocks/{tkr}/order"
            finviz_link = f"https://finviz.com/quote.ashx?t={tkr}"

            msg = (
                f"<b>{grade}</b>\n\n"
                f"<b>📌 티커: {tkr} ({comp_name}) | 현재가: ${m_data['price']:.2f} ({chg:+.1f}%)</b>\n"
                f"<b>🔗 바로가기: <a href='{toss_web_link}'>[📲 토스증권 열기]</a> | <a href='{finviz_link}'>[📈 핀비즈 차트]</a></b>\n"
                f"<b>🚀🚀 [공시 전 바닥 매집 레이더 포착!]</b>\n"
                f"<b>🛡️ 독극물 쉴드: {dilution_status}</b>\n"
                f"<b>☠️ 희석 레이더: {switch_line}</b>\n"
                f"<b>📦 유통주식수: {float_str} 👉 [🔥초품절 매집구간]</b>\n"
                f"<b>📊 시가총액: {m_cap_str} | 공매도: {short_str} (CTB: {ctb_str})</b>\n"
                f"<b>{m_data['chart_status']}</b>\n"
                f"<b>🧠 패턴 유사도: {similarity_pct}% ({matched_pattern_name})</b>\n\n"
                f"<b>🤖 선제 발굴 팩트 브리핑:</b>\n"
                f"• 아직 주가가 급등하지 않은 바닥권({chg:+.1f}%)에서 평소 대비 {m_data['vol_ratio']:.1f}배 이상 이상 거래량과 OBV 매집이 포착되었습니다.\n"
                f"• 최근 공시 기준 ATM/TOXIC/ELOC 모두 OFF 상태인 깨끗한 품절주입니다.\n\n"
                f"<b>📈 예상 변동성:</b> {volatility}\n"
                f"<b>💡 대응 가이드:</b> {action_guide}"
            )
            send_telegram_msg(msg, is_loud=True)
            recent_ticker_alerts[dedup_key] = current_ts
            print(f"🦈 [폭등 전 바닥 매집주 선제 포착!] {tkr} | 등락률: {chg:+.1f}% | 유통주: {float_str}")
    except Exception:
        pass

def check_sec_api():
    global seen_filings, recent_ticker_alerts, is_first_run
    target_forms = ['8-K', '6-K', 'S-1', 'S-3', '424B', '4', 'SC 13D', 'SC 13G', '144', 'RW']
    try:
        url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&company=&dateb=&owner=include&count=40&output=atom"
        response = session.get(url, timeout=25)
        if response.status_code != 200:
            print(f"⚠️ [SEC 응답 지연] 상태 코드: {response.status_code}")
            return

        root = ET.fromstring(response.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        entries = root.findall('atom:entry', ns)
        
        now_str = datetime.now().strftime("%H:%M:%S")
        current_ts = time.time()

        if is_first_run:
            for entry in entries:
                filing_id = entry.find('atom:id', ns).text
                seen_filings.append(filing_id)
            is_first_run = False
            print(f"🛡️ [{now_str}] 기존 과거 공시 {len(entries)}개 스킵 완료! 폭등 전 발굴 레이더 가동 시작!")
            return

        new_cnt = 0

        for entry in entries:
            filing_id = entry.find('atom:id', ns).text
            if filing_id in seen_filings:
                continue
                
            new_cnt += 1
            title = entry.find('atom:title', ns).text
            link = entry.find('atom:link', ns).attrib['href']
            summary_el = entry.find('atom:summary', ns)
            summary_html = summary_el.text if summary_el is not None and summary_el.text else ""
            form_type = title.split(" - ")[0].strip() if " - " in title else "UNKNOWN"

            if any(tf.upper() == form_type.upper() or tf.upper() in form_type.upper() for tf in target_forms):
                ticker, comp_name, cik = parse_company_and_ticker(title)
                
                if ticker == "UNKNOWN":
                    seen_filings.append(filing_id)
                    continue

                dedup_key = f"{ticker}_{form_type}"
                if dedup_key in recent_ticker_alerts and (current_ts - recent_ticker_alerts[dedup_key] < 1800):
                    seen_filings.append(filing_id)
                    continue

                is_holding = ticker in MY_HOLDINGS
                print(f"🔎 [{now_str}] 정식 상장사 공시 포착! [{ticker}] ({form_type}) -> 팩트 및 희석 검증 중...")
                
                market_data = get_market_data(ticker, is_holding=is_holding)
                if not market_data:
                    seen_filings.append(filing_id)
                    continue

                float_sh = market_data.get('float_shares', 0)
                m_cap = market_data.get('market_cap', 0)

                ai_summary, sentiment_override, full_scanned_text = extract_real_filing_summary(form_type, link, summary_html)
                dilution_status, switch_line, is_any_toxic_on = check_dilution_and_switches(cik, ticker, full_scanned_text)
                
                grade, volatility, action_guide, score, is_bullish = analyze_advanced_filing(title, form_type, market_data, sentiment_override)
                similarity_pct, matched_pattern_name = calculate_historical_pattern_match(form_type, market_data)

                is_super_catalyst = (is_bullish is True or score >= 70) and not is_any_toxic_on
                max_mcap_allowed = 500_000_000 if is_super_catalyst else 250_000_000
                max_float_allowed = 30_000_000 if is_super_catalyst else 15_000_000

                if not is_holding:
                    if m_cap > max_mcap_allowed:
                        seen_filings.append(filing_id)
                        continue
                    if float_sh > max_float_allowed:
                        seen_filings.append(filing_id)
                        continue

                if not is_holding and score < 45 and not any(k in form_type.upper() for k in ['8-K', '6-K', '13D', 'RW']):
                    seen_filings.append(filing_id)
                    continue

                star_count = min(5, max(1, score // 20))
                stars = "🌟" * star_count

                if float_sh == 0:
                    float_tag = "미집계(신규상장 등)"
                elif float_sh <= 3_000_000:
                    float_tag = "🔥초품절 (매우 적음)"
                elif float_sh <= 10_000_000:
                    float_tag = "🎯적음 (슈팅 양호)"
                elif float_sh <= 20_000_000:
                    float_tag = "📊보통 (무난함)"
                else:
                    float_tag = "⚠️많음 (무거움)"

                if is_holding:
                    if is_bullish is False:
                        grade = "🚨🚨 [보유종목 악재/위험 경보] 🚨🚨"
                        rec_title = "⚠️ [악재 발생!] 즉시 리스크 점검 필수"
                    else:
                        grade = "🚀🚀 [보유종목 공시 경보] 🚀🚀"
                        rec_title = f"🔥 [보유종목 이벤트!] 내용 즉시 확인 {stars}"
                else:
                    if is_bullish is False:
                        rec_title = "⚠️ [원문 악재/희석 감지] 진입 보류"
                    elif 0 < float_sh <= 3_000_000 and (0 < m_cap <= 100_000_000) and not is_any_toxic_on:
                        rec_title = f"🚀🚀 [SS급 폭등전 초품절주 포착] 야수모드 ON {stars}"
                    elif 0 < float_sh <= 10_000_000 and not is_any_toxic_on:
                        rec_title = f"🎯 [A급 유통물량 적음 + 클린] 타점 검토 {stars}"
                    else:
                        rec_title = f"📢 [신규 공시 레이더 포착] 수급 체크 {stars}"

                m_cap_str = f"${m_cap / 1_000_000:.1f}M" if m_cap > 0 else "미집계"
                float_str = f"{float_sh / 1_000_000:.2f}M주" if float_sh > 0 else "미집계"
                short_str = f"{market_data['short_pct']:.1f}%" if market_data['short_pct'] > 0 else "미집계"
                
                borrow_val = market_data['borrow_pct']
                ctb_str = f"{borrow_val:.1f}%" if borrow_val > 0 else "일반(낮음)"
                
                news_headline = market_data.get('latest_news', '특이 뉴스 없음')
                kr_news_headline = news_headline
                if translator and news_headline not in ['특이 뉴스 없음', '최신 뉴스 없음', '확인불가']:
                    try:
                        kr_news_headline = translator.translate(news_headline)
                    except Exception:
                        pass 

                is_key_news = market_data.get('is_key_news', False)
                chart_info = market_data.get('chart_status', '데이터 없음')
                
                toss_web_link = f"https://tossinvest.com/stocks/{ticker}/order"
                finviz_link = f"https://finviz.com/quote.ashx?t={ticker}"

                if is_key_news:
                    news_line = f"<b>📰 핵심 호재 뉴스: {kr_news_headline}</b>\n(원문: {news_headline})"
                else:
                    news_line = f"<b>📰 최신 뉴스: {kr_news_headline}</b>"

                msg = (
                    f"<b>{grade}</b>\n\n"
                    f"<b>📌 티커: {ticker} ({comp_name}) | 현재가: ${market_data['price']:.2f} ({market_data.get('change_pct', 0):+.1f}%)</b>\n"
                    f"<b>🔗 바로가기: <a href='{toss_web_link}'>[📲 토스증권 열기]</a> | <a href='{finviz_link}'>[📈 핀비즈 차트]</a></b>\n"
                    f"<b>{rec_title}</b>\n"
                    f"<b>🛡️ 독극물 쉴드: {dilution_status}</b>\n"
                    f"<b>☠️ 희석 레이더: {switch_line}</b>\n"
                    f"<b>📦 유통주식수: {float_str} 👉 [{float_tag}]</b>\n"
                    f"<b>📊 시가총액: {m_cap_str} | 공매도: {short_str} (CTB: {ctb_str})</b>\n"
                    f"{news_line}\n"
                    f"<b>{chart_info}</b>\n"
                    f"<b>🧠 패턴 유사도: {similarity_pct}% ({matched_pattern_name})</b>\n"
                    f"<b>📄 공시 서식:</b> {form_type}\n\n"
                    f"<b>🤖 AI 공시 원문 딥스캔 요약:</b>\n"
                    f"{ai_summary}\n\n"
                    f"<b>📈 예상 변동성:</b> {volatility}\n"
                    f"<b>💡 대응 가이드:</b> {action_guide}\n\n"
                    f"🔗 <a href='{link}'>SEC 원문 공시 바로보기</a>"
                )
                
                is_loud_alert = True if is_holding or (is_bullish is not False and similarity_pct >= 60) else False
                send_telegram_msg(msg, is_loud=is_loud_alert)
                recent_ticker_alerts[dedup_key] = current_ts
                print(f"🎉 [텔레그램 전송 완료!] {ticker} ({form_type}) | 시총: {m_cap_str} | CTB: {ctb_str}")

            seen_filings.append(filing_id)

        if new_cnt == 0:
            print(f"👀 [{now_str}] 레이더 정상 감시 중... (새로운 공시 대기 중)")

        if len(recent_ticker_alerts) > 500:
            recent_ticker_alerts.clear()

    except Exception as e:
        print(f"[안정 모드] 일시적 통신 지연 (다음 주기에 자동 재조회): {e}")

def start_radar():
    global loop_counter
    try:
        print("🚀 마이크로캡 폭등 전 선제 발굴 레이더 (Pre-Surge 패치 버전) 가동 시작...")
        load_sec_ticker_map()
        send_telegram_msg("🚀 [폭등스캐너가동]", is_loud=True)
        while True:
            check_sec_api()
            loop_counter += 1
            if loop_counter % 45 == 0:
                scan_pre_surge_candidates()
            time.sleep(20)
    except Exception as e:
        print(f"❌ 치명적 에러 발생: {e}")
        input("프로그램이 멈췄습니다. 에러를 확인하려면 엔터 키를 누르세요...")

start_radar()
