import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta

# --- KONFIGURATION ---
SYMBOL = "bitcoin"          # Vilken krypto du vill handla
VS_CURRENCY = "usd"         # Mot vilken valuta
SHORT_MA = 10               # Korta glidande medelvärdet (dagar)
LONG_MA = 30                # Långa glidande medelvärdet (dagar)
INITIAL_CAPITAL = 10000     # Startkapital i USD

# --- 1. HÄMTA HISTORISK DATA (UTAN NYCKEL) ---
def fetch_historical_data(days=90):
    """
    Hämtar historisk 'close'-prisdata för de senaste X dagarna.
    Använder CoinGecks Keyless Public API - ingen nyckel krävs!
    """
    url = f"https://api.coingecko.com/api/v3/coins/{SYMBOL}/market_chart"
    params = {
        "vs_currency": VS_CURRENCY,
        "days": days,
        "interval": "daily"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        prices = data['prices']
        df = pd.DataFrame(prices, columns=['timestamp', 'price'])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('date', inplace=True)
        
        print(f"✅ Hämtade {len(df)} dagar av historisk data för {SYMBOL}.")
        return df
    except Exception as e:
        print(f"❌ Fel vid hämtning av data: {e}")
        return None

# --- 2. BERÄKNA GLIDANDE MEDELVÄRDEN OCH SIGNALER ---
def calculate_signals(df):
    """
    Beräknar korta och långa glidande medelvärden samt genererar köp/sälj-signaler.
    """
    df = df.copy()
    
    df['short_ma'] = df['price'].rolling(window=SHORT_MA).mean()
    df['long_ma'] = df['price'].rolling(window=LONG_MA).mean()
    
    df['signal'] = 0
    df.loc[df['short_ma'] > df['long_ma'], 'signal'] = 1
    df.loc[df['short_ma'] < df['long_ma'], 'signal'] = -1
    
    df['position'] = df['signal'].diff()
    
    df['buy_signal'] = (df['position'] == 2)
    df['sell_signal'] = (df['position'] == -2)
    
    return df

# --- 3. SIMULERA HANDEL (PAPPERSHANDEL) ---
def run_simulation(df):
    """
    Simulerar köp och sälj baserat på signalerna.
    Håller reda på portföljens värde i USD och antal mynt.
    """
    df = df.dropna(subset=['short_ma', 'long_ma']).copy()
    
    cash = INITIAL_CAPITAL
    holdings = 0.0
    portfolio_value = []
    trades = []
    
    print(f"\n🚀 Startar simulering med {INITIAL_CAPITAL} {VS_CURRENCY.upper()}")
    print("-" * 60)
    
    for index, row in df.iterrows():
        current_price = row['price']
        
        if row['buy_signal']:
            if cash > 0:
                buy_amount = cash / current_price
                holdings += buy_amount
                cash = 0
                trades.append({
                    'date': index,
                    'type': 'KÖP',
                    'price': current_price,
                    'amount': buy_amount,
                    'value': buy_amount * current_price
                })
                print(f"🟢 KÖP  {index.strftime('%Y-%m-%d')} | Pris: ${current_price:,.2f} | Köpte: {buy_amount:.6f} mynt")
        
        elif row['sell_signal']:
            if holdings > 0:
                sell_value = holdings * current_price
                cash += sell_value
                trades.append({
                    'date': index,
                    'type': 'SÄLJ',
                    'price': current_price,
                    'amount': holdings,
                    'value': sell_value
                })
                print(f"🔴 SÄLJ {index.strftime('%Y-%m-%d')} | Pris: ${current_price:,.2f} | Sålde: {holdings:.6f} mynt | Fick: ${sell_value:,.2f}")
                holdings = 0.0
        
        total_value = cash + (holdings * current_price)
        portfolio_value.append({
            'date': index,
            'total_value': total_value,
            'cash': cash,
            'holdings': holdings,
            'price': current_price
        })
    
    portfolio_df = pd.DataFrame(portfolio_value)
    portfolio_df.set_index('date', inplace=True)
    
    return portfolio_df, trades

# --- 4. PRESENTERA RESULTAT ---
def print_results(portfolio_df, trades):
    """
    Skriver ut en sammanfattning av simuleringen.
    """
    print("\n" + "=" * 60)
    print("📊 SIMULERINGSLUTRESULTAT")
    print("=" * 60)
    
    start_value = INITIAL_CAPITAL
    end_value = portfolio_df['total_value'].iloc[-1]
    total_return = ((end_value - start_value) / start_value) * 100
    
    print(f"Startkapital: ${start_value:,.2f}")
    print(f"Slutvärde:    ${end_value:,.2f}")
    print(f"Total avkastning: {total_return:+.2f}%")
    print(f"Antal affärer: {len(trades)}")
    
    if trades:
        print("\n📝 De 5 senaste affärerna:")
        for trade in trades[-5:]:
            print(f"  {trade['date'].strftime('%Y-%m-%d')} - {trade['type']} {trade['amount']:.6f} st @ ${trade['price']:,.2f}")
    
    portfolio_df.to_csv("simuleringsresultat.csv")
    print(f"\n💾 Portföljutvecklingen sparades som 'simuleringsresultat.csv'")

# --- HUVUDPROGRAM ---
if __name__ == "__main__":
    print("🔄 Hämtar data från CoinGecko Keyless API...")
    df = fetch_historical_data(days=90)
    
    if df is not None:
        print("📈 Beräknar signaler...")
        df_with_signals = calculate_signals(df)
        
        print("💹 Kör simulering...")
        portfolio_df, trades = run_simulation(df_with_signals)
        
        print_results(portfolio_df, trades)
    else:
        print("❌ Kunde inte hämta data. Avslutar.")