import time
import requests
import webbrowser
from smartcard.System import readers
from smartcard.util import toHexString

def get_uid(reader):
    try:
        connection = reader.createConnection()
        connection.connect()

        command = [0xFF, 0xCA, 0x00, 0x00, 0x00]
        response, sw1, sw2 = connection.transmit(command)

        if sw1 == 0x90:
            return toHexString(response)
    except Exception:
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
                response = requests.post("http://127.0.0.1:5000/api/scan", json={"uid": uid})
                data = response.json()

                if response.status_code == 200:
                    data = response.json()
                    print("✅ Kendt UID:", data.get("name"))
                    redirect_url = data.get("redirect_url")
                    if redirect_url:
                        import webbrowser
                        webbrowser.open(f"http://127.0.0.1:5000{redirect_url}")

                elif response.status_code == 403 and data["status"] == "expired":
                    print(f"⚠️  Abonnement udløbet for: {data['name']}")
                elif response.status_code == 404 and data["status"] == "new":
                    print("🆕 Ukendt kort! Åbner registreringsside...")
                    webbrowser.open(f"http://127.0.0.1:5000{data['redirect_url']}")
                else:
                    print("❓ Uventet svar:", data)

            except Exception as e:
                print("❌ Fejl ved kontakt til server:", e)

            last_uid = uid

        elif not uid and last_uid:
            print("💤 Kort fjernet")
            last_uid = None

        time.sleep(1)

if __name__ == "__main__":
    main()
