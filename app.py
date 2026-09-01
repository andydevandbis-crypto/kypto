from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import requests
import pandas as pd
import time
import threading
from datetime import datetime, timedelta
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Globala variabler
simulation_data = {
    'is_running': False,
    'data': {},
    'current_index': 0,
    'portfolios': {},
    'trades': {},
    'total_value': 10000,
    'thread': None
}

# Endast 3 valutor för att undvika rate limiting
CRYPTO_LIST = [
    {'id': 'bitcoin', 'name': 'Bitcoin', 'symbol': 'BTC'},
    {'id': 'ethereum', 'name': 'Ethereum', 'symbol': 'ETH'},
    {'id': 'solana', 'name': 'Solana', 'symbol': 'SOL'}
]

def fetch_crypto_data_with_retry(symbol, days=90, max_retries=3):
    """Hämtar data med retry-funktion"""
    for attempt in range(max_retries):
        try:
            # Använder market_chart för att få daglig data
            url = f"https://api.coingecko.com/api/v3/coins/{symbol}/market_chart"
            params = {
                "vs_currency": "usd",
                "days": days,
                "interval": "daily"
            }
            
            print(f"📡 Hämtar data för {symbol} (försök {attempt+1}/{max_retries})...")
            response = requests.get(url, params=params, timeout=15)
            
            if response.status_code == 429:
                wait_time = (attempt + 1) * 5
                print(f"⚠️ Rate limit! Väntar {wait_time} sekunder...")
                time.sleep(wait_time)
                continue
                
            response.raise_for_status()
            data = response.json()
            
            if data and 'prices' in data and len(data['prices']) > 0:
                prices = data['prices']
                df = pd.DataFrame(prices, columns=['timestamp', 'price'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                print(f"✅ {symbol}: {len(df)} dagar med data")
                return df
            else:
                print(f"⚠️ {symbol}: Ingen data")
                return None
                
        except requests.exceptions.Timeout:
            print(f"⏱️ Timeout för {symbol}, försöker igen...")
            time.sleep(3)
        except Exception as e:
            print(f"❌ {symbol}: {e}")
            time.sleep(3)
    
    print(f"❌ {symbol}: Misslyckades efter {max_retries} försök")
    return None

def fetch_all_crypto_data(days=90):
    """Hämtar data för alla kryptovalutor"""
    all_data = {}
    
    for crypto in CRYPTO_LIST:
        symbol = crypto['id']
        df = fetch_crypto_data_with_retry(symbol, days)
        if df is not None:
            all_data[symbol] = df
        # Vänta mellan anrop
        time.sleep(3)
    
    return all_data

def calculate_rsi(price_history, period=14):
    """Beräknar RSI"""
    if len(price_history) < period + 1:
        return 50
    
    deltas = [price_history[i] - price_history[i-1] for i in range(1, len(price_history))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 1
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def generate_smart_signal(price_history):
    """Smart signal - anpassar sig efter marknaden"""
    if len(price_history) < 20:
        return 'HOLD', 0, {}
    
    # Beräkna olika indikatorer
    current_price = price_history[-1]
    ma10 = sum(price_history[-10:]) / 10
    ma20 = sum(price_history[-20:]) / 20
    
    # Prisavvikelse från MA20
    deviation = ((current_price - ma20) / ma20) * 100
    
    # RSI
    rsi = calculate_rsi(price_history)
    
    # Trendstyrka (sista 5 dagarna)
    trend = ((price_history[-1] - price_history[-5]) / price_history[-5]) * 100 if len(price_history) >= 5 else 0
    
    debug = {
        'rsi': round(rsi, 2),
        'deviation': round(deviation, 2),
        'trend': round(trend, 2),
        'ma10': round(ma10, 2),
        'ma20': round(ma20, 2),
        'price': round(current_price, 2)
    }
    
    # SMART STRATEGI - anpassar sig efter trenden
    buy_signals = 0
    sell_signals = 0
    
    # 1. RSI - köp vid översålt, sälj vid överköpt
    if rsi < 30:  # Starkt översålt
        buy_signals += 3
    elif rsi < 40:  # Lätt översålt
        buy_signals += 1.5
    elif rsi > 70:  # Starkt överköpt
        sell_signals += 3
    elif rsi > 60:  # Lätt överköpt
        sell_signals += 1.5
    
    # 2. Prisavvikelse från MA20
    if deviation < -5:  # Mycket under MA20
        buy_signals += 2
    elif deviation < -2:  # Lite under MA20
        buy_signals += 1
    elif deviation > 5:  # Mycket över MA20
        sell_signals += 2
    elif deviation > 2:  # Lite över MA20
        sell_signals += 1
    
    # 3. Trend - bekräftelse
    if trend > 0 and buy_signals > 0:  # Uppåtgående trend + köpsignal
        buy_signals += 0.5
    elif trend < 0 and sell_signals > 0:  # Nedåtgående trend + säljsignal
        sell_signals += 0.5
    
    # Beslut
    confidence = max(buy_signals, sell_signals)
    
    if buy_signals > sell_signals and confidence >= 2.0:
        signal_type = 'BUY'
    elif sell_signals > buy_signals and confidence >= 2.0:
        signal_type = 'SELL'
    else:
        signal_type = 'HOLD'
    
    return signal_type, confidence, debug

def run_multi_simulation():
    """Kör simuleringen med smart strategi"""
    global simulation_data
    
    print("🚀 Startar SMART multi-krypto simulering...")
    print("=" * 60)
    
    all_data = simulation_data['data']
    if not all_data:
        print("❌ Ingen data tillgänglig")
        return
    
    # Initiera portföljer
    initial_per_coin = 10000 / len(all_data)
    portfolios = {}
    price_histories = {}
    
    for symbol, df in all_data.items():
        portfolios[symbol] = {
            'cash': initial_per_coin,
            'holdings': 0,
            'total_value': initial_per_coin,
            'trades': [],
            'initial_price': float(df.iloc[0]['price']),
            'entry_price': None,
            'last_action': 'HOLD'
        }
        price_histories[symbol] = []
    
    max_length = max([len(df) for df in all_data.values()])
    print(f"📊 Simulerar {max_length} dagar över {len(all_data)} valutor")
    print("=" * 60)
    
    total_trades_all = 0
    
    for i in range(max_length):
        if not simulation_data['is_running']:
            print("⏹ Simulering stoppad")
            break
        
        total_value_all = 0
        updates = {}
        
        for symbol, df in all_data.items():
            if i >= len(df):
                continue
                
            row = df.iloc[i]
            current_price = float(row['price'])
            timestamp = row.name.strftime('%Y-%m-%d')
            
            # Uppdatera prishistorik
            price_histories[symbol].append(current_price)
            if len(price_histories[symbol]) > 30:
                price_histories[symbol].pop(0)
            
            # Generera signal
            signal, confidence, debug = generate_smart_signal(price_histories[symbol])
            
            portfolio = portfolios[symbol]
            trade = None
            crypto_name = next(c['name'] for c in CRYPTO_LIST if c['id'] == symbol)
            
            # --- TAKE PROFIT / STOP LOSS ---
            if portfolio['holdings'] > 0 and portfolio['entry_price'] is not None:
                profit_percent = ((current_price - portfolio['entry_price']) / portfolio['entry_price']) * 100
                
                # Take Profit: Sälj vid 15% vinst
                if profit_percent >= 15:
                    signal = 'SELL'
                    confidence = 3.0
                    print(f"💰 {crypto_name} Take Profit! +{profit_percent:.1f}%")
                
                # Stop Loss: Sälj vid 8% förlust
                elif profit_percent <= -8:
                    signal = 'SELL'
                    confidence = 3.0
                    print(f"🛑 {crypto_name} Stop Loss! {profit_percent:.1f}%")
            
            # Logga signaler (var 10:e dag)
            if i % 10 == 0:
                print(f"📊 {crypto_name} dag {i}: RSI={debug.get('rsi', 'N/A')}, Signal={signal}, Conf={confidence:.1f}")
            
            # Utför trade
            if signal == 'BUY' and confidence >= 2.0 and portfolio['cash'] > 0:
                buy_amount = portfolio['cash'] / current_price * 0.95  # Använd 95% av kapitalet
                portfolio['holdings'] += buy_amount
                portfolio['cash'] -= buy_amount * current_price
                portfolio['entry_price'] = current_price
                trade = {
                    'symbol': symbol,
                    'type': 'KÖP',
                    'price': current_price,
                    'amount': buy_amount,
                    'value': buy_amount * current_price,
                    'timestamp': timestamp,
                    'confidence': confidence,
                    'debug': debug
                }
                portfolio['trades'].append(trade)
                total_trades_all += 1
                print(f"🟢 {crypto_name} KÖP @ ${current_price:.2f} (Conf: {confidence:.1f}, RSI: {debug.get('rsi', 0):.1f})")
                
            elif signal == 'SELL' and confidence >= 2.0 and portfolio['holdings'] > 0:
                sell_value = portfolio['holdings'] * current_price
                portfolio['cash'] += sell_value
                trade = {
                    'symbol': symbol,
                    'type': 'SÄLJ',
                    'price': current_price,
                    'amount': portfolio['holdings'],
                    'value': sell_value,
                    'timestamp': timestamp,
                    'confidence': confidence,
                    'debug': debug
                }
                portfolio['trades'].append(trade)
                portfolio['holdings'] = 0
                portfolio['entry_price'] = None
                total_trades_all += 1
                print(f"🔴 {crypto_name} SÄLJ @ ${current_price:.2f} (Conf: {confidence:.1f}, RSI: {debug.get('rsi', 0):.1f})")
            
            # Beräkna totalt värde
            total_value = portfolio['cash'] + (portfolio['holdings'] * current_price)
            portfolio['total_value'] = total_value
            total_value_all += total_value
            
            # Spara uppdatering
            updates[symbol] = {
                'price': current_price,
                'signal': signal,
                'confidence': confidence,
                'portfolio': portfolio,
                'trade': trade,
                'timestamp': timestamp,
                'debug': debug
            }
        
        # Uppdatera totalt värde
        simulation_data['total_value'] = total_value_all
        progress = (i + 1) / max_length * 100
        
        # Skicka uppdatering (var 5:e dag)
        if i % 5 == 0:
            try:
                socketio.emit('multi_price_update', {
                    'updates': updates,
                    'total_value': total_value_all,
                    'progress': progress,
                    'day': i + 1,
                    'total_days': max_length
                })
            except Exception as e:
                print(f"⚠️ Kunde inte skicka data: {e}")
        
        time.sleep(0.05)  # Snabbare simulering
    
    # Sammanfatta resultat
    print("\n" + "=" * 60)
    print("📊 SIMULERING KLAR!")
    print("=" * 60)
    
    total_final = 0
    total_trades = 0
    
    for symbol, portfolio in portfolios.items():
        final_value = portfolio['total_value']
        total_final += final_value
        trades_count = len(portfolio['trades'])
        total_trades += trades_count
        crypto_name = next(c['name'] for c in CRYPTO_LIST if c['id'] == symbol)
        initial_price = portfolio['initial_price']
        last_price = float(all_data[symbol].iloc[-1]['price'])
        price_change = ((last_price - initial_price) / initial_price) * 100
        
        print(f"{crypto_name:10} | Start: ${initial_price:.2f} | Slut: ${last_price:.2f} | Ändring: {price_change:+.1f}% | Portfölj: ${final_value:.2f} | Trades: {trades_count}")
    
    print("-" * 60)
    print(f"💰 TOTALT SLUTVÄRDE: ${total_final:.2f}")
    print(f"📈 TOTAL AVKASTNING: {((total_final - 10000) / 10000 * 100):.2f}%")
    print(f"📊 TOTALA TRADES: {total_trades}")
    print("=" * 60)
    
    try:
        socketio.emit('simulation_complete', {
            'message': 'Multi-krypto simulering klar!',
            'total_value': total_final,
            'portfolios': {symbol: p['total_value'] for symbol, p in portfolios.items()},
            'trades': {symbol: len(p['trades']) for symbol, p in portfolios.items()},
            'total_trades': total_trades
        })
    except Exception as e:
        print(f"⚠️ Kunde inte skicka slutmeddelande: {e}")
    
    simulation_data['is_running'] = False

@app.route('/')
def index():
    return render_template('multi_simulation.html')

@app.route('/api/start_simulation', methods=['POST'])
def start_simulation():
    """Startar multi-krypto simuleringen"""
    global simulation_data
    
    print("🔄 Startar SMART multi-krypto simulering...")
    
    # Hämta data för 90 dagar
    all_data = fetch_all_crypto_data(days=90)
    
    if not all_data:
        return jsonify({'error': 'Kunde inte hämta data - försök igen'}), 400
    
    # Återställ simulation_data
    simulation_data['is_running'] = True
    simulation_data['data'] = all_data
    simulation_data['current_index'] = 0
    simulation_data['total_value'] = 10000
    simulation_data['portfolios'] = {}
    simulation_data['trades'] = {}
    
    # Starta simulering i separat tråd
    simulation_data['thread'] = threading.Thread(target=run_multi_simulation, daemon=True)
    simulation_data['thread'].start()
    
    return jsonify({
        'message': 'Multi-krypto simulering startad!',
        'coins': len(all_data),
        'total_points': max([len(df) for df in all_data.values()])
    })

@app.route('/api/stop_simulation', methods=['POST'])
def stop_simulation():
    """Stoppar simuleringen"""
    global simulation_data
    simulation_data['is_running'] = False
    return jsonify({'message': 'Simulering stoppad'})

@app.route('/api/reset_simulation', methods=['POST'])
def reset_simulation():
    """Återställer simuleringen"""
    global simulation_data
    simulation_data['is_running'] = False
    simulation_data['data'] = {}
    simulation_data['current_index'] = 0
    simulation_data['portfolios'] = {}
    simulation_data['trades'] = {}
    simulation_data['total_value'] = 10000
    return jsonify({'message': 'Simulering återställd'})

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)