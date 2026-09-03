import sys
import os
import json
import urllib.request

# Default message or user-provided message from CLI
default_text = "مرحبا، بدي شقة 3 غرف نوم للبيع في دابوق أو عبدون"
message_text = sys.argv[1] if len(sys.argv) > 1 else default_text
phone_number = "962799887766"
customer_name = "Tareq Al-Husseini"

print("=" * 65)
print("[SIMULATION] EUREKA JO - SIMULATED INBOUND WHATSAPP MESSAGE")
print("=" * 65)
print(f"Customer Name : {customer_name}")
print(f"Customer Phone: +{phone_number}")
print(f"Message Text  : {message_text.encode('ascii', 'replace').decode('ascii')}")
print("-" * 65)

# Meta WhatsApp Inbound Webhook Payload Format
payload = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "1587149902942521",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "15556712685",
                            "phone_number_id": "109283746501928",
                        },
                        "contacts": [
                            {
                                "profile": {"name": customer_name},
                                "wa_id": phone_number,
                            }
                        ],
                        "messages": [
                            {
                                "from": phone_number,
                                "id": f"wamid.SIMULATED_{os.urandom(4).hex().upper()}",
                                "timestamp": "1724950000",
                                "type": "text",
                                "text": {"body": message_text},
                            }
                        ],
                    },
                    "field": "messages",
                }
            ],
        }
    ],
}

url = "http://localhost:8000/webhook/whatsapp"
data_bytes = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(
    url,
    data=data_bytes,
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    print(f"1. Sending simulated message to FastAPI Webhook ({url})...")
    with urllib.request.urlopen(req, timeout=10) as res:
        print(f"   [OK] Webhook fast-ACK response: HTTP {res.status}")

    print("\n2. The background pipeline is now:")
    print("   - Upserting contact & checking the 24-hour conversation window")
    print("   - Logging customer inbound message")
    print("   - Calling your LIVE n8n AI Agent at https://eurekajo.app.n8n.cloud")
    print("   - Receiving the AI Agent's real response & saving it to the database")

    print("\n3. OPEN YOUR BROWSER:")
    print("   -> Go to: http://localhost:3000/conversations")
    print("   -> Log in if prompted (admin@eurekajo.com / Admin@123456)")
    print("   -> You will see Tareq Al-Husseini's conversation thread with the AI bot's reply!")
    print("=" * 65)

except Exception as e:
    print(f"[ERROR]: Could not reach backend: {e}")
