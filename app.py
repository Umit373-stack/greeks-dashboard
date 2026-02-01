from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import yfinance as yf
import numpy as np
import pandas as pd
from scipy.stats import norm
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change_me_in_production_12345')

# IDENTIFIANTS
USERNAME = os.environ.get('DASH_USERNAME', 'trader')
PASSWORD = os.environ.get('DASH_PASSWORD', 'greeks2026')

class GreeksCalculator:
    @staticmethod
    def calculate_greeks(S, K, T, r, sigma):
        if T <= 0 or sigma <= 0:
            return {'gamma': 0, 'vanna': 0, 'charm': 0}
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        vanna = -norm.pdf(d1) * d2 / sigma
        charm = -norm.pdf(d1) * (2 * r * T - d2 * sigma * np.sqrt(T)) / (2 * T * sigma * np.sqrt(T))
        
        return {'gamma': gamma, 'vanna': vanna, 'charm': charm}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == USERNAME and password == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Identifiants incorrects')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    dte = int(request.args.get('dte', 0))
    ticker = request.args.get('ticker', 'SPY').upper()
    
    try:
        stock = yf.Ticker(ticker)
        spot_price = stock.history(period='1d')['Close'].iloc[-1]
        expirations = stock.options
        
        if len(expirations) == 0:
            return jsonify({'error': 'No options data'}), 500
        
        target_date = datetime.now() + timedelta(days=dte)
        selected_exp = min(expirations, key=lambda x: abs((datetime.strptime(x, '%Y-%m-%d') - target_date).days))
        
        opt_chain = stock.option_chain(selected_exp)
        exp_date = datetime.strptime(selected_exp, '%Y-%m-%d')
        days_to_exp = (exp_date - datetime.now()).days
        T = max(days_to_exp / 365.0, 1/365)
        r = 0.05
        
        if dte >= 98:
            strike_range = 120
            min_strike = (int(spot_price - strike_range) // 5) * 5
            max_strike = ((int(spot_price + strike_range) // 5) + 1) * 5
            all_strikes = list(range(min_strike, max_strike, 5))
        else:
            strike_range = 30
            min_strike = int(spot_price - strike_range)
            max_strike = int(spot_price + strike_range) + 1
            all_strikes = list(range(min_strike, max_strike))
        
        call_gex = []
        put_gex = []
        call_vanna = []
        put_vanna = []
        call_charm = []
        put_charm = []
        
        for strike in all_strikes:
            calls = opt_chain.calls[opt_chain.calls['strike'] == strike]
            puts = opt_chain.puts[opt_chain.puts['strike'] == strike]
            
            call_oi = calls['openInterest'].iloc[0] if len(calls) > 0 else 0
            put_oi = puts['openInterest'].iloc[0] if len(puts) > 0 else 0
            
            call_iv = calls['impliedVolatility'].iloc[0] if len(calls) > 0 and call_oi > 0 else 0.3
            put_iv = puts['impliedVolatility'].iloc[0] if len(puts) > 0 and put_oi > 0 else 0.3
            
            if call_oi > 0 and call_iv > 0:
                greeks = GreeksCalculator.calculate_greeks(spot_price, strike, T, r, call_iv)
                call_gex.append(greeks['gamma'] * call_oi * 100 * spot_price * spot_price * 0.01 / 1e6)
                call_vanna.append(greeks['vanna'] * call_oi * 100)
                call_charm.append(greeks['charm'] * call_oi * 100)
            else:
                call_gex.append(0)
                call_vanna.append(0)
                call_charm.append(0)
            
            if put_oi > 0 and put_iv > 0:
                greeks = GreeksCalculator.calculate_greeks(spot_price, strike, T, r, put_iv)
                put_gex.append(greeks['gamma'] * put_oi * 100 * spot_price * spot_price * 0.01 * -1 / 1e6)
                put_vanna.append(greeks['vanna'] * put_oi * 100 * -1)
                put_charm.append(greeks['charm'] * put_oi * 100 * -1)
            else:
                put_gex.append(0)
                put_vanna.append(0)
                put_charm.append(0)
        
        total_gex = [c + p for c, p in zip(call_gex, put_gex)]
        total_vanna = [c + p for c, p in zip(call_vanna, put_vanna)]
        total_charm = [c + p for c, p in zip(call_charm, put_charm)]
        
        return jsonify({
            'ticker': ticker,
            'spot': spot_price,
            'expiration': selected_exp,
            'dte': days_to_exp,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'strikes': all_strikes,
            'call_gex': call_gex,
            'put_gex': put_gex,
            'total_gex': total_gex,
            'call_vanna': call_vanna,
            'put_vanna': put_vanna,
            'total_vanna': total_vanna,
            'call_charm': call_charm,
            'put_charm': put_charm,
            'total_charm': total_charm
        })
    
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({'error': str(e)}), 500

# ========== NOUVELLE ROUTE POUR TRADINGVIEW ==========
@app.route('/api/tradingview-csv')
def tradingview_csv():
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    dte = int(request.args.get('dte', 0))
    ticker = request.args.get('ticker', 'SPY').upper()
    
    try:
        stock = yf.Ticker(ticker)
        spot_price = stock.history(period='1d')['Close'].iloc[-1]
        expirations = stock.options
        
        if len(expirations) == 0:
            return jsonify({'error': 'No options data', 'csv': ''}), 500
        
        target_date = datetime.now() + timedelta(days=dte)
        selected_exp = min(expirations, key=lambda x: abs((datetime.strptime(x, '%Y-%m-%d') - target_date).days))
        
        opt_chain = stock.option_chain(selected_exp)
        exp_date = datetime.strptime(selected_exp, '%Y-%m-%d')
        days_to_exp = (exp_date - datetime.now()).days
        T = max(days_to_exp / 365.0, 1/365)
        r = 0.05
        
        if dte >= 98:
            strike_range = 120
            min_strike = (int(spot_price - strike_range) // 5) * 5
            max_strike = ((int(spot_price + strike_range) // 5) + 1) * 5
            all_strikes = list(range(min_strike, max_strike, 5))
        else:
            strike_range = 30
            min_strike = int(spot_price - strike_range)
            max_strike = int(spot_price + strike_range) + 1
            all_strikes = list(range(min_strike, max_strike))
        
        gex_data = []
        vanna_data = []
        charm_data = []
        
        for strike in all_strikes:
            calls = opt_chain.calls[opt_chain.calls['strike'] == strike]
            puts = opt_chain.puts[opt_chain.puts['strike'] == strike]
            
            call_oi = calls['openInterest'].iloc[0] if len(calls) > 0 else 0
            put_oi = puts['openInterest'].iloc[0] if len(puts) > 0 else 0
            call_iv = calls['impliedVolatility'].iloc[0] if len(calls) > 0 and call_oi > 0 else 0.3
            put_iv = puts['impliedVolatility'].iloc[0] if len(puts) > 0 and put_oi > 0 else 0.3
            
            total_gex = 0
            total_vanna = 0
            total_charm = 0
            
            if call_oi > 0 and call_iv > 0:
                greeks = GreeksCalculator.calculate_greeks(spot_price, strike, T, r, call_iv)
                total_gex += greeks['gamma'] * call_oi * 100 * spot_price * spot_price * 0.01 / 1e6
                total_vanna += greeks['vanna'] * call_oi * 100
                total_charm += greeks['charm'] * call_oi * 100
            
            if put_oi > 0 and put_iv > 0:
                greeks = GreeksCalculator.calculate_greeks(spot_price, strike, T, r, put_iv)
                total_gex += greeks['gamma'] * put_oi * 100 * spot_price * spot_price * 0.01 * -1 / 1e6
                total_vanna += greeks['vanna'] * put_oi * 100 * -1
                total_charm += greeks['charm'] * put_oi * 100 * -1
            
            gex_data.append((strike, abs(total_gex)))
            vanna_data.append((strike, abs(total_vanna)))
            charm_data.append((strike, abs(total_charm)))
        
        top_gex = sorted(gex_data, key=lambda x: x[1], reverse=True)[:5]
        top_vanna = sorted(vanna_data, key=lambda x: x[1], reverse=True)[:5]
        top_charm = sorted(charm_data, key=lambda x: x[1], reverse=True)[:5]
        
        csv_lines = []
        csv_lines.append("GAMMA," + ",".join([str(s[0]) for s in top_gex]))
        csv_lines.append("VANNA," + ",".join([str(s[0]) for s in top_vanna]))
        csv_lines.append("CHARM," + ",".join([str(s[0]) for s in top_charm]))
        
        csv_text = "\n".join(csv_lines)
        
        return jsonify({
            'csv': csv_text,
            'ticker': ticker,
            'spot': spot_price,
            'expiration': selected_exp,
            'dte': days_to_exp,
            'timestamp': datetime.now().strftime('%H:%M:%S')
        })
    
    except Exception as e:
        print(f"Erreur: {e}")
        return jsonify({'error': str(e), 'csv': ''}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
