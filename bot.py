import requests
import time
import json
from datetime import datetime, timedelta
from prettytable import PrettyTable
from functools import wraps
import os
import signal

class APIClient:
    BASE_URL = "https://kaleidofinance.xyz/api/testnet"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'MinerBot/1.0'})
    
    def handle_errors(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(5):
                try:
                    return func(*args, **kwargs)
                except (requests.ConnectionError, requests.Timeout) as e:
                    print(f"Network error: {e}, retry {attempt+1}/5")
                    time.sleep(2**attempt)
                except requests.RequestException as e:
                    print(f"Request failed: {e}")
                    break
            return None
        return wrapper
    
    @handle_errors
    def check_registration(self, address):
        return self.session.get(f"{self.BASE_URL}/check-registration?wallet={address}")
    
    @handle_errors
    def update_balance(self, address, earnings_data):
        return self.session.post(
            f"{self.BASE_URL}/update-balance",
            json={"wallet": address, "earnings": earnings_data}
        )

class MiningSession:
    def __init__(self, wallet_address):
        self.wallet = wallet_address
        self.file_name = f"{self.wallet}_mining.dat"
        self.data = {
            'start_time': None,
            'total_earned': 0.0,
            'paid_out': 0.0,
            'referral_bonus': 0.0
        }
    
    def exists(self):
        return os.path.exists(self.file_name)
    
    def load(self):
        try:
            with open(self.file_name, 'r') as f:
                self.data = json.load(f)
                return True
        except Exception as e:
            print(f"Error loading session: {e}")
            return False
    
    def save(self):
        with open(self.file_name, 'w') as f:
            json.dump(self.data, f, indent=2)

class CryptoMiner:
    BASE_HASHRATE = 75.5  # MH/s
    POWER_CONSUMPTION = 120  # Watts
    
    def __init__(self, wallet_address, miner_id):
        self.client = APIClient()
        self.miner_id = miner_id
        self.wallet = wallet_address
        self.session = MiningSession(wallet_address)
        self.active = False
        self.start_time = None
        
        if self.session.exists():
            self.session.load()
    
    def _calculate_production(self):
        operational_time = time.time() - self.session.data['start_time']
        base_production = self.BASE_HASHRATE * operational_time * 0.0001
        return base_production * (1 + self.session.data['referral_bonus'])
    
    def display_stats(self):
        tbl = PrettyTable()
        tbl.field_names = ["Metric", "Value"]
        tbl.align = "l"
        
        tbl.add_row(["Wallet", self.wallet[:8] + '...' + self.wallet[-4:]])
        tbl.add_row(["Uptime", str(timedelta(seconds=int(time.time() - self.start_time)))])
        tbl.add_row(["Hashrate", f"{self.BASE_HASHRATE} MH/s"])
        tbl.add_row(["Total Earned", f"{self.session.data['total_earned']:.6f} KLDO"])
        tbl.add_row(["Pending", f"{self._calculate_production():.6f} KLDO"])
        tbl.add_row(["Referral Bonus", f"{self.session.data['referral_bonus']*100:.1f}%"])
        
        print("\nCurrent Mining Status:")
        print(tbl)
    
    def initialize_miner(self):
        response = self.client.check_registration(self.wallet)
        if not response or not response.json().get('isRegistered'):
            print(f"Miner {self.miner_id} - Wallet not registered!")
            return False
        
        if not self.session.data['start_time']:
            self.session.data['start_time'] = time.time()
            user_data = response.json().get('userData', {})
            self.session.data['referral_bonus'] = user_data.get('referralBonus', 0.0)
        
        self.start_time = self.session.data['start_time']
        self.active = True
        return True
    
    def _update_server_balance(self, final=False):
        current_production = self._calculate_production()
        
        new_balance = {
            'total': self.session.data['total_earned'] + current_production,
            'pending': 0.0 if final else current_production,
            'paid': self.session.data['paid_out'] + (current_production if final else 0)
        }
        
        if self.client.update_balance(self.wallet, new_balance):
            if final:
                self.session.data['paid_out'] = new_balance['paid']
            self.session.data['total_earned'] = new_balance['total']
            self.session.save()
            return True
        return False
    
    def run_mining_cycle(self):
        try:
            while self.active:
                cycle_start = time.time()
                
                # Mining interval
                while time.time() - cycle_start < 30:
                    time.sleep(1)
                
                # Update balance every 30 seconds
                if self._update_server_balance():
                    self.display_stats()
                    
        except KeyboardInterrupt:
            self.shutdown()
    
    def shutdown(self):
        self.active = False
        self._update_server_balance(final=True)
        print(f"Miner {self.miner_id} stopped. Total paid: {self.session.data['paid_out']:.6f} KLDO")

class MiningSupervisor:
    def __init__(self):
        self.miners = []
    
    def load_addresses(self):
        try:
            with open('wallets.txt', 'r') as f:
                return [line.strip() for line in f if line.startswith('0x')]
        except FileNotFoundError:
            print("Wallet file not found!")
            return []
    
    def start_operation(self):
        addresses = self.load_addresses()
        if not addresses:
            return
        
        print(f"Initializing {len(addresses)} mining instances...")
        self.miners = [CryptoMiner(addr, i+1) for i, addr in enumerate(addresses)]
        
        for miner in self.miners:
            if miner.initialize_miner():
                miner.display_stats()
            else:
                self.miners.remove(miner)
        
        signal.signal(signal.SIGINT, self.emergency_stop)
        
        # Start mining threads
        for miner in self.miners:
            miner.run_mining_cycle()
    
    def emergency_stop(self, signum, frame):
        print("\nInitiating shutdown sequence...")
        for miner in self.miners:
            miner.shutdown()
        exit()

if __name__ == "__main__":
    controller = MiningSupervisor()
    controller.start_operation()
