#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import streamlit as st
import requests

# =====================================================================
# 1. OKX API'DEN CANLI VERİ ÇEKME FONKSİYONU
# =====================================================================
def fetch_okx_data(symbol="BTC-USDT"):
    # Kullanıcı "CLUSDT" veya "BTC-USDT-SWAP" yazsa bile otomatik "BTC-USDT" formatına çevirir
    clean_sym = symbol.upper().strip().replace("-SWAP", "")
    if "-" not in clean_sym and clean_sym.endswith("USDT"):
        clean_sym = clean_sym[:-4] + "-USDT"

    swap_id = f"{clean_sym}-SWAP"

    # 1. Vadeli (Perpetual) Fiyatı Çek
    ticker_url = f"https://www.okx.com/api/v5/market/ticker?instId={swap_id}"
    ticker_res = requests.get(ticker_url, timeout=5).json()
    if not ticker_res.get("data"):
        raise ValueError("Parite bulunamadı.")
    perp_price = float(ticker_res["data"][0]["last"])

    # 2. Spot Index Fiyatını Çek (TradFi paritelerinde boş dönerse perp_price kullan)
    index_url = f"https://www.okx.com/api/v5/market/index-tickers?instId={clean_sym}"
    index_res = requests.get(index_url, timeout=5).json()
    if index_res.get("data") and index_res["data"][0].get("idxPx"):
        index_price = float(index_res["data"][0]["idxPx"])
    else:
        index_price = perp_price

    # 3. Resmi OKX Fonlama Oranını ve Alt/Üst Sınırları Çek
    funding_url = f"https://www.okx.com/api/v5/public/funding-rate?instId={swap_id}"
    funding_res = requests.get(funding_url, timeout=5).json()
    funding_data = funding_res["data"][0]

    funding_rate = float(funding_data["fundingRate"]) * 100  # Yüzde (%) cinsinden
    max_f = float(funding_data.get("maxFundingRate", 0)) * 100
    min_f = float(funding_data.get("minFundingRate", 0)) * 100

    return clean_sym, perp_price, index_price, funding_rate, min_f, max_f

# =====================================================================
# 2. HESAPLAMA FONKSİYONU (DOĞRUDAN FONLAMA + KLASİK FORMÜL DESTEKLİ)
# =====================================================================
def calculate(m, l, r, c1, c2, p, ip, I, d_cap=0.05, side="long", funding_intervals=1, direct_f=None):
    """
    direct_f dolu gönderilirse (OKX Modu) p, ip, I, d_cap formülünü atlar ve
    doğrudan resmi fonlama oranını (f) kullanır.
    """
    r_, c1_, c2_ = r / 100, c1 / 100, c2 / 100
    I_, cap = I / 100, d_cap / 100

    # Pozisyon büyüklükleri
    s1 = m * l
    s2 = s1 * (1 + r_)

    # Komisyonlar
    C1 = s1 * c1_
    C2 = s2 * c2_
    t = C1 + C2

    # Premium Index ve Fonlama Oranı (f)
    pi = (p - ip) / ip if ip > 0 else 0.0
    d = I_ - pi

    if direct_f is not None:
        f = direct_f / 100.0  # Doğrudan OKX resmi fonlama oranı
    else:
        f = pi + max(-cap, min(cap, d))  # Klasik Borsa Formülü: f = pi + clamp(I - pi, -cap, +cap)

    # Fonlama Ücreti (F > 0 ise Long öder/Short alır; F < 0 ise Short öder/Long alır)
    F = s1 * f * funding_intervals

    # Brüt ve Net Kâr/Zarar (P/L)
    if side == "long":
        gross = s2 - s1
        n = gross - (t + F)
    else:
        gross = s1 - s2
        n = gross - (t - F)

    return {
        "Opening size s1": s1,
        "Closing size s2": s2,
        "Initial commission C1": C1,
        "Last commission C2": C2,
        "Total commission / trading fee t": t,
        "Premium index (%)": pi * 100,
        "Funding rate f (%)": f * 100,
        "Funding fee F (long pays +)": F,
        "Gross P/L": gross,
        "Net P/L": n,
        "ROI on margin (%)": n / m * 100,
    }

# =====================================================================
# 3. STREAMLIT WEB ARAYÜZÜ
# =====================================================================
st.set_page_config(page_title="OKX Futures PnL Bot", page_icon="⚡", layout="centered")

st.title("⚡ OKX Canlı Vadeli İşlemler Botu")
st.caption("OKX resmi fonlama oranı (f) ve canlı fiyat entegreli net kâr hesaplayıcı.")

# Başlangıç Session State Değerleri
if "p_input" not in st.session_state:
    st.session_state.p_input = 97.51
    st.session_state.ip_input = 97.51
    st.session_state.f_input = -0.01757
    st.session_state.giris_input = 97.51
    st.session_state.tp_input = 95.85
    st.session_state.cap_info = "-%1.00 / +%1.00"

# --- YAN PANEL: OKX CANLI VERİ ÇEKİCİ ---
st.sidebar.header("🌐 OKX Canlı Veri Bağlantısı")
secilen_parite = st.sidebar.text_input("Parite Kodu (Örn: BTC-USDT, CL-USDT, ETH-USDT)", value="CL-USDT")

if st.sidebar.button("🔄 OKX'ten Canlı Verileri Çek", use_container_width=True):
    try:
        sym, p_canli, ip_canli, f_canli, min_f, max_f = fetch_okx_data(secilen_parite)
        st.session_state.p_input = p_canli
        st.session_state.ip_input = ip_canli
        st.session_state.f_input = f_canli
        st.session_state.giris_input = p_canli
        st.session_state.tp_input = round(p_canli * 1.0111, 4)
        st.session_state.cap_info = f"%{min_f:.2f} / +%{max_f:.2f}"
        st.sidebar.success(f"✅ {sym} güncellendi! Resmi f: %{f_canli:+.5f}")
    except Exception:
        st.sidebar.error("Parite bulunamadı. Lütfen 'BTC-USDT' veya 'CL-USDT' formatında yazın.")

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Pozisyon Parametreleri")

side = st.sidebar.selectbox("Pozisyon Yönü (Side)", ["long", "short"], index=1)
m = st.sidebar.number_input("Margin (m) [USDT]", min_value=1.0, value=121.45, step=10.0)
l = st.sidebar.slider("Leverage (l)", min_value=1.0, max_value=125.0, value=10.0, step=1.0)

r_modu = st.sidebar.radio("Fiyat Değişimi (r) Giriş Yöntemi", ["Giriş ve TP Fiyatını Gir", "Doğrudan Yüzde (%) Gir"])

if r_modu == "Doğrudan Yüzde (%) Gir":
    r = st.sidebar.number_input("Price Change r (%) [Yükseliş: +, Düşüş: -]", value=-1.7024, step=0.1, format="%.4f")
else:
    giris_fiyati = st.sidebar.number_input("Giriş Fiyatı", key="giris_input", format="%.4f")
    tp_fiyati = st.sidebar.number_input("Hedef (TP / SL) Fiyatı", key="tp_input", format="%.4f")
    r = ((tp_fiyati - giris_fiyati) / giris_fiyati) * 100 if giris_fiyati > 0 else 0.0
    st.sidebar.info(f"Hesaplanan Fiyat Değişimi (r): **%{r:+.4f}**")

st.sidebar.markdown("---")
st.sidebar.subheader("Komisyon Oranları (%)")
col_c1, col_c2 = st.sidebar.columns(2)
with col_c1:
    c1_type = st.selectbox("Açılış Emri", ["Taker (%0.05)", "Maker (%0.02)", "Özel"])
    c1 = 0.02 if c1_type == "Maker (%0.02)" else (0.05 if c1_type == "Taker (%0.05)" else st.number_input("Açılış (%)", value=0.04, format="%.3f"))
with col_c2:
    c2_type = st.selectbox("Kapanış Emri", ["Taker (%0.05)", "Maker (%0.02)", "Özel"])
    c2 = 0.02 if c2_type == "Maker (%0.02)" else (0.05 if c2_type == "Taker (%0.05)" else st.number_input("Kapanış (%)", value=0.04, format="%.3f"))

st.sidebar.markdown("---")
st.sidebar.subheader("Fonlama (Funding) Modu")

f_modu = st.sidebar.radio(
    "Fonlama Hesaplama Yöntemi",
    ["Doğrudan Resmi Oran (OKX Modu)", "Klasik Formül (p, iₚ, I, d ile)"]
)

k = st.sidebar.number_input("Fonlama Periyot Sayısı (Intervals Held)", min_value=0, max_value=50, value=1, step=1)

if f_modu == "Doğrudan Resmi Oran (OKX Modu)":
    direct_f_val = st.sidebar.number_input("OKX Fonlama Oranı f (%)", key="f_input", step=0.005, format="%.5f")
    st.sidebar.caption(f"📌 Parite Fonlama Sınırı (Cap/Floor): **{st.session_state.cap_info}**")
    p = st.session_state.p_input
    ip = st.session_state.ip_input
    I, d_cap = 0.01, 0.05
else:
    direct_f_val = None
    p = st.sidebar.number_input("Perpetual Price (p) [USDT]", key="p_input", format="%.4f")
    ip = st.sidebar.number_input("Index Price (iₚ) [USDT]", key="ip_input", format="%.4f")
    I = st.sidebar.number_input("Interest Rate I (%)", value=0.01, step=0.005, format="%.4f")
    d_cap = st.sidebar.number_input("Dampener Cap (%)", value=0.05, step=0.01, format="%.3f")

# --- HESAPLAMA MOTORUNU ÇALIŞTIRMA ---
res = calculate(
    m=m, l=l, r=r, c1=c1, c2=c2, p=p, ip=ip, I=I, d_cap=d_cap,
    side=side, funding_intervals=k, direct_f=direct_f_val
)

# --- ANA EKRAN SONUÇ KARTLARI ---
net_pnl = res["Net P/L"]
roi = res["ROI on margin (%)"]
pnl_color = "#16a34a" if net_pnl >= 0 else "#dc2626"

# Fonlama yönünü kullanıcıya net gösterme (Kim ödüyor, kim alıyor?)
f_oran = res["Funding rate f (%)"]
f_tutar = res["Funding fee F (long pays +)"]
if k == 0 or f_oran == 0:
    f_durum = "Fonlama Kesintisi Yok"
elif (side == "long" and f_oran > 0) or (side == "short" and f_oran < 0):
    f_durum = f"Sen Ödüyorsun (-{abs(f_tutar):.4f} USDT)"
else:
    f_durum = f"Sen Alıyorsun (+{abs(f_tutar):.4f} USDT)"

st.markdown(f"""
<div style="background-color: #0f172a; padding: 22px; border-radius: 12px; text-align: center; border: 1px solid #334155; margin-bottom: 20px;">
    <span style="color: #94a3b8; font-size: 14px; text-transform: uppercase; letter-spacing: 1px;">Cebe Kalan Net Kazanç (Net P/L)</span>
    <h1 style="color: {pnl_color}; margin: 8px 0; font-size: 40px;">{net_pnl:+,.2f} USDT</h1>
    <span style="color: #e2e8f0; font-size: 16px;">Marjin Getirisi (ROE): <b>%{roi:+,.2f}</b> | İşlem Sonu Bakiye: <b>{m + net_pnl:,.2f} USDT</b></span>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    st.metric(label="Açılış Hacmi (s₁)", value=f"{res['Opening size s1']:,.2f} USDT")
    st.metric(label="Toplam Komisyon (t)", value=f"{res['Total commission / trading fee t']:,.4f} USDT", 
              delta=f"C₁: {res['Initial commission C1']:.2f} | C₂: {res['Last commission C2']:.2f}", delta_color="inverse")
    st.metric(label="Brüt Kâr/Zarar (Gross)", value=f"{res['Gross P/L']:+,.2f} USDT")

with col2:
    st.metric(label="Kapanış Hacmi (s₂)", value=f"{res['Closing size s2']:,.2f} USDT")
    st.metric(label="Fonlama Etkisi (F)", value=f"{abs(f_tutar):,.4f} USDT", 
              delta=f"f: %{f_oran:+.5f} → {f_durum}", delta_color="off")
    st.metric(label="Hesaplanan Değişim (r)", value=f"%{r:+.4f}")

with st.expander("📋 Tüm Hesaplama Çıktıları (Detaylı Tablo)"):
    st.table({k_name: [f"{v_val:,.6f}"] for k_name, v_val in res.items()})

