import time
import requests
# Removed webbrowser as we don't want to open new windows
# import webbrowser
from smartcard.System import readers
from smartcard.util import toHexString


def get_uid(reader):
    try:
        connection = reader.createConnection()
        connection.connect()
        print(f"Successfully connected to reader: {reader}")  # Debug line

        command = [0xFF, 0xCA, 0x00, 0x00, 0x00]
        response, sw1, sw2 = connection.transmit(command)
        print(f"Response received - SW1: {sw1}, SW2: {sw2}")  # Debug line

        if sw1 == 0x90:
            return toHexString(response)
        else:
            print(f"Error response from reader: SW1={sw1:02x}, SW2={sw2:02x}")
            return None
    except Exception as e:
        print(f"Error connecting to reader: {str(e)}")
        return None


def main():
    print("📡 NFC Scanner started.")
    last_uid = None

    while True:
        reader_list = readers()
        if not reader_list:
            print("❗ Ingen skanner fundet. Prøver igen...")
            time.sleep(1)
            continue

        reader = reader_list[0]
        uid = get_uid(reader)

        if uid and uid != last_uid:
            print(f"📲 Detekteret tag: {uid}")
            try:
                # This is the core action: sending the UID to your Flask app
                response = requests.post("http://127.0.0.1:5000/api/scan", json={"uid": uid})

                try:
                    data = response.json()
                except Exception:
                    print("❌ Server svarede ikke med gyldig JSON.")
                    data = {}

                if response.status_code == 200:
                    print("✅ Kendt UID:", data.get("name"))
                    # Removed the webbrowser.open() call here
                    # redirect_url = data.get("redirect_url")
                    # if redirect_url:
                    #     webbrowser.open(f"http://127.0.0.1:5000{redirect_url}")

                elif response.status_code == 403 and data.get("status") == "expired":
                    print(f"⚠️  Abonnement udløbet for: {data.get('name')}")
                elif response.status_code == 404 and data.get("status") == "new":
                    print("🆕 Ukendt kort! Handling handled by server response.")
                    # Removed the webbrowser.open() call here
                    # if "redirect_url" in data:
                    #     webbrowser.open(f"http://127.0.0.1:5000{data['redirect_url']}")
                else:
                    print("❓ Uventet svar:", data)

            except requests.RequestException as e:
                print("❌ Fejl ved kontakt til server:", e)

            last_uid = uid

        elif not uid and last_uid:
            print("💤 Kort fjernet")
            last_uid = None

        time.sleep(1)


if __name__ == "__main__":
    main()
