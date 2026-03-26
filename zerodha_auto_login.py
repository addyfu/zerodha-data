"""
Zerodha Auto Login
==================
Automatically logs into Zerodha and gets enctoken.
No manual intervention needed!

Requirements:
- Your Zerodha User ID
- Your Password
- Your TOTP Secret (from when you set up 2FA)
"""

import requests
import pyotp
import time
import os
from urllib.parse import urlparse, parse_qs


class ZerodhaAutoLogin:
    """
    Automatically login to Zerodha and get enctoken.
    
    How to get TOTP Secret:
    1. Go to Zerodha Console → My Account → Security
    2. Click "Reset TOTP" or "Setup TOTP"
    3. When shown the QR code, click "Can't scan? Enter manually"
    4. Copy the secret key (looks like: ABCD1234EFGH5678)
    5. Save this secret - it's used to generate TOTP codes
    """
    
    LOGIN_URL = "https://kite.zerodha.com/api/login"
    TWOFA_URL = "https://kite.zerodha.com/api/twofa"
    
    def __init__(self, user_id: str, password: str, totp_secret: str):
        """
        Initialize with credentials.

        Args:
            user_id: Your Zerodha client ID (e.g., AB1234)
            password: Your Zerodha password
            totp_secret: Your TOTP secret key (NOT the 6-digit code)
        """
        self.user_id = user_id
        self.password = password
        self.totp_secret = totp_secret.replace(" ", "").upper()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })
    
    def generate_totp(self) -> str:
        """Generate current TOTP code."""
        totp = pyotp.TOTP(self.totp_secret)
        return totp.now()
    
    def login(self) -> dict:
        """
        Perform full login and return enctoken.
        
        Returns:
            dict with 'success', 'enctoken', 'user_id', 'error'
        """
        result = {
            'success': False,
            'enctoken': None,
            'user_id': self.user_id,
            'error': None
        }
        
        try:
            # Step 0: Visit login page with browser-like headers to pass Cloudflare
            self.session.headers.update({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            self.session.get("https://kite.zerodha.com/", timeout=15)

            # Switch to API headers for subsequent requests
            self.session.headers.update({
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://kite.zerodha.com",
                "Referer": "https://kite.zerodha.com/",
                "X-Kite-Version": "3.0.0",
            })

            # Step 1: Initial login with user_id and password
            print(f"[1/3] Logging in as {self.user_id}...")

            login_data = {
                "user_id": self.user_id,
                "password": self.password
            }

            response = self.session.post(self.LOGIN_URL, data=login_data, timeout=30)
            
            if response.status_code != 200:
                result['error'] = f"Login failed: HTTP {response.status_code}"
                return result
            
            login_response = response.json()
            
            if login_response.get("status") != "success":
                result['error'] = f"Login failed: {login_response.get('message', 'Unknown error')}"
                return result
            
            request_id = login_response.get("data", {}).get("request_id")
            if not request_id:
                result['error'] = "No request_id in login response"
                return result
            
            print("[2/3] Submitting TOTP...")
            
            # Step 2: Submit TOTP
            # Wait a moment to ensure TOTP is fresh
            time.sleep(1)
            totp_code = self.generate_totp()
            
            twofa_data = {
                "user_id": self.user_id,
                "request_id": request_id,
                "twofa_value": totp_code,
                "twofa_type": "totp"
            }
            
            response = self.session.post(self.TWOFA_URL, data=twofa_data, timeout=30)
            
            if response.status_code != 200:
                result['error'] = f"2FA failed: HTTP {response.status_code}"
                return result
            
            twofa_response = response.json()
            
            if twofa_response.get("status") != "success":
                result['error'] = f"2FA failed: {twofa_response.get('message', 'Unknown error')}"
                return result
            
            print("[3/3] Extracting enctoken...")
            
            # Step 3: Extract enctoken from cookies
            enctoken = None
            for cookie in self.session.cookies:
                if cookie.name == "enctoken":
                    enctoken = cookie.value
                    break
            
            if not enctoken:
                result['error'] = "Could not find enctoken in cookies"
                return result
            
            result['success'] = True
            result['enctoken'] = enctoken
            print(f"✅ Login successful! Token length: {len(enctoken)}")
            
            return result
            
        except requests.exceptions.RequestException as e:
            result['error'] = f"Network error: {e}"
            return result
        except Exception as e:
            result['error'] = f"Error: {e}"
            return result
    
    def verify_token(self, enctoken: str) -> bool:
        """Verify if a token is valid."""
        try:
            headers = {"Authorization": f"enctoken {enctoken}"}
            response = requests.get(
                "https://kite.zerodha.com/oms/user/profile",
                headers=headers,
                timeout=10
            )
            return response.status_code == 200 and response.json().get("status") == "success"
        except:
            return False


def get_enctoken(user_id: str = None, password: str = None, totp_secret: str = None) -> str:
    """
    Convenience function to get enctoken.
    Reads from environment variables if not provided.
    
    Environment variables:
        ZERODHA_USER_ID
        ZERODHA_PASSWORD
        ZERODHA_TOTP_SECRET
    """
    user_id = user_id or os.environ.get("ZERODHA_USER_ID")
    password = password or os.environ.get("ZERODHA_PASSWORD")
    totp_secret = totp_secret or os.environ.get("ZERODHA_TOTP_SECRET")
    
    if not all([user_id, password, totp_secret]):
        raise ValueError(
            "Missing credentials. Provide via arguments or environment variables:\n"
            "  ZERODHA_USER_ID, ZERODHA_PASSWORD, ZERODHA_TOTP_SECRET"
        )
    
    login = ZerodhaAutoLogin(user_id, password, totp_secret)
    result = login.login()
    
    if result['success']:
        return result['enctoken']
    else:
        raise Exception(result['error'])


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Zerodha Auto Login")
    parser.add_argument("--user-id", "-u", help="Zerodha User ID")
    parser.add_argument("--password", "-p", help="Zerodha Password")
    parser.add_argument("--totp-secret", "-t", help="TOTP Secret Key")
    parser.add_argument("--save", "-s", action="store_true", help="Save token to enctoken.txt")
    
    args = parser.parse_args()
    
    try:
        enctoken = get_enctoken(args.user_id, args.password, args.totp_secret)
        
        if args.save:
            with open("enctoken.txt", "w") as f:
                f.write(enctoken)
            print(f"Token saved to enctoken.txt")
        else:
            print(f"\nEnctoken:\n{enctoken}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        exit(1)
