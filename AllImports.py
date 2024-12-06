import numpy as np
import time
from random import shuffle
from copy import deepcopy
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

from polygon import RESTClient

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, CreateWatchlistRequest, GetCalendarRequest, StopLossRequest
from alpaca.trading.stream import TradingStream
from alpaca.common.exceptions import APIError

import threading

import os
import csv
from alpaca.trading.client import TradingClient

import datetime
import time
import configparser

from urllib3.exceptions import MaxRetryError
from requests import ConnectionError
API_KEYS_POL = None
API_KEY_AL = None
SECRET_AL = None

def init_config():
    abspath = os.path.abspath(__file__)
    dname = os.path.dirname(abspath)
    os.chdir(dname)
    all_files = os.listdir()
    if "config.ini" not in all_files:
        _create_config_file()
    config = configparser.ConfigParser()
    config.read('config.ini')
    global API_KEY_AL, API_KEYS_POL, SECRET_AL
    API_KEYS_POL = config.get('POLYGON', 'api_keys').split(sep=' ')
    API_KEY_AL = config.get('ALPACA', 'api_key')
    SECRET_AL = config.get('ALPACA', 'secret')
    return
    
def _create_config_file():
    config = configparser.ConfigParser()
    while True:
        api_keys = _prompt_polygon()
        x = input("Would you like to redo this section? (n for \"No\", any other key for \"Yes\")")
        if x !="n":    continue
        api_keys = ' '.join(api_keys)
        config['POLYGON'] = {"api_keys" : api_keys}
        break
    while True:
        api_key, secret = _prompt_alpaca()
        x = input("Would you like to redo this section? (n for \"No\", any other key for \"Yes\")")
        if x != "n":    continue
        config['ALPACA'] = {"api_key" : api_key, "secret": secret}
        break
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    print("Created file.")
    
def _prompt_polygon():
    all_api_keys = list()
    count = 1
    print("API Keys needed for Polygon.\nAlternatively, type NEXT to insert Alpaca keys next.\n")
    while True:
        api_key = input(f"Please enter API #{count} key:\t")
        if api_key.upper() == "NEXT":
            if len(all_api_keys) == 0:
                print("Error: No api keys inserted. You must enter one before continuing.")
            else:   break
        elif len(api_key) != 32: print("Error: Please enter a valid API_Key of 32 units")
        else:   
            all_api_keys.append(api_key)
            count += 1
    return all_api_keys

def _prompt_alpaca():
    print("API Key and Secret needed for Alpaca")
    api_key, secret = '', ''
    while True:
        api_key = input("Please enter API key:\t")
        if len(api_key) != 20: print("Error: Please enter a valid API_Key of 20 units")
        else: 
            break
    print("\nSecret needed for Alpaca.")
    while True:
        secret = input("Please enter secret:\t")
        if len(secret) != 40: print("Error: Please enter a valid Secret_Key of 40 units")
        else:
            break
    return api_key, secret


init_config()
        