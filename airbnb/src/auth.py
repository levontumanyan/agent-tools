import shutil
import sqlite3
import subprocess
from pathlib import Path


def get_brave_cookies():
	"""
	Automatically extracts and decrypts Airbnb session cookies from Brave Browser on macOS.
	Returns a dictionary of cookie name -> value.
	"""
	try:
		cmd = ["security", "find-generic-password", "-w", "-s", "Brave Safe Storage"]
		res = subprocess.run(cmd, capture_output=True, text=True, check=True)
		password = res.stdout.strip().encode("utf-8")

		from cryptography.hazmat.primitives import hashes
		from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
		from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

		kdf = PBKDF2HMAC(
			algorithm=hashes.SHA1(),
			length=16,
			salt=b"saltysalt",
			iterations=1003,
		)
		key = kdf.derive(password)

		cookie_db = (
			Path.home()
			/ "Library/Application Support/BraveSoftware/Brave-Browser/Default/Cookies"
		)
		if not cookie_db.exists():
			return {}

		tmp_path = Path("/tmp/brave_airbnb_cookies.db")
		shutil.copy2(cookie_db, tmp_path)
		conn = sqlite3.connect(tmp_path)
		c = conn.cursor()
		c.execute(
			"SELECT host_key, name, encrypted_value FROM cookies WHERE host_key LIKE '%airbnb%'"
		)
		rows = c.fetchall()
		conn.close()
		tmp_path.unlink(missing_ok=True)

		cookies = {}
		for host, name, enc_val in rows:
			if enc_val and enc_val[:3] == b"v10":
				enc_data = enc_val[3:]
				iv = b" " * 16
				cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
				dec = cipher.decryptor().update(enc_data)
				pad = dec[-1]
				raw_val = dec[32:-pad] if pad <= 16 else dec[32:]
				val = raw_val.decode("utf-8", errors="ignore")
				if val:
					cookies[name] = val
		return cookies
	except Exception:
		return {}
